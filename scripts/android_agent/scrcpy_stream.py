"""scrcpy-server video stream reader: fresh frames without screencap.

Opt-in only: coc_android.Device.attach_stream() (used by farming_cutoff.py
--stream). Refuses the live BlueStacks serials unless COC_ANDROID_ALLOW_LIVE=1.

A video-only scrcpy-server (control=false) sends H.264 over an adb forward
tunnel. PyAV (vendored in ./_vendor, `pip install --target _vendor av`)
decodes each packet with its device PTS, so every frame keeps the time the
device captured it.

Wire format (scrcpy v5.0.1 doc/develop.md, same jar as scrcpy_control.py):
the first tunnel socket gets one 0x00 dummy byte; then u32 codec id; then a
12-byte session packet (MSB of byte 0 set, u32 width, u32 height at bytes
4-11) per capture session; then media packets with a 12-byte header (u64
flags|PTS: bit63=0 media, bit62 config, bit61 key frame, low 61 bits PTS in
us; u32 size) + payload. A new session (rotation/resize) mid-stream is an
error: callers restart, mirroring the controller's stale-size refusal.

Freshness (measured 2026-11-03 on the emulator: the stream arrived up to
~1 s after screencap already showed a change, so "newest decoded frame" is
NOT the current screen). A frame's host capture time is estimated as
PTS + min(arrival - PTS) over recent packets; the minimum is the fastest
transport seen, so the estimate is late by at most that minimum, and
`bias` (default 0.05 s) is added on top. wait_fresh(after) returns only a
frame captured >= after + bias. Android sends nothing while the screen is
static. wait_static() proves that no packets arrived for its silence window
and returns the newest frame with staticScreen evidence. Device.observe uses
that mode when idle; a flowing stream must still pass wait_fresh(), otherwise
the receipt identifies the screencap fallback.

Usage:
  COC_ANDROID_SERIAL=emulator-5560 python3 scrcpy_stream.py OUT.png [seconds]
"""
from __future__ import annotations

import collections
import os
import random
import socket
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "_vendor"))
import av  # noqa: E402  (vendored PyAV)
from scrcpy_control import ADB, SERVER_LOCAL, server_version  # noqa: E402

LIVE_SERIALS = {"emulator-5554", "127.0.0.1:5555", "localhost:5555"}
SERVER_REMOTE = "/data/local/tmp/coc-scrcpy-stream.jar"
CODEC_H264 = 0x68323634  # "h264"
PTS_MASK = (1 << 61) - 1


class Recorder:
    """Remux received H.264 packets into a Matroska file (no re-encode).

    PTS is the device capture time relative to the first written packet;
    `start_pts_us` (device clock) and the host time of that packet are kept
    so events in host ms can be aligned with video time.
    """

    def __init__(self, path: str, size: tuple[int, int], fps: int):
        import fractions
        self.path = path
        self.out = av.open(path, "w", format="matroska")
        # These packets were encoded by Android. add_stream() opens a new
        # encoder and can invent SPS/PPS for a different encoder configuration.
        self.st = self.out.add_mux_stream("h264", rate=fps, width=size[0], height=size[1])
        self.US = fractions.Fraction(1, 1_000_000)
        self.st.time_base = self.US
        self.start_pts_us: int | None = None
        self.start_host_ms: int | None = None
        self.frames = 0
        self.bytes = 0
        self.last_pts_us: int | None = None

    def write(self, pts_us: int, data: bytes, key: bool, host_s: float) -> None:
        if self.start_pts_us is None:
            if not key:
                return  # a decodable file must begin at a key frame
            self.start_pts_us = pts_us
            self.start_host_ms = int(host_s * 1000)
        rel = pts_us - self.start_pts_us
        if self.last_pts_us is not None and rel <= self.last_pts_us:
            rel = self.last_pts_us + 1  # muxer needs strictly increasing timestamps
        packet = av.Packet(data)
        packet.pts = packet.dts = rel
        # Always microseconds: the muxer rescales to the stream time base,
        # which Matroska changes to 1/1000 once the header is written.
        packet.time_base = self.US
        packet.stream = self.st
        packet.is_keyframe = key
        self.out.mux(packet)
        self.last_pts_us = rel
        self.frames += 1
        self.bytes += len(data)

    def close(self) -> dict:
        self.out.close()
        return {"path": self.path, "frames": self.frames, "bytes": self.bytes,
                "videoStartPtsUs": self.start_pts_us, "videoStartHostMs": self.start_host_ms,
                "durationMs": round((self.last_pts_us or 0) / 1000)}


