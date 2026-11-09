"""Offline tests: Device.observe with an attached stream and its screencap fallback.

No device needed: Device.__init__ is bypassed and the stream/screencap are fakes.
  python3 test_device_stream.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coc_android import Device, GuardError  # noqa: E402


class FakeStream:
    def __init__(self, size=(1280, 960), fail=None, flowing=True):
        self.size, self.fail, self.stopped, self.calls = size, fail, False, 0
        self._flowing = flowing

    def flowing(self):
        return self._flowing

    def alive(self):
        return not self.stopped

    def observe(self, path, static=False):
        self.calls += 1
        self.last_static = static
        if self.fail:
            raise self.fail
        return {"frameId": f"s1-{self.calls}", "capturedAtMs": 1, "size": list(self.size),
                "path": path, "source": "scrcpy-stream"}

    def stop(self):
        self.stopped = True


def device(stream):
    d = Device.__new__(Device)  # no adb, no lock
    d.serial, d._size, d.stream, d.stream_fallbacks = "test", (1280, 960), stream, []
    d._scrcpy, d._lock = None, None
    d.screencaps = 0

    def screencap(path):
        d.screencaps += 1
        return {"frameId": "cap", "capturedAtMs": 2, "size": [1280, 960], "path": path}
    d._screencap = screencap
    return d


class DeviceStreamTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "f.png")

    def test_stream_serves_observe(self):
        d = device(FakeStream())
        obs = d.observe(self.path)
        self.assertEqual(obs["source"], "scrcpy-stream")
        self.assertEqual(d.screencaps, 0)

    def test_live_stream_validates_bounds_without_hanging_binder_query(self):
        d = device(FakeStream())
        d._size = None
        def forbidden_query(*args, **kwargs):
            raise AssertionError("stream bounds must not issue wm/dumpsys")
        d.shell = forbidden_query
        self.assertEqual(d.size(), (1280, 960))
        self.assertEqual(d.size(), (1280, 960))

    def test_dead_or_changed_stream_cannot_reuse_cached_input_bounds(self):
        for stream in [FakeStream(size=(960, 1280)), FakeStream(size=None),
                       FakeStream(size=(0, 960))]:
            with self.assertRaises(GuardError):
                device(stream).size()
        stream = FakeStream()
        stream.stop()
        with self.assertRaises(GuardError):
            device(stream).size()

    def test_without_stream_size_still_reads_actual_rotation(self):
        d = device(None)
        d.shell = lambda command: ("Physical size: 960x1280" if command == "wm size"
                                   else "mCurrentOrientation=1")
        self.assertEqual(d.size(), (1280, 960))

    def test_static_screen_uses_stream_static_mode_not_screencap(self):
        s = FakeStream(flowing=False)
        d = device(s)
        obs = d.observe(self.path)
        self.assertEqual((obs["source"], s.last_static, d.screencaps), ("scrcpy-stream", True, 0))
        self.assertIs(d.stream, s)

    def test_timeout_uses_screencap_and_keeps_stream(self):
        s = FakeStream(fail=TimeoutError("no frame"))
        d = device(s)
        obs = d.observe(self.path)
        self.assertEqual(obs["frameId"], "cap")
        self.assertIn("no frame", obs["streamSkipped"])
        self.assertIs(d.stream, s)
        self.assertFalse(s.stopped)

    def test_stream_error_falls_back_and_stays_off(self):
        s = FakeStream(fail=RuntimeError("stream ended"))
        d = device(s)
        obs = d.observe(self.path)
        self.assertEqual(obs["frameId"], "cap")
        self.assertIn("RuntimeError", obs["streamFallback"])
        self.assertTrue(s.stopped)
        self.assertIsNone(d.stream)
        d.observe(self.path)  # later observes go straight to screencap
        self.assertEqual((s.calls, d.screencaps), (1, 2))

    def test_stream_size_mismatch_is_refused(self):
        d = device(FakeStream(size=(960, 1280)))
        obs = d.observe(self.path)
        self.assertEqual(obs["frameId"], "cap")
        self.assertIn("size", obs["streamFallback"])

    def test_no_stream_uses_screencap(self):
        d = device(None)
        self.assertEqual(d.observe(self.path)["frameId"], "cap")

    def test_view_jpeg_copy_is_written_except_for_hud_polls(self):
        from PIL import Image
        d = device(None)
        def screencap(path):
            Image.effect_noise((1280, 960), 40).convert("RGB").save(path)  # photo-like
            return {"frameId": "cap", "size": [1280, 960], "path": path}
        d._screencap = screencap
        d.view_jpeg = True
        obs = d.observe(self.path)
        self.assertTrue(os.path.exists(obs["viewPath"]))
        self.assertLess(os.path.getsize(obs["viewPath"]), os.path.getsize(self.path))
        poll = os.path.join(os.path.dirname(self.path), "watch-live.png")
        self.assertNotIn("viewPath", d.observe(poll))

    def test_close_stops_stream(self):
        s = FakeStream()
        d = device(s)
        d.close()
        self.assertTrue(s.stopped)
        self.assertIsNone(d.stream)


if __name__ == "__main__":
    unittest.main()
