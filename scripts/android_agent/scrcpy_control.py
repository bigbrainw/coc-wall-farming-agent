"""Minimal scrcpy-server control client (touch injection only, no video).

Wire format verified against scrcpy v5.0.1 server source
(ControlMessageReader.parseInjectTouchEvent): 32 bytes, big-endian:
  u8 type=2, u8 action, i64 pointerId, i32 x, i32 y, u16 screenW, u16 screenH,
  u16 pressure (fixed point, 0xffff = 1.0), i32 actionButton, i32 buttons.
With video disabled the server injects raw x/y on display 0.
"""
from __future__ import annotations

import os
import random
import re
import shutil
import socket
import struct
import subprocess
import time

ADB = shutil.which("adb") or "/opt/homebrew/bin/adb"
SERVER_LOCAL = os.environ.get("SCRCPY_SERVER_PATH", "/opt/homebrew/share/scrcpy/scrcpy-server")
SERVER_REMOTE = "/data/local/tmp/coc-scrcpy-server.jar"

ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
TYPE_INJECT_TOUCH_EVENT = 2


def server_version() -> str:
    out = subprocess.run(["scrcpy", "--version"], capture_output=True, text=True).stdout
    return re.search(r"scrcpy (\S+)", out).group(1)


class ScrcpyControl:
    def __init__(self, serial: str, port: int | None = None):
        self.serial = serial
        self.scid = random.randint(1, 0x7FFFFFFF)
        self.port = port or random.randint(27200, 27900)
        self.proc: subprocess.Popen | None = None
        self.sock: socket.socket | None = None

    def _adb(self, *args: str) -> str:
        r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.strip()[:200]}")
        return r.stdout

    def start(self, timeout: float = 10) -> None:
        self._adb("push", SERVER_LOCAL, SERVER_REMOTE)
        name = f"scrcpy_{self.scid:08x}"
        self._adb("forward", f"tcp:{self.port}", f"localabstract:{name}")
        cmd = (f"CLASSPATH={SERVER_REMOTE} app_process / com.genymobile.scrcpy.Server "
               f"{server_version()} scid={self.scid:08x} log_level=warn tunnel_forward=true "
               f"video=false audio=false control=true send_device_meta=false "
               f"send_dummy_byte=true cleanup=true")
        self.proc = subprocess.Popen([ADB, "-s", self.serial, "shell", cmd],
                                     stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=2)
            try:
                # adb accepts forward connections before the server listens;
                # only the server's dummy byte proves the tunnel is live.
                if s.recv(1) == b"\x00":
                    s.settimeout(None)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self.sock = s
                    return
            except (socket.timeout, ConnectionResetError):
                pass
            s.close()
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("scrcpy server did not become ready")

    def stop(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None
        if self.proc:
            self.proc.terminate()
            self.proc = None
        subprocess.run([ADB, "-s", self.serial, "forward", "--remove", f"tcp:{self.port}"],
                       capture_output=True)

    def touch(self, action: int, pointer_id: int, x: int, y: int, w: int, h: int,
              pressure: float = 1.0) -> None:
        if self.sock is None:
            raise RuntimeError("scrcpy control not started")
        p = max(0, min(0xFFFF, int(pressure * 0xFFFF)))
        msg = struct.pack(">BBqiiHHHii", TYPE_INJECT_TOUCH_EVENT, action, pointer_id,
                          int(x), int(y), w, h, p, 0, 0)
        assert len(msg) == 32
        self.sock.sendall(msg)

    # -- gestures ------------------------------------------------------------
    def tap(self, x, y, w, h, hold_ms: int = 40) -> None:
        self.touch(ACTION_DOWN, 0, x, y, w, h, 1.0)
        time.sleep(hold_ms / 1000)
        self.touch(ACTION_UP, 0, x, y, w, h, 0.0)

    def swipe(self, x1, y1, x2, y2, w, h, ms: int = 300, steps: int = 15) -> None:
        self.touch(ACTION_DOWN, 0, x1, y1, w, h)
        for i in range(1, steps + 1):
            time.sleep(ms / 1000 / steps)
            self.touch(ACTION_MOVE, 0, x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps, w, h)
        self.touch(ACTION_UP, 0, x2, y2, w, h, 0.0)

    def pinch(self, cx, cy, start_r, end_r, w, h, ms: int = 400, steps: int = 12) -> None:
        """Horizontal two-finger pinch. end_r < start_r = fingers close = zoom out."""
        self.touch(ACTION_DOWN, 0, cx - start_r, cy, w, h)
        self.touch(ACTION_DOWN, 1, cx + start_r, cy, w, h)
        for i in range(1, steps + 1):
            time.sleep(ms / 1000 / steps)
            r = start_r + (end_r - start_r) * i // steps
            self.touch(ACTION_MOVE, 0, cx - r, cy, w, h)
            self.touch(ACTION_MOVE, 1, cx + r, cy, w, h)
        self.touch(ACTION_UP, 1, cx + end_r, cy, w, h, 0.0)
        self.touch(ACTION_UP, 0, cx - end_r, cy, w, h, 0.0)
