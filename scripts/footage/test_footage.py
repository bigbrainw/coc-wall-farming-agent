#!/usr/bin/env python3
"""Offline tests for the footage uploader and dataset index.

A fake rclone (a small Python script written into the temp dir) stands in for
the real CLI, so these tests never touch the network or Google Drive.

Run:  python3 scripts/footage/test_footage.py
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import dataset_index  # noqa: E402
import upload_footage  # noqa: E402

FAKE_RCLONE = textwrap.dedent(
    r'''
    #!/usr/bin/env python3
    """Fake rclone. Remote 'name:path' maps to $FAKE_RCLONE_STATE/remote/name/path."""
    import filecmp, json, os, shutil, sys
    from pathlib import Path

    state = Path(os.environ["FAKE_RCLONE_STATE"])
    args = sys.argv[1:]

    def remote_dir(spec):
        name, _, path = spec.partition(":")
        return state / "remote" / name / path

    def record(entry):
        with open(state / "calls.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    cmd = args[0]
    skip_sidecars = "._*" in args

    def listing(folder):
        return sorted(p.name for p in folder.iterdir() if not (skip_sidecars and p.name.startswith("._")))
    if cmd == "listremotes":
        record({"cmd": cmd})
        for name in os.environ.get("FAKE_RCLONE_REMOTES", "coc-gdrive").split(","):
            if name:
                print(name + ":")
        sys.exit(0)
    if cmd == "about":
        record({"cmd": cmd})
        if os.environ.get("FAKE_RCLONE_ABOUT_FAIL"):
            print("Failed to about: couldn't fetch token", file=sys.stderr)
            sys.exit(1)
        print(json.dumps({"total": 15_000_000_000, "used": 15_000_000_000 - int(os.environ.get("FAKE_RCLONE_FREE", "10000000000")),
                          "free": int(os.environ.get("FAKE_RCLONE_FREE", "10000000000"))}))
        sys.exit(0)
    if cmd == "copy":
        src, dst = Path(args[1]), remote_dir(args[2])
        record({"cmd": cmd, "src": str(src), "dst": args[2], "srcExists": src.is_dir()})
        if os.environ.get("FAKE_RCLONE_COPY_FAIL"):
            sys.exit(5)
        dst.mkdir(parents=True, exist_ok=True)
        for name in listing(src):
            shutil.copy2(src / name, dst / name)
        sys.exit(0)
    if cmd == "check":
        src, dst = Path(args[1]), remote_dir(args[2])
        record({"cmd": cmd, "src": str(src), "dst": args[2], "srcExists": src.is_dir()})
        if os.environ.get("FAKE_RCLONE_CHECK_FAIL"):
            print("ERROR : video.mkv: hash differ", file=sys.stderr)
            sys.exit(1)
        names = listing(src)
        same = dst.is_dir() and names == listing(dst)
        same = same and all(filecmp.cmp(src / n, dst / n, shallow=False) for n in names)
        sys.exit(0 if same else 1)
    print("fake rclone: unsupported " + " ".join(args), file=sys.stderr)
    sys.exit(9)
    '''
).lstrip()

T0 = 1_793_000_000_000  # host ms, arbitrary


def make_recording(root: Path, recording_id: str, complete: bool = True, age_s: float = 0,
                   video_bytes: int = 4096, meta_extra: dict | None = None) -> Path:
    folder = root / "incoming" / recording_id
    folder.mkdir(parents=True)
    (folder / "video.mkv").write_bytes(os.urandom(video_bytes))
    events = [
        {"t": T0, "type": "note", "text": "recording started"},
        {"t": T0 + 1000, "type": "batch", "id": "b1", "actions": [
            {"kind": "select", "label": "valk", "point": [100, 900]},
            {"kind": "spawn", "label": "valk", "point": [210, 480], "issuedAtMs": T0 + 1100},
            {"kind": "spawn", "label": "valk", "point": [220, 470]},
        ]},
        {"t": T0 + 3000, "type": "batch", "id": "b2", "actions": [
            {"kind": "spell", "label": "eq", "point": [640, 400], "issuedAtMs": T0 + 3050},
            {"kind": "ability", "label": "king", "point": [300, 900], "issuedAtMs": T0 + 3100},
        ]},
        {"t": T0 + 5000, "type": "damage", "damage": 23},
        {"t": T0 + 9000, "type": "damage", "damage": 51},
        {"t": T0 + 9100, "type": "cutoff", "status": "ended", "damage": 51},
    ]
    with open(folder / "events.jsonl", "w") as stream:
        for event in events:
            stream.write(json.dumps(event) + "\n")
        if not complete:
            stream.write('{"t": 1, "type": "da')  # partial line from an unfinished write
    if complete:
        meta = {"recordingId": recording_id, "raid": recording_id.split("-", 1)[1],
                "startedAtMs": T0, "endedAtMs": T0 + 10_000, "videoStartPtsUs": 123_456_789,
                "videoStartHostMs": T0 + 200, "frames": 140, "bytes": video_bytes,
                "durationMs": 9_500, "size": [1280, 960], "controller": "test"}
        meta.update(meta_extra or {})
        (folder / "meta.json").write_text(json.dumps(meta))
    if age_s:
        old = time.time() - age_s
        for path in [folder, *folder.iterdir()]:
            os.utime(path, (old, old))
    return folder


class FootageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.root = base / "attack-footage"
        (self.root / "incoming").mkdir(parents=True)
        (self.root / "uploaded").mkdir()
        self.state = base / "fake-state"
        self.state.mkdir()
        self.rclone = base / "fake-rclone"
        self.rclone.write_text("#!" + sys.executable + "\n" + FAKE_RCLONE.split("\n", 1)[1])
        self.rclone.chmod(0o755)
        self.env_keys = []
        self.setenv("FAKE_RCLONE_STATE", str(self.state))

    def tearDown(self):
        for key in self.env_keys:
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def setenv(self, key, value):
        os.environ[key] = value
        self.env_keys.append(key)

    def run_uploader(self, *extra) -> int:
        return upload_footage.main(["--root", str(self.root), "--rclone", str(self.rclone),
                                    "--once", "--quiet", *extra])

    def calls(self) -> list[dict]:
        path = self.state / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def log(self) -> list[dict]:
        path = self.root / "upload-log.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


class UploaderTests(FootageTestCase):
    def test_only_complete_recordings_are_uploaded(self):
        make_recording(self.root, "20261103T224512Z-r566")
        make_recording(self.root, "20261103T230000Z-r567", complete=False)
        make_recording(self.root, "20261103T190000Z-r560", complete=False, age_s=3 * 3600)

        self.assertEqual(self.run_uploader(), 0)

        copied = [c["src"] for c in self.calls() if c["cmd"] == "copy"]
        self.assertEqual([Path(p).name for p in copied], ["20261103T224512Z-r566"])
        self.assertTrue((self.root / "uploaded/2026-11-03/20261103T224512Z-r566/video.mkv").is_file())
        self.assertTrue((self.root / "incoming/20261103T230000Z-r567").is_dir())
        self.assertTrue((self.root / "incoming/20261103T190000Z-r560").is_dir())
        remote = self.state / "remote/coc-gdrive/coc-attack-footage/2026-11-03/20261103T224512Z-r566"
        self.assertEqual(sorted(p.name for p in remote.iterdir()), ["events.jsonl", "meta.json", "video.mkv"])

        actions = [(r["action"], r.get("recordingId")) for r in self.log()]
        self.assertIn(("uploaded", "20261103T224512Z-r566"), actions)
        self.assertIn(("abandoned", "20261103T190000Z-r560"), actions)
        self.assertNotIn("20261103T230000Z-r567", [a[1] for a in actions])

        # Second pass: nothing new uploaded, abandoned folder not re-logged.
        self.assertEqual(self.run_uploader(), 0)
        self.assertEqual(len([c for c in self.calls() if c["cmd"] == "copy"]), 1)
        self.assertEqual(len([r for r in self.log() if r["action"] == "abandoned"]), 1)

    def test_move_happens_only_after_verified_check(self):
        make_recording(self.root, "20261103T224512Z-r566")
        self.assertEqual(self.run_uploader(), 0)
        sequence = [c for c in self.calls() if c["cmd"] in ("copy", "check")]
        self.assertEqual([c["cmd"] for c in sequence], ["copy", "check"])
        # The local folder was still in incoming/ while both copy and check ran.
        self.assertTrue(all(c["srcExists"] for c in sequence))
        self.assertTrue(all("/incoming/" in c["src"] for c in sequence))
        self.assertFalse((self.root / "incoming/20261103T224512Z-r566").exists())

    def test_macos_sidecars_are_not_uploaded(self):
        folder = make_recording(self.root, "20261103T224512Z-r566")
        (folder / "._video.mkv").write_bytes(b"appledouble")
        self.assertEqual(self.run_uploader(), 0)
        remote = self.state / "remote/coc-gdrive/coc-attack-footage/2026-11-03/20261103T224512Z-r566"
        self.assertEqual(sorted(p.name for p in remote.iterdir()), ["events.jsonl", "meta.json", "video.mkv"])

    def test_failed_check_leaves_folder_in_incoming(self):
        folder = make_recording(self.root, "20261103T224512Z-r566")
        self.setenv("FAKE_RCLONE_CHECK_FAIL", "1")
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_UPLOAD_FAILED)
        self.assertTrue((folder / "meta.json").is_file())
        self.assertFalse((self.root / "uploaded/2026-11-03").exists())
        self.assertEqual([r["action"] for r in self.log()], ["verify_failed"])

    def test_failed_copy_skips_check_and_move(self):
        folder = make_recording(self.root, "20261103T224512Z-r566")
        self.setenv("FAKE_RCLONE_COPY_FAIL", "1")
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_UPLOAD_FAILED)
        self.assertTrue(folder.is_dir())
        self.assertNotIn("check", [c["cmd"] for c in self.calls()])
        self.assertEqual([r["action"] for r in self.log()], ["upload_failed"])

    def test_lock_held_skips_pass(self):
        make_recording(self.root, "20261103T224512Z-r566")
        with open(self.root / ".upload.lock", "a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Separate process so the lock is contended exactly as with launchd.
            result = subprocess.run(
                [sys.executable, str(HERE / "upload_footage.py"), "--root", str(self.root),
                 "--rclone", str(self.rclone), "--once"],
                capture_output=True, text=True, env=os.environ.copy(),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("another uploader holds the lock", result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertTrue((self.root / "incoming/20261103T224512Z-r566").is_dir())
        # Lock released: a normal pass now proceeds.
        self.assertEqual(self.run_uploader(), 0)
        self.assertFalse((self.root / "incoming/20261103T224512Z-r566").exists())

    def test_quota_below_reserve_stops_uploads(self):
        folder = make_recording(self.root, "20261103T224512Z-r566")
        self.setenv("FAKE_RCLONE_FREE", str(1_500_000_000))  # 1.5 GB < 2 GB reserve
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_QUOTA)
        self.assertNotIn("copy", [c["cmd"] for c in self.calls()])
        self.assertTrue(folder.is_dir())
        stop = [r for r in self.log() if r["action"] == "quota_stop"]
        self.assertEqual(len(stop), 1)
        self.assertEqual(stop[0]["level"], "warning")
        self.assertEqual(stop[0]["attacksRemaining"], 0)

    def test_quota_stops_partway_when_reserve_reached(self):
        make_recording(self.root, "20261103T224512Z-r566", video_bytes=300_000)
        make_recording(self.root, "20261103T224600Z-r567", video_bytes=300_000)
        # Room for one recording above the reserve, not two.
        self.setenv("FAKE_RCLONE_FREE", str(2_000_000_000 + 400_000))
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_QUOTA)
        self.assertEqual(len([c for c in self.calls() if c["cmd"] == "copy"]), 1)
        self.assertTrue((self.root / "incoming/20261103T224600Z-r567").is_dir())

    def test_missing_remote_exits_cleanly(self):
        make_recording(self.root, "20261103T224512Z-r566")
        self.setenv("FAKE_RCLONE_REMOTES", "other")
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_REMOTE_UNAVAILABLE)
        self.assertNotIn("copy", [c["cmd"] for c in self.calls()])

    def test_unauthorized_remote_exits_cleanly(self):
        make_recording(self.root, "20261103T224512Z-r566")
        self.setenv("FAKE_RCLONE_ABOUT_FAIL", "1")
        self.assertEqual(self.run_uploader(), upload_footage.EXIT_REMOTE_UNAVAILABLE)
        self.assertEqual(self.log()[-1]["action"], "remote_unavailable")

    def test_missing_rclone_binary_exits_cleanly(self):
        make_recording(self.root, "20261103T224512Z-r566")
        code = upload_footage.main(["--root", str(self.root), "--rclone", str(self.root / "no-rclone"),
                                    "--once", "--quiet"])
        self.assertEqual(code, upload_footage.EXIT_NO_RCLONE)

    def test_dry_run_changes_nothing(self):
        folder = make_recording(self.root, "20261103T224512Z-r566")
        self.assertEqual(self.run_uploader("--dry-run"), 0)
        self.assertTrue(folder.is_dir())
        self.assertNotIn("copy", [c["cmd"] for c in self.calls()])
        self.assertFalse((self.root / "upload-log.jsonl").exists())

    def test_unmounted_volume_is_skipped(self):
        code = upload_footage.main(["--root", "/Volumes/coc-test-not-mounted-xyz/coc/attack-footage",
                                    "--rclone", str(self.rclone), "--once", "--quiet"])
        self.assertEqual(code, 0)
        self.assertEqual(self.calls(), [])
        self.assertFalse(Path("/Volumes/coc-test-not-mounted-xyz").exists())


class IndexTests(FootageTestCase):
    def test_index_rows(self):
        make_recording(self.root, "20261103T224512Z-r566", meta_extra={"opponent": "Bob", "percent": 52})
        make_recording(self.root, "20261103T224600Z-r567")
        make_recording(self.root, "20261103T230000Z-r568", complete=False)
        make_recording(self.root, "20261103T190000Z-r560", complete=False, age_s=3 * 3600)
        self.assertEqual(self.run_uploader(), 0)  # uploads r566 and r567

        dataset_index.main(["--root", str(self.root)])
        lines = (self.root / "index.jsonl").read_text().splitlines()
        rows = {r["id"]: r for r in map(json.loads, lines)}
        self.assertEqual(len(rows), 4)

        r566 = rows["20261103T224512Z-r566"]
        self.assertEqual(r566["state"], "uploaded")
        self.assertTrue(r566["uploaded"])
        self.assertEqual(r566["remotePath"], "coc-gdrive:coc-attack-footage/2026-11-03/20261103T224512Z-r566")
        self.assertEqual(r566["date"], "2026-11-03")
        self.assertEqual(r566["hostDurationMs"], 10_000)
        self.assertEqual(r566["videoDurationMs"], 9_500)
        self.assertEqual(r566["frames"], 140)
        self.assertEqual(r566["finalPercent"], 52)
        self.assertEqual(r566["finalPercentSource"], "meta.percent")
        self.assertEqual(r566["opponent"], "Bob")
        deploys = r566["deploys"]
        self.assertEqual([d["kind"] for d in deploys], ["spawn", "spawn", "spell", "ability"])
        self.assertEqual(deploys[0]["point"], [210, 480])
        self.assertEqual(deploys[0]["hostMs"], T0 + 1100)
        self.assertEqual(deploys[0]["videoMs"], 900)  # 1100 - videoStartHostMs offset 200
        self.assertEqual(deploys[1]["timeSource"], "batchEvent")
        self.assertEqual(deploys[1]["hostMs"], T0 + 1000)
        self.assertEqual(r566["actionCounts"]["select"], 1)
        self.assertEqual([d["percent"] for d in r566["damageCurve"]], [23, 51])

        self.assertEqual(rows["20261103T224600Z-r567"]["finalPercent"], 51)
        self.assertEqual(rows["20261103T224600Z-r567"]["finalPercentSource"], "events.cutoff")
        self.assertEqual(rows["20261103T230000Z-r568"]["state"], "recording")
        self.assertEqual(rows["20261103T230000Z-r568"]["badEventLines"], 1)
        self.assertEqual(rows["20261103T190000Z-r560"]["state"], "abandoned")
        self.assertFalse(rows["20261103T190000Z-r560"]["uploaded"])

        # Rebuilding is idempotent.
        dataset_index.main(["--root", str(self.root)])
        self.assertEqual((self.root / "index.jsonl").read_text().splitlines(), lines)

    def test_pending_upload_state(self):
        make_recording(self.root, "20261103T224512Z-r566")
        rows = dataset_index.build_index(self.root)
        self.assertEqual(rows[0]["state"], "pending_upload")
        self.assertIsNone(rows[0]["remotePath"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