class Frame:
    __slots__ = ("seq", "pts_us", "captured_at", "arrived_at", "image")

    def __init__(self, seq, pts_us, captured_at, arrived_at, image):
        self.seq, self.pts_us, self.captured_at = seq, pts_us, captured_at
        self.arrived_at, self.image = arrived_at, image


class ScrcpyStream:
    def __init__(self, serial: str | None = None, max_fps: int = 15,
                 bit_rate: int = 8_000_000, port: int | None = None):
        serial = serial or os.environ.get("COC_ANDROID_SERIAL")
        if not serial:
            raise RuntimeError("COC_ANDROID_SERIAL required; no default device")
        if serial in LIVE_SERIALS and os.environ.get("COC_ANDROID_ALLOW_LIVE") != "1":
            raise RuntimeError(f"{serial} is the live BlueStacks instance; refused")
        self.serial = serial
        # Low fps keeps decode cost (battery) down; 15 fps is plenty for HUD polling.
        self.max_fps, self.bit_rate = max_fps, bit_rate
        self.scid = random.randint(1, 0x7FFFFFFF)
        self.port = port or random.randint(27900, 28600)
        self.size: tuple[int, int] | None = None
        self._server = self._sock = None
        self._thread: threading.Thread | None = None
        self._cond = threading.Condition()
        self._latest: Frame | None = None
        self._error: str | None = None
        self._stop = threading.Event()
        self._offsets: collections.deque = collections.deque(maxlen=300)  # arrival - pts, seconds
        self.observations = 0
        self.frames_decoded = 0
        self.packets = 0
        self.bytes_received = 0
        self.last_packet_at: float | None = None
        # Packets since the last key frame (config prepended), so a recording
        # can start immediately with a decodable key frame.
        self._gop: list[tuple[int, bytes, bool, float]] = []
        self._rec: Recorder | None = None

    # -- lifecycle -------------------------------------------------------------
    def _adb(self, *args: str) -> str:
        r = subprocess.run([ADB, "-s", self.serial, *args], capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {r.stderr.strip()[:200]}")
        return r.stdout

    def start(self, timeout: float = 10) -> "ScrcpyStream":
        self._adb("push", SERVER_LOCAL, SERVER_REMOTE)
        self._adb("forward", f"tcp:{self.port}", f"localabstract:scrcpy_{self.scid:08x}")
        cmd = (f"CLASSPATH={SERVER_REMOTE} app_process / com.genymobile.scrcpy.Server "
               f"{server_version()} scid={self.scid:08x} log_level=warn tunnel_forward=true "
               f"video=true audio=false control=false video_codec=h264 "
               f"video_bit_rate={self.bit_rate} max_fps={self.max_fps} "
               f"send_device_meta=false send_frame_meta=true send_codec_meta=true "
               f"send_dummy_byte=true cleanup=true")
        # stdin=DEVNULL: an inherited stdin let the scrcpy adb child steal
        # controller commands before (android_farming_batch.md).
        self._server = subprocess.Popen([ADB, "-s", self.serial, "shell", cmd], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + timeout
        while time.time() < deadline and self._sock is None:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=2)
            try:
                if s.recv(1) == b"\x00":  # only the server's dummy byte proves the tunnel
                    self._sock = s
                    break
            except (socket.timeout, ConnectionResetError):
                pass
            s.close()
            time.sleep(0.2)
        if self._sock is None:
            self.stop()
            raise RuntimeError("scrcpy video server did not become ready")
        self._sock.settimeout(timeout)
        (codec,) = struct.unpack(">I", self._recv_exact(4))
        flags, w, h = struct.unpack(">III", self._recv_exact(12))
        if codec != CODEC_H264 or not flags & 0x80000000:
            self.stop()
            raise RuntimeError(f"unexpected stream start codec=0x{codec:08x} flags=0x{flags:08x}")
        self._sock.settimeout(None)
        self.size = (w, h)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._rec is not None:
            try:
                self.stop_recording()
            except Exception:  # noqa: BLE001
                pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._server:
            self._server.terminate()
        if self._thread:
            self._thread.join(timeout=2)
        subprocess.run([ADB, "-s", self.serial, "forward", "--remove", f"tcp:{self.port}"],
                       capture_output=True)
        self._sock = self._server = self._thread = None
        with self._cond:
            self._cond.notify_all()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # -- reader/decoder thread -------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("video socket closed")
            buf += chunk
        return bytes(buf)

    def _run(self) -> None:
        codec = av.CodecContext.create("h264", "r")
        codec.thread_count = 1  # frame threading would hold frames back
        config = b""
        codec_config = b""
        try:
            while not self._stop.is_set():
                hdr = self._recv_exact(12)
                if hdr[0] & 0x80:  # session packet: capture size changed (rotation)
                    w, h = struct.unpack(">II", hdr[4:12])
                    if (w, h) != self.size:
                        raise ConnectionError(f"screen size changed {list(self.size)} -> {[w, h]}; restart stream")
                    continue
                head, size = struct.unpack(">QI", hdr)
                data = self._recv_exact(size)
                arrived = time.time()
                if head & (1 << 62):  # config (SPS/PPS): prepend to the next frame, as scrcpy does
                    config += data
                    continue
                pts = head & PTS_MASK
                key = bool(head & (1 << 61))
                if config:
                    codec_config = config
                elif key:
                    # scrcpy may send SPS/PPS only at stream startup. A later
                    # recording starts at a buffered IDR, so keep the real
                    # configuration with every GOP instead of losing it.
                    config = codec_config
                payload = config + data
                packet = av.Packet(payload)
                config = b""
                packet.pts = pts
                with self._cond:
                    if key:
                        self._gop = []
                    if len(self._gop) < 3000:
                        self._gop.append((pts, payload, key, arrived))
                    if self._rec is not None:
                        try:
                            self._rec.write(pts, payload, key, arrived)
                        except Exception as e:  # noqa: BLE001 - recording must never stop the stream
                            self.record_error = f"{type(e).__name__}: {e}"
                            self._rec = None
                    self.packets += 1
                    self.bytes_received += 12 + size
                    self.last_packet_at = arrived
                    self._offsets.append(arrived - pts / 1e6)
                for frame in codec.decode(packet):
                    img = frame.to_ndarray(format="bgr24")
                    now = time.time()
                    with self._cond:
                        self.frames_decoded += 1
                        offset = min(self._offsets)
                        fpts = frame.pts if frame.pts is not None else pts
                        self._latest = Frame(self.frames_decoded, fpts, fpts / 1e6 + offset, now, img)
                        self._cond.notify_all()
        except Exception as e:  # noqa: BLE001 - any failure ends the stream
            with self._cond:
                if not self._stop.is_set() and self._error is None:
                    self._error = f"stream ended: {type(e).__name__}: {e}"
                self._cond.notify_all()

    # -- recording ---------------------------------------------------------------
    record_error: str | None = None

    def start_recording(self, path: str) -> dict:
        """Start writing the stream to `path` (.mkv), beginning with the
        buffered packets since the last key frame (at most one key-frame
        interval, ~10 s, of lead-in)."""
        with self._cond:
            if self._rec is not None:
                raise RuntimeError("already recording")
            rec = Recorder(path, self.size, self.max_fps)
            for pts, payload, key, arrived in self._gop:
                rec.write(pts, payload, key, arrived)
            self._rec = rec
            self.record_error = None
            return {"path": path, "leadInPackets": len(self._gop)}

    def stop_recording(self) -> dict | None:
        with self._cond:
            rec, self._rec = self._rec, None
        if rec is None:
            return None
        info = rec.close()
        if self.record_error:
            info["error"] = self.record_error
        return info

    @property
    def recording(self) -> bool:
        return self._rec is not None

    # -- reading -----------------------------------------------------------------
    def alive(self) -> bool:
        return self._error is None and self._server is not None and self._server.poll() is None

    def flowing(self, within: float = 0.6) -> bool:
        """Packets arrived recently (screen is animating). False on a static screen.

        0.6 s, not 0.25 s: minimized BlueStacks leaves >0.25 s gaps between
        frames mid-battle (raid 566: 23 of 72 polls fell back to screencap).
        """
        return self.alive() and self.last_packet_at is not None and time.time() - self.last_packet_at < within

    def latest(self) -> Frame | None:
        with self._cond:
            if self._error:
                raise RuntimeError(self._error)
            return self._latest

    def wait_fresh(self, after: float | None = None, bias: float = 0.05, timeout: float = 1.2) -> Frame:
        """First frame captured on the device at or after `after` (default now).

        Raises TimeoutError if none arrives in `timeout` (static screen or a
        slow encoder); callers then use screencap.
        """
        need = (after if after is not None else time.time()) + bias
        deadline = time.time() + timeout
        with self._cond:
            while True:
                if self._error:
                    raise RuntimeError(self._error)
                if not self.alive():
                    raise RuntimeError("stream server exited")
                if self._latest and self._latest.captured_at >= need:
                    return self._latest
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"no frame captured after the request within {timeout}s")
                self._cond.wait(left)

    def wait_static(self, after: float, quiet: float = 1.5) -> Frame:
        """Prove the screen did not change since `after` without screencap.

        The stream lagged the screen by up to ~1.1 s (emulator worst case,
        2026-11-03). If no packet at all arrives for `quiet` seconds after the
        request and every received packet is decoded, nothing changed and the
        newest frame is the current screen. A fresh frame arriving in that
        window is returned as usual. If packets arrive but none is captured
        after the request, raises TimeoutError (caller uses screencap).
        """
        need = after + 0.05
        deadline = after + quiet
        with self._cond:
            while True:
                if self._error:
                    raise RuntimeError(self._error)
                if not self.alive():
                    raise RuntimeError("stream server exited")
                if self._latest and self._latest.captured_at >= need:
                    return self._latest
                now = time.time()
                if now >= deadline:
                    quiet_since = self.last_packet_at is None or self.last_packet_at < after
                    if quiet_since and self._latest is not None and self.frames_decoded >= self.packets:
                        return self._latest
                    raise TimeoutError("screen changed but no fresh frame yet")
                self._cond.wait(deadline - now)

    def observe(self, path: str, timeout: float = 1.2, static: bool = False) -> dict:
        """Same receipt shape as coc_android.Device.observe, from the stream.

        static=True: the screen looked still; use wait_static (no screencap)."""
        import cv2
        t0 = time.time()
        f = self.wait_static(t0) if static else self.wait_fresh(t0, timeout=timeout)
        self.observations += 1
        # PNG level 1: ~3x faster to write than the default level 3, still lossless.
        if not cv2.imwrite(path, f.image, [cv2.IMWRITE_PNG_COMPRESSION, 1]):
            raise RuntimeError(f"could not write {path}")
        # frameId stays unique per observation (batch ids are built from it).
        return {"frameId": f"s{self.scid:08x}-{f.seq}-{self.observations}",
                "capturedAtMs": int(f.captured_at * 1000), "requestedAtMs": int(t0 * 1000),
                "frameArrivedAtMs": int(f.arrived_at * 1000),
                "captureMs": round((time.time() - t0) * 1000), "size": list(self.size),
                "path": path, "source": "scrcpy-stream",
                **({"staticScreen": True} if f.captured_at < t0 else {})}


def main(argv: list[str]) -> int:
    import json
    out = argv[0] if argv else "stream.png"
    secs = float(argv[1]) if len(argv) > 1 else 2.0
    with ScrcpyStream() as s:
        time.sleep(secs)
        try:
            res = s.observe(out)
        except TimeoutError as e:
            res = {"timeout": str(e), "flowing": s.flowing()}
        res.update(framesDecoded=s.frames_decoded, packets=s.packets)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
