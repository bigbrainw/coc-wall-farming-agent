#!/usr/bin/env python3
"""Live check of scrcpy_stream against a NON-live test device (no CoC needed).

  COC_ANDROID_SERIAL=emulator-5560 python3 test_scrcpy_stream.py

Changes Settings/Home on the device: never run against BlueStacks.
Checks: live-serial guard; static frame matches screencap; static screen is
reported as not flowing and observe() times out (callers use screencap);
freshness: once a screencap that shows a change has returned, wait_fresh(that
time) never returns a frame without the change; observe() latency while the screen animates;
idle CPU; clean stop. Exits non-zero on any failure.
"""
import os
import statistics as st
import subprocess
import sys
import threading
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrcpy_stream import LIVE_SERIALS, ScrcpyStream  # noqa: E402

SERIAL = os.environ.get("COC_ANDROID_SERIAL", "")
if not SERIAL or SERIAL in LIVE_SERIALS:
    sys.exit("set COC_ANDROID_SERIAL to a test device (never the live game)")
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def adb(*a, binary=False):
    r = subprocess.run(["adb", "-s", SERIAL, *a], capture_output=True)
    return r.stdout if binary else r.stdout.decode(errors="replace")


def screencap() -> np.ndarray:
    raw = adb("exec-out", "screencap", binary=True)
    w, h = int.from_bytes(raw[0:4], "little"), int.from_bytes(raw[4:8], "little")
    img = np.frombuffer(raw, np.uint8, offset=len(raw) - w * h * 4).reshape(h, w, 4)
    return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)


def diff(a, b) -> float:  # mean abs difference on a downscaled grey image (0-255)
    g = lambda x: cv2.resize(cv2.cvtColor(x, cv2.COLOR_BGR2GRAY), (160, 120)).astype(np.int16)
    return float(np.abs(g(a) - g(b)).mean())


# 1. guard
os.environ.pop("COC_ANDROID_ALLOW_LIVE", None)
try:
    ScrcpyStream("127.0.0.1:5555")
    check("live serial refused", False)
except RuntimeError as e:
    check("live serial refused", "refused" in str(e))

adb("shell", "am", "start", "-a", "android.settings.SETTINGS")
time.sleep(2)
s = ScrcpyStream(SERIAL).start()
cpu0 = time.process_time()
try:
    # 2. static picture equals screencap (H.264 residual only)
    time.sleep(1.5)
    d = diff(s.latest().image, screencap())
    check("static frame matches screencap", d < 6, f"mean abs diff {d:.2f}/255")

    # 3. static screen: not flowing, observe refuses to guess
    # a stray frame (status bar, cursor) can land inside the 0.6 s window:
    # require the stream to report "not flowing" within 3 s of stillness
    t_wait = time.time()
    while s.flowing() and time.time() - t_wait < 3:
        time.sleep(0.05)
    flowing = s.flowing()
    try:
        s.observe("/dev/null", timeout=0.4)
        timed_out = False
    except TimeoutError:
        timed_out = True
    check("static screen: not flowing and observe times out", not flowing and timed_out,
          f"flowing={flowing} timeout={timed_out}")

    # 3b. static mode: still screen -> newest frame without screencap; right
    # after a change -> never the old screen (fresh frame or TimeoutError)
    t0 = time.time()
    f = s.wait_static(time.time())
    still_ok = diff(f.image, screencap()) < 6
    stale_static, ok_static, to_static = 0, 0, 0
    for i in range(8):
        before = s.wait_static(time.time()).image.copy()
        cmd = ["shell", "input", "keyevent", "3"] if i % 2 == 0 else \
              ["shell", "am", "start", "-a", "android.settings.SETTINGS"]
        adb(*cmd)
        # request only once a returned screencap proves the change exists
        t_end = time.time() + 6
        while time.time() < t_end:
            img = screencap()
            t_req = time.time()
            if diff(img, before) > 8:
                break
        try:
            g = s.wait_static(t_req)
            if diff(g.image, before) > 8:
                ok_static += 1
            else:
                stale_static += 1
        except TimeoutError:
            to_static += 1  # safe: caller uses screencap
        time.sleep(2.5)
    check("static mode: still screen matches, never stale after change",
          still_ok and stale_static == 0,
          f"still match {still_ok}; after change ok {ok_static}, stale {stale_static}, timeouts {to_static}")

    # 4. freshness at screen changes
    stale, fresh, waits = 0, 0, []
    for i in range(10):
        before = s.latest().image.copy()
        cmd = ["shell", "input", "keyevent", "3"] if i % 2 == 0 else \
              ["shell", "am", "start", "-a", "android.settings.SETTINGS"]
        subprocess.Popen(["adb", "-s", SERIAL, *cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < 6:
            img = screencap()
            # the device grabbed this image somewhere between request and return;
            # its return time is a moment by which the change certainly existed
            tc = time.time()
            if diff(img, before) > 8:
                break
        try:
            f = s.wait_fresh(tc, timeout=2.0)
            waits.append((time.time() - tc) * 1000)
            if diff(f.image, before) > 8:
                fresh += 1
            else:
                stale += 1
        except TimeoutError:
            pass  # safe: caller would use screencap
        time.sleep(1.5)
    check("freshness: no stale frame after a change", stale == 0 and fresh >= 5,
          f"fresh {fresh}, stale {stale}, timeouts {10 - fresh - stale}")
    if waits:
        print(f"      wait for a frame captured after screencap saw the change: "
              f"median {st.median(waits):.0f} ms, max {max(waits):.0f} ms")

    # 5. observe latency while the screen animates (scrolling Settings)
    stop = threading.Event()

    def scroll():
        k = 0
        while not stop.is_set():
            y1, y2 = (700, 300) if k % 2 == 0 else (300, 700)
            adb("shell", "input", "swipe", "640", str(y1), "640", str(y2), "400")
            k += 1
    th = threading.Thread(target=scroll, daemon=True)
    th.start()
    time.sleep(1)
    lat, to = [], 0
    for _ in range(15):
        t0 = time.time()
        try:
            if s.flowing():
                s.wait_fresh(t0, timeout=1.2)
                lat.append((time.time() - t0) * 1000)
        except TimeoutError:
            to += 1
        time.sleep(0.2)
    stop.set()
    th.join(timeout=5)
    check("animating screen: fresh frames obtained", len(lat) >= 10,
          f"{len(lat)} ok, {to} timeouts; median {st.median(lat) if lat else 0:.0f} ms, "
          f"max {max(lat) if lat else 0:.0f} ms")

    # 6. CPU of this process (decoder thread) per wall second
    cpu = (time.process_time() - cpu0)
    print(f"      decoder process CPU {cpu:.1f} s over the test; frames {s.frames_decoded}, "
          f"packets {s.packets}, {s.bytes_received / 1e6:.1f} MB")
    c0, w0 = time.process_time(), time.time()
    time.sleep(4)
    idle = (time.process_time() - c0) / (time.time() - w0) * 100
    check("idle CPU low", idle < 5, f"{idle:.1f}% of one core on a static screen")
finally:
    s.stop()

# 7. clean stop
fw = adb("forward", "--list")
check("forward removed after stop", f"tcp:{s.port}" not in fw)
t0 = time.time()
while time.time() - t0 < 5:
    left = [l for l in adb("shell", "ps -A -o ARGS").splitlines() if "coc-scrcpy-stream.jar" in l]
    if not left:
        break
    time.sleep(0.25)
check("server process ended", not left, f"{time.time() - t0:.1f} s after stop")

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
