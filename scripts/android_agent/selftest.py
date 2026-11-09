#!/usr/bin/env python3
"""Self-test for coc_android against a NON-live test device (no CoC needed).

  COC_ANDROID_SERIAL=emulator-5560 python3 selftest.py

Opens Android Settings in landscape and checks: live-serial guard, controller
lock, tap accuracy (Settings -> Apps x10), swipe, two-pointer pinch reaching
InputDispatcher, batch guards, 20-input batch timing, 20 s time cap, dead
scrcpy server detection and cleanup. Exits non-zero on any failure.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coc_android import LIVE_SERIALS, Device, GuardError  # noqa: E402

SERIAL = os.environ.get("COC_ANDROID_SERIAL", "")
if not SERIAL or SERIAL in LIVE_SERIALS:
    sys.exit("set COC_ANDROID_SERIAL to a test device (never the live game)")
TMP = tempfile.mkdtemp(prefix="coc_android_selftest_")
results = []


def adb(cmd):
    return subprocess.run(["adb", "-s", SERIAL, "shell", cmd], capture_output=True, text=True).stdout


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")


def top():
    o = adb("dumpsys activity activities | grep -m1 topResumedActivity")
    return "Sub" if "SubSettings" in o else "Main" if "Settings" in o else "other"


adb("wm user-rotation lock 1; "
    "am force-stop com.android.settings; am start -W -a android.settings.SETTINGS")
time.sleep(2)

for live in sorted(LIVE_SERIALS):
    try:
        Device(live)
        check(f"refuse live {live}", False)
    except GuardError:
        check(f"refuse live {live}", True)

d = Device(SERIAL)
d._ctl()
try:
    Device(SERIAL)
    check("controller lock", False)
except GuardError:
    check("controller lock", True)

end = time.time() + 5  # rotation applies asynchronously after launch
while d.size() != (1920, 1080) and time.time() < end:
    # Launching Settings from the portrait-locked launcher can reset the lock.
    adb("wm user-rotation lock 1")
    time.sleep(0.3)
w, h = d.size()
check("landscape size", (w, h) == (1920, 1080),
      f"{w}x{h} top={top()} {adb('wm user-rotation').strip()} "
      f"{adb('dumpsys window | grep -m1 -oE \"mRotation=[0-9]|mUserRotation=[A-Z_0-9]+\"').strip()}")

def wait_top(want, secs=4.0):
    end = time.time() + secs
    while time.time() < end:
        if top() == want:
            return True
    return False


ok = 0
for _ in range(10):
    # Fresh Settings each time: retained scroll/sub-pages would move "Apps".
    adb("am force-stop com.android.settings; am start -W -a android.settings.SETTINGS")
    wait_top("Main", 3)
    adb("wm user-rotation lock 1")
    time.sleep(0.5)  # let rotation/layout settle before tapping
    d.tap(315, 960)
    ok += wait_top("Sub")
check("tap accuracy Settings->Apps", ok == 10, f"{ok}/10")

a = d.observe(f"{TMP}/a.png")
d.swipe(960, 900, 960, 300, 300)
time.sleep(1)
b = d.observe(f"{TMP}/b.png")
check("swipe changes screen", open(a["path"], "rb").read() != open(b["path"], "rb").read())

d.pinch("out")
acts = re.findall(r"MotionEvent\(.*?action=([A-Z_0-9()]+)", adb("dumpsys input"))
check("pinch two pointers", any(x.startswith("POINTER_UP") for x in acts[-8:]), str(acts[-3:]))

tap = lambda i: {"label": f"t{i}", "point": [1000, 60], "kind": "select"}  # noqa: E731
for name, batch in [
    ("21 inputs", {"id": "g1", "actions": [tap(i) for i in range(21)]}),
    ("spawn w/o evidence", {"id": "g2", "actions": [{"label": "s", "point": [300, 300], "kind": "spawn"}]}),
    ("spawn legal flag only", {"id": "g3", "actions": [{"label": "s", "point": [300, 300], "kind": "spawn"}],
                               "checkpoint": {"legalSpawns": [{"point": [300, 300], "legal": True}]}}),
    ("stale frame size", {"id": "g5", "actions": [tap(0)], "checkpoint": {"size": [1080, 1920]}}),
    ("off-screen point (no partial batch)", {"id": "g4", "actions": [tap(0), {"label": "x", "point": [5000, 10], "kind": "select"}]}),
]:
    try:
        d.run_batch(batch, f"{TMP}/g.png")
        check(f"refuse {name}", False)
    except GuardError:
        check(f"refuse {name}", True)

r = d.run_batch({"id": "b20", "actions": [tap(i) for i in range(20)]}, f"{TMP}/b20.png")
check("20-tap batch inputs < 3 s", r["inputMs"] < 3000 and len(r["issued"]) == 20,
      f"inputs {r['inputMs']} ms, with settle+observe {r['elapsedMs']} ms")
try:
    d.run_batch({"id": "b20", "actions": [tap(0)]}, f"{TMP}/x.png")
    check("refuse replayed id", False)
except GuardError:
    check("refuse replayed id", True)

orig = d.tap
d.tap = lambda x, y: (time.sleep(1.5), orig(x, y))
r = d.run_batch({"id": "cap", "actions": [tap(i) for i in range(20)]}, f"{TMP}/cap.png")
d.tap = orig
check("20 s time cap", r["stopped"] == "time_cap" and len(r["issued"]) < 20, f"{len(r['issued'])} issued")

adb("pkill -f com.genymobile.scrcpy.Server")
time.sleep(1)
try:
    for _ in range(5):
        d.tap(1000, 60)
        time.sleep(0.2)
    check("dead server detected", False)
except OSError:
    check("dead server detected", True)
d.close()
time.sleep(1)
check("cleanup", adb("ps -A | grep -c app_process").strip() == "0"
      and not subprocess.run(["adb", "-s", SERIAL, "forward", "--list"], capture_output=True, text=True).stdout.strip())

print(f"\n{sum(results)}/{len(results)} passed")
sys.exit(0 if all(results) else 1)
