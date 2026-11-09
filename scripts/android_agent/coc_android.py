#!/usr/bin/env python3
"""Agent-native Android controller over ADB (phase 1, TEST ONLY).

Not an active game controller. AGENTS.md still names native Codex CUA as the
only controller for the live game. This module refuses the live BlueStacks
serials unless COC_ANDROID_ALLOW_LIVE=1 is set after an approved handoff.

Input: scrcpy-server control socket by default (no root, multi-touch, ~40 ms
taps; see scrcpy_control.py). COC_ANDROID_INPUT=adb falls back to `input tap`
(~400 ms, no pinch). One controller per device is enforced with a lock file.
Re-run selftest.py against a test device after any change.

Usage (CLI):
  COC_ANDROID_SERIAL=emulator-5560 python3 coc_android.py info
  ... observe OUT.png | tap X Y | swipe X1 Y1 X2 Y2 MS | pinch in|out | batch FILE.json
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

ADB = shutil.which("adb") or "/opt/homebrew/bin/adb"
LIVE_SERIALS = {"emulator-5554", "127.0.0.1:5555", "localhost:5555"}
MAX_BATCH_INPUTS = 20
MAX_BATCH_SECONDS = 20.0
# CoC on BlueStacks reacts to a tap after ~0.4-0.8 s and screencap grabs the
# frame when it starts, so observing right after the last input returns the
# pre-input screen (seen live 2026-11-03). Wait before the post-batch observe.
SETTLE_SECONDS = float(os.environ.get("COC_ANDROID_SETTLE", "1.0"))


class GuardError(RuntimeError):
    pass


class Device:
    def __init__(self, serial: str | None = None):
        serial = serial or os.environ.get("COC_ANDROID_SERIAL")
        if not serial:
            raise GuardError("COC_ANDROID_SERIAL required; no default device")
        if serial in LIVE_SERIALS and os.environ.get("COC_ANDROID_ALLOW_LIVE") != "1":
            raise GuardError(f"{serial} is the live BlueStacks instance; refused")
        self.serial = serial
        self._size = None
        self.used_batch_ids: set[str] = set()
        self.input_backend = os.environ.get("COC_ANDROID_INPUT", "scrcpy")  # or "adb"
        self._scrcpy = None
        self._freeze_size = False
        # Optional video stream (scrcpy_stream.py). Off unless attach_stream()
        # is called by a long-lived owner such as farming_cutoff.py --stream.
        self.stream = None
        self.stream_fallbacks: list[str] = []
        # One controller per device: exclusive lock held for this object's life.
        import fcntl
        lock_path = f"/tmp/coc_android_{serial.replace(':', '_')}.lock"
        self._lock = open(lock_path, "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GuardError(f"another controller holds {serial} ({lock_path})")

    # -- low level -------------------------------------------------------
    def adb(self, *args: str, binary: bool = False, timeout: float = 15) -> bytes | str:
        out = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True, timeout=timeout)
        if out.returncode != 0:
            err = out.stderr.decode(errors="replace").strip().splitlines()
            raise RuntimeError(f"adb {' '.join(args)[:80]} failed: {err[0] if err else out.returncode}")
        return out.stdout if binary else out.stdout.decode(errors="replace")

    def shell(self, cmd: str, timeout: float = 15) -> str:
        return self.adb("shell", cmd, timeout=timeout)

    # -- info --------------------------------------------------------------
    def rotation(self) -> int:
        m = re.search(r"mCurrentOrientation=(\d)", self.shell("dumpsys display | grep -m1 mCurrentOrientation"))
        return int(m.group(1)) if m else 0

    def size(self) -> tuple[int, int]:
        """Current screen size as the agent sees it (rotation applied)."""
        if self.stream is not None:
            # The live encoder header already reports oriented display bounds.
            # Avoid wm/dumpsys binder queries, which also hang on BlueStacks.
            # A changed header/rotation ends ScrcpyStream; never reuse dimensions
            # after its server exits or its decoder reports an error.
            if not self.stream.alive():
                raise GuardError("Cannot validate input bounds: video stream is not alive")
            dimensions = self.stream.size
            if (not dimensions or len(dimensions) != 2 or any(
                    not isinstance(v, int) or isinstance(v, bool) or not 0 < v <= 65535
                    for v in dimensions)):
                raise GuardError("Video stream has no valid display dimensions")
            current = tuple(dimensions)
            if self._size is not None and current != self._size:
                raise GuardError("Video display dimensions changed; fresh controller required")
            self._size = current
            return current
        m = re.findall(r"(\d+)x(\d+)", self.shell("wm size"))
        w, h = map(int, m[-1])  # override size wins if present
        if self.rotation() in (1, 3):
            w, h = h, w
        self._size = (w, h)
        return self._size

    def info(self) -> dict:
        return {
            "serial": self.serial,
            "model": self.shell("getprop ro.product.model").strip(),
            "sdk": self.shell("getprop ro.build.version.sdk").strip(),
            "size": self.size(),
            "input": self.input_backend,
        }

    # -- observe -----------------------------------------------------------
    def attach_stream(self, max_fps: int = 15) -> dict:
        """Serve observe() from a scrcpy video stream in this process.

        Only worth it for a long-lived process: startup is ~1.8 s on
        BlueStacks. On any stream error observe() stops the stream and falls
        back to screencap for the rest of the process (recorded in receipts).
        """
        from scrcpy_stream import ScrcpyStream
        self.stream = ScrcpyStream(self.serial, max_fps=max_fps).start()
        return {"stream": True, "size": list(self.stream.size), "maxFps": max_fps}

    def _drop_stream(self, reason: str) -> None:
        self.stream_fallbacks.append(reason)
        try:
            self.stream.stop()
        finally:
            self.stream = None

    view_jpeg = False  # also write a small JPEG next to each saved frame (agent viewing)

    def observe(self, path: str) -> dict:
        obs = self._observe(path)
        if self.view_jpeg and not os.path.basename(path).startswith("watch-live"):
            # The agent views this copy: ~10x smaller than the PNG, so its
            # conversation context grows far slower. The PNG stays the record.
            try:
                from PIL import Image
                view = os.path.splitext(path)[0] + ".view.jpg"
                with Image.open(path) as frame:
                    frame.convert("RGB").save(view, quality=75)
                obs["viewPath"] = view
            except Exception as error:  # never let the viewing copy block play
                obs["viewError"] = str(error)
        return obs

    def _observe(self, path: str) -> dict:
        if self.stream is not None:
            # A static screen sends no frames, so freshness can only be proven
            # while frames are flowing; otherwise (or on timeout) use screencap.
            try:
                # A still screen sends no frames: wait_static proves "no change"
                # from stream silence instead of screencap (which hung for 15 s
                # on BlueStacks and halted the watcher, raid 571).
                obs = self.stream.observe(path, static=not self.stream.flowing())
                if tuple(obs["size"]) != (self._size or self.size()):
                    raise RuntimeError(f"stream size {obs['size']} != screen {list(self._size)}")
                return obs
            except TimeoutError as error:  # no frame captured after the request: keep stream
                obs = self._screencap(path)
                obs["streamSkipped"] = str(error)
                return obs
            except Exception as error:  # fall back to screencap, never to a stale frame
                self._drop_stream(f"{type(error).__name__}: {error}")
                obs = self._screencap(path)
                obs["streamFallback"] = self.stream_fallbacks[-1]
                return obs
        return self._screencap(path)

    def _screencap(self, path: str) -> dict:
        # Raw RGBA is ~3x faster than `screencap -p` on BlueStacks (median
        # 0.18 s vs 0.57 s, live 2026-11-03); the PNG is encoded locally.
        t0 = time.time()
        raw = self.adb("exec-out", "screencap", binary=True)
        t1 = time.time()
        w, h = int.from_bytes(raw[0:4], "little"), int.from_bytes(raw[4:8], "little")
        hdr = len(raw) - w * h * 4
        if w and h and hdr in (12, 16):
            import cv2
            import numpy as np
            img = np.frombuffer(raw, np.uint8, offset=hdr).reshape(h, w, 4)
            if not cv2.imwrite(path, cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)):
                raise RuntimeError(f"could not write {path}")
        else:  # unknown raw layout: fall back to device-side PNG
            png = self.adb("exec-out", "screencap", "-p", binary=True)
            t1 = time.time()
            if not png.startswith(b"\x89PNG"):
                raise RuntimeError("screencap returned non-PNG data")
            with open(path, "wb") as f:
                f.write(png)
            w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
        return {
            "frameId": uuid.uuid4().hex[:12],
            # the device grabs the frame when screencap starts; transfer comes after
            "capturedAtMs": int(t0 * 1000),
            "captureMs": round((t1 - t0) * 1000),
            "size": [w, h],
            "path": path,
        }

    # -- input -------------------------------------------------------------
    def _check_point(self, x: int, y: int) -> None:
        # Within a batch the size is frozen (one query); otherwise re-read.
        w, h = self._size if self._freeze_size and self._size else self.size()
        if not (0 <= x < w and 0 <= y < h):
            raise GuardError(f"point {(x, y)} outside screen {w}x{h}")

    def _ctl(self):
        """scrcpy control channel (no root, multi-touch). Started lazily."""
        if self.input_backend != "scrcpy":
            return None
        if self._scrcpy is None:
            from scrcpy_control import ScrcpyControl
            self._scrcpy = ScrcpyControl(self.serial)
            self._scrcpy.start()
        return self._scrcpy

    def close(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream = None
        if self._scrcpy:
            self._scrcpy.stop()
            self._scrcpy = None
        if self._lock:
            self._lock.close()  # releases flock
            self._lock = None

    def tap(self, x: int, y: int) -> None:
        self._check_point(x, y)
        ctl = self._ctl()
        if ctl:
            ctl.tap(int(x), int(y), *self._size)
        else:
            self.shell(f"input tap {int(x)} {int(y)}")

    def swipe(self, x1, y1, x2, y2, ms: int = 300) -> None:
        self._check_point(x1, y1)
        self._check_point(x2, y2)
        ctl = self._ctl()
        if ctl:
            ctl.swipe(int(x1), int(y1), int(x2), int(y2), *self._size, ms=ms)
        else:
            self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")

    def back(self) -> None:
        """Android Back key: closes CoC panels/popups without tapping inside them.
        Live-tested 2026-11-03 on the Battle hub (closed it, no button pressed)."""
        self.shell("input keyevent 4")

    def pinch(self, direction: str = "out", ms: int = 400) -> None:
        """Two-finger horizontal pinch at screen centre. 'out' = zoom out."""
        ctl = self._ctl()
        if not ctl:
            raise RuntimeError("pinch needs COC_ANDROID_INPUT=scrcpy")
        w, h = self.size()
        far, near = int(min(w, h) * 0.35), int(min(w, h) * 0.08)
        start, end = (far, near) if direction == "out" else (near, far)
        ctl.pinch(w // 2, h // 2, start, end, w, h, ms=ms)

    # -- batch (mirrors native_farming_batch limits) -------------------------
    def run_batch(self, batch: dict, observe_path: str) -> dict:
        bid = batch.get("id")
        if not bid or bid in self.used_batch_ids:
            raise GuardError(f"batch id missing or already used: {bid}")
        actions = batch.get("actions", [])
        if len(actions) > MAX_BATCH_INPUTS:
            raise GuardError(f"{len(actions)} inputs > {MAX_BATCH_INPUTS}")
        for a in actions:
            if a.get("kind") == "spawn" and not any(
                s.get("point") == a["point"] and s.get("evidence")
                for s in batch.get("checkpoint", {}).get("legalSpawns", [])
            ):
                raise GuardError(f"spawn {a['label']} lacks legalSpawns evidence")
        cur = self.size()
        frame_size = batch.get("checkpoint", {}).get("size")
        if frame_size is not None and tuple(frame_size) != cur:
            raise GuardError(f"checkpoint frame size {frame_size} != screen {list(cur)} (stale or rotating)")
        self._freeze_size = True
        try:
            for a in actions:  # validate every point before issuing any input
                self._check_point(*a["point"])
        except GuardError:
            self._freeze_size = False
            raise
        self.used_batch_ids.add(bid)
        try:
            t0 = time.time()
            issued = []
            stopped = None
            for index, a in enumerate(actions):
                if time.time() - t0 > MAX_BATCH_SECONDS:
                    stopped = "time_cap"
                    break
                ts = time.time()
                self.tap(*a["point"])
                issued.append({"label": a["label"], "issuedAtMs": int(ts * 1000),
                               "ms": round((time.time() - ts) * 1000)})
                # Let CoC register a selection before the following map tap.
                # Consecutive UP/DOWN events with no release interval sometimes
                # left the previous unit selected in the supervised live trial.
                if index + 1 < len(actions):
                    time.sleep(.2 if a.get("kind") == "select" else .06)
        finally:
            self._freeze_size = False
        input_ms = round((time.time() - t0) * 1000)
        time.sleep(batch.get("settleSeconds", SETTLE_SECONDS))
        obs = self.observe(observe_path)
        return {"batchId": bid, "issued": issued, "planned": len(actions),
                "stopped": stopped, "inputMs": input_ms, "elapsedMs": round((time.time() - t0) * 1000),
                "observation": obs, "accepted": None}  # accept only after visual verify


def main(argv: list[str]) -> int:
    dev = Device()
    cmd, *rest = argv or ["info"]
    if cmd == "info":
        res = dev.info()
    elif cmd == "observe":
        res = dev.observe(rest[0])
    elif cmd == "tap":
        dev.tap(int(rest[0]), int(rest[1])); res = {"ok": True}
    elif cmd == "swipe":
        dev.swipe(*map(int, rest[:5])); res = {"ok": True}
    elif cmd == "back":
        dev.back(); res = {"ok": True}
    elif cmd == "pinch":
        dev.pinch(rest[0] if rest else "out"); res = {"ok": True}
    elif cmd == "batch":
        with open(rest[0]) as f:
            res = dev.run_batch(json.load(f), rest[1])
    else:
        raise SystemExit(f"unknown command {cmd}")
    dev.close()
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
