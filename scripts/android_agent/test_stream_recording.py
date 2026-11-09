"""Offline decoding checks for real H.264 recording packets; no ADB/device."""
import fractions
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrcpy_stream import Recorder, ScrcpyStream, av


def encoded_packets():
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height = 96, 64
    codec.pix_fmt = "yuv420p"
    codec.time_base = fractions.Fraction(1, 15)
    codec.framerate = fractions.Fraction(15)
    codec.options = {"preset": "ultrafast", "tune": "zerolatency",
                     "x264-params": "keyint=2:min-keyint=2:scenecut=0:repeat-headers=1"}
    packets = []
    for i in range(6):
        frame = av.VideoFrame(96, 64, "yuv420p")
        frame.pts = i
        for j, plane in enumerate(frame.planes):
            plane.update(bytes([30 + i * 20 if j == 0 else 128]) * plane.buffer_size)
        packets.extend(codec.encode(frame))
    packets.extend(codec.encode(None))
    return packets


def annexb_units(data):
    import re
    starts = list(re.finditer(b"\x00\x00\x00?\x01", data))
    return [data[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(data)]
            for i, m in enumerate(starts)]


class MemorySocket:
    def __init__(self, data):
        self.data = data

    def recv(self, n):
        result, self.data = self.data[:n], self.data[n:]
        return result


class StreamRecordingTests(unittest.TestCase):
    def test_recording_reuses_actual_parameters_at_later_keyframe(self):
        packets = encoded_packets()
        config = b"".join(b"\x00\x00\x00\x01" + n for n in annexb_units(bytes(packets[0]))
                          if n[0] & 31 in (7, 8))
        self.assertTrue(config)
        stream = ScrcpyStream("offline-test")
        stream.size = (96, 64)
        stream._offsets.clear()
        wire = struct.pack(">QI", 1 << 62, len(config)) + config
        for i, packet in enumerate(packets):
            # Android sends configuration separately once; later IDRs omit it.
            payload = b"".join(b"\x00\x00\x00\x01" + n for n in annexb_units(bytes(packet))
                               if n[0] & 31 not in (7, 8))
            head = i * 66667 | ((1 << 61) if packet.is_keyframe else 0)
            wire += struct.pack(">QI", head, len(payload)) + payload
        stream._sock = MemorySocket(wire)
        stream._run()
        self.assertEqual(stream.frames_decoded, 6)
        self.assertEqual(len(stream._gop), 2)
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "later-gop.mkv")
            stream.start_recording(path)
            info = stream.stop_recording()
            self.assertEqual(info["frames"], 2)
            with av.open(path) as recorded:
                frames = list(recorded.decode(video=0))
            self.assertEqual(len(frames), 2)
            # Re-muxing must retain exact decoded pixels, not merely yield a file.
            self.assertEqual(frames[-1].width, 96)
            expected = stream._latest.image  # the finite fake socket has reached EOF
            self.assertTrue((frames[-1].to_ndarray(format="bgr24") == expected).all())

    def test_recorder_skips_nonkey_and_preserves_microsecond_timing(self):
        packets = encoded_packets()
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "timing.mkv")
            rec = Recorder(path, (96, 64), 15)
            rec.write(10, bytes(packets[1]), False, 1)
            for i, packet in enumerate(packets):
                rec.write(1000000 + i * 66667, bytes(packet), packet.is_keyframe, 2 + i / 15)
            info = rec.close()
            self.assertEqual((info["frames"], info["videoStartPtsUs"]), (6, 1000000))
            with av.open(path) as recorded:
                frames = list(recorded.decode(video=0))
            self.assertEqual(len(frames), 6)
            self.assertAlmostEqual(float(frames[-1].pts * frames[-1].time_base), 1 / 3, places=2)


if __name__ == "__main__":
    unittest.main()
