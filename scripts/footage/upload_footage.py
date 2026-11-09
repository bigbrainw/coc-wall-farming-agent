#!/usr/bin/env python3
"""Passive uploader for Clash of Clans attack footage.

Reads recordings written by the game controller's recorder and copies each
complete one to Google Drive with rclone:

    incoming/<recordingId>/  ->  coc-gdrive:coc-attack-footage/<YYYY-MM-DD>/<recordingId>/

Only after `rclone check` confirms the remote copy (size and hash where the
backend supports it) is the local folder moved to
uploaded/<YYYY-MM-DD>/<recordingId>/. Local copies are never deleted.

This script never touches the game, the emulator or adb. It only reads the
footage folders, moves verified ones, and appends to upload-log.jsonl.

Exit codes:
    0  success, nothing to do, another uploader running, or volume not mounted
    1  at least one upload or verification failed
    2  rclone binary not found
    3  rclone remote missing or not authorized
    4  stopped because Google Drive free space is below the reserve
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from footage_common import (  # noqa: E402
    classify_incoming,
    default_root,
    folder_bytes,
    incoming_folders,
    read_json,
    read_log,
    recording_date,
    uploaded_folders,
    volume_available,
)

REMOTE_NAME = "coc-gdrive"
REMOTE_DIR = "coc-attack-footage"
RESERVE_BYTES = 2 * 1000 ** 3  # 2 GB kept free on Drive
DEFAULT_RECORDING_BYTES = 75 * 1000 ** 2  # estimate before any real recordings exist
# macOS writes AppleDouble "._*" sidecars on ExFAT volumes such as T7; never upload them.
RCLONE_FILTERS = ("--exclude", "._*", "--exclude", ".DS_Store")

EXIT_OK = 0
EXIT_UPLOAD_FAILED = 1
EXIT_NO_RCLONE = 2
EXIT_REMOTE_UNAVAILABLE = 3
EXIT_QUOTA = 4

SETUP_HINT = (
    "Create the remote once in your own terminal (browser login as the footage Google account):\n"
    f"    rclone config create {REMOTE_NAME} drive scope=drive.file\n"
    f"Then verify with:  rclone about {REMOTE_NAME}:"
)


class RemoteUnavailable(Exception):
    pass


class Uploader:
    def __init__(self, root: Path, rclone: str, remote: str, remote_dir: str,
                 reserve_bytes: int, dry_run: bool, verbose: bool = True):
        self.root = root
        self.rclone = rclone
        self.remote = remote
        self.remote_dir = remote_dir
        self.reserve_bytes = reserve_bytes
        self.dry_run = dry_run
        self.verbose = verbose

    # ------------------------------------------------------------------ output

    def say(self, message: str) -> None:
        if self.verbose:
            print(message, flush=True)

    def warn(self, message: str) -> None:
        """Always shown, even with --quiet (lands in the launchd log)."""
        print(time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime()) + message, file=sys.stderr, flush=True)

    def log(self, action: str, **fields) -> None:
        now = time.time()
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "tsMs": int(now * 1000),
            "action": action,
            **fields,
        }
        if self.dry_run:
            self.say("[dry-run] would log " + json.dumps(row, ensure_ascii=False))
            return
        with open(self.root / "upload-log.jsonl", "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ rclone

    def run_rclone(self, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([self.rclone, *args], capture_output=True, text=True, timeout=timeout)

    def check_remote(self) -> dict:
        """Confirm the remote exists and is authorized; return quota info."""
        try:
            listed = self.run_rclone("listremotes", timeout=60)
        except FileNotFoundError:
            raise
        names = {line.strip().rstrip(":") for line in listed.stdout.splitlines() if line.strip()}
        if listed.returncode != 0 or self.remote not in names:
            raise RemoteUnavailable(f"rclone remote '{self.remote}:' is not configured.\n{SETUP_HINT}")
        about = self.run_rclone("about", self.remote + ":", "--json", timeout=120)
        if about.returncode != 0:
            detail = (about.stderr or about.stdout).strip().splitlines()[-3:]
            raise RemoteUnavailable(
                f"rclone remote '{self.remote}:' did not answer (not authorized or offline):\n    "
                + "\n    ".join(detail)
                + f"\nIf the login expired, run:  rclone config reconnect {self.remote}:\n{SETUP_HINT}"
            )
        try:
            info = json.loads(about.stdout)
        except ValueError:
            info = {}
        total, used, free = info.get("total"), info.get("used"), info.get("free")
        if free is None and total is not None and used is not None:
            free = total - used
        return {"total": total, "used": used, "free": free, "trashed": info.get("trashed")}

    def remote_path(self, date: str, recording_id: str) -> str:
        return f"{self.remote}:{self.remote_dir}/{date}/{recording_id}"

    # ------------------------------------------------------------------ helpers

    def average_recording_bytes(self) -> int:
        sizes = [folder_bytes(p) for p in uploaded_folders(self.root)]
        sizes += [folder_bytes(p) for p in incoming_folders(self.root) if (p / "meta.json").is_file()]
        sizes = [s for s in sizes if s > 0]
        return int(sum(sizes) / len(sizes)) if sizes else DEFAULT_RECORDING_BYTES

    def attacks_remaining(self, free: int | None, average: int) -> int | None:
        if free is None:
            return None
        return max(0, (free - self.reserve_bytes) // max(average, 1))

    # ------------------------------------------------------------------ main pass

    def run_once(self) -> int:
        now = time.time()
        already_abandoned = {r.get("recordingId") for r in read_log(self.root) if r.get("action") == "abandoned"}
        complete = []
        for folder in incoming_folders(self.root):
            state = classify_incoming(folder, now)
            if state == "complete":
                complete.append(folder)
            elif state == "abandoned":
                if folder.name not in already_abandoned:
                    self.say(f"abandoned (no meta.json for >2h, left in place): {folder.name}")
                    self.log("abandoned", recordingId=folder.name, path=str(folder))
            else:
                self.say(f"still recording, skipped: {folder.name}")

        if not complete:
            self.say("no complete recordings to upload")
            return EXIT_OK

        try:
            quota = self.check_remote()
        except FileNotFoundError:
            message = f"rclone not found ({self.rclone}). Install it with: brew install rclone"
            self.warn(message)
            self.log("remote_unavailable", reason="rclone_missing", pending=len(complete))
            return EXIT_NO_RCLONE
        except RemoteUnavailable as error:
            self.warn(str(error))
            self.log("remote_unavailable", reason=str(error).splitlines()[0], pending=len(complete))
            return EXIT_REMOTE_UNAVAILABLE

        average = self.average_recording_bytes()
        free = quota.get("free")
        self.say(
            "Drive quota: free={} used={} total={}; avg recording {:.1f} MB; "
            "attacks that still fit (keeping {:.1f} GB reserve): {}".format(
                _gb(free), _gb(quota.get("used")), _gb(quota.get("total")),
                average / 1e6, self.reserve_bytes / 1e9, self.attacks_remaining(free, average),
            )
        )

        exit_code = EXIT_OK
        for folder in complete:
            size = folder_bytes(folder)
            if free is not None and free - size < self.reserve_bytes:
                self.warn(f"QUOTA STOP: Drive free {_gb(free)} would drop below the "
                         f"{self.reserve_bytes / 1e9:.1f} GB reserve; uploads paused")
                self.log("quota_stop", level="warning", recordingId=folder.name, free=free,
                         reserveBytes=self.reserve_bytes, recordingBytes=size,
                         pending=len(complete), attacksRemaining=self.attacks_remaining(free, average))
                return EXIT_QUOTA
            if not self.upload_one(folder, size):
                exit_code = EXIT_UPLOAD_FAILED
            elif free is not None:
                free -= size

        if free is not None:
            self.say(f"after this pass: about {self.attacks_remaining(free, average)} more attacks fit on Drive")
        return exit_code

    def upload_one(self, folder: Path, size: int) -> bool:
        recording_id = folder.name
        meta = read_json(folder / "meta.json") or {}
        date = recording_date(recording_id, meta)
        remote = self.remote_path(date, recording_id)
        target = self.root / "uploaded" / date / recording_id

        if self.dry_run:
            self.say(f"[dry-run] would upload {folder} -> {remote} ({size / 1e6:.1f} MB), "
                     f"verify, then move to {target}")
            return True

        if target.exists():
            self.warn(f"refusing to move {recording_id}: {target} already exists")
            self.log("move_conflict", recordingId=recording_id, target=str(target))
            return False

        self.say(f"uploading {recording_id} ({size / 1e6:.1f} MB) -> {remote}")
        started = time.time()
        copy = self.run_rclone("copy", str(folder), remote, *RCLONE_FILTERS,
                               "--retries", "3", "--low-level-retries", "10")
        if copy.returncode != 0:
            self.warn(f"upload failed for {recording_id}; left in incoming")
            self.log("upload_failed", recordingId=recording_id, remote=remote, bytes=size,
                     rcloneExit=copy.returncode, stderr=_tail(copy.stderr))
            return False

        check = self.run_rclone("check", str(folder), remote, *RCLONE_FILTERS)
        if check.returncode != 0:
            self.warn(f"verification failed for {recording_id}; left in incoming")
            self.log("verify_failed", recordingId=recording_id, remote=remote, bytes=size,
                     rcloneExit=check.returncode, stderr=_tail(check.stderr))
            return False

        if not (folder / "meta.json").is_file():
            # Should never happen; the folder changed under us. Do not move.
            self.log("verify_failed", recordingId=recording_id, remote=remote,
                     reason="meta.json disappeared after verification")
            return False

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(folder, target)  # same volume: atomic, never deletes data
        except OSError as error:
            self.warn(f"verified but could not move {recording_id}: {error}")
            self.log("move_failed", recordingId=recording_id, remote=remote, error=str(error))
            return False

        self.say(f"uploaded and verified {recording_id}")
        self.log("uploaded", recordingId=recording_id, date=date, remote=remote, bytes=size,
                 seconds=round(time.time() - started, 1), localPath=str(target))
        return True


def _gb(value) -> str:
    return "unknown" if value is None else f"{value / 1e9:.2f} GB"


def _tail(text: str, lines: int = 5) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


class LockBusy(Exception):
    pass


class FootageLock:
    """Exclusive non-blocking flock on <root>/.upload.lock."""

    def __init__(self, root: Path):
        self.path = root / ".upload.lock"
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.handle.close()
            self.handle = None
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise LockBusy(str(self.path)) from error
            raise
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"{os.getpid()}\n")
        self.handle.flush()
        return self

    def __exit__(self, *exc):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
        return False


def find_rclone(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("COC_FOOTAGE_RCLONE")
    if env:
        return env
    found = shutil.which("rclone")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/rclone", "/usr/local/bin/rclone"):
        if os.path.exists(candidate):
            return candidate
    return "rclone"


def run_pass(args) -> int:
    root = Path(args.root)
    if not volume_available(root):
        if args.verbose:
            print(f"footage volume for {root} not mounted; skipping")
        return EXIT_OK
    if not root.is_dir():
        if args.verbose:
            print(f"footage root {root} does not exist yet; nothing to do")
        return EXIT_OK
    uploader = Uploader(root, find_rclone(args.rclone), args.remote, args.remote_dir,
                        int(args.reserve_gb * 1e9), args.dry_run, args.verbose)
    try:
        with FootageLock(root):
            return uploader.run_once()
    except LockBusy:
        if args.verbose:
            print("another uploader holds the lock; skipping this pass")
        return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(default_root()), help="footage root directory")
    parser.add_argument("--rclone", help="rclone binary (default: $COC_FOOTAGE_RCLONE or PATH)")
    parser.add_argument("--remote", default=REMOTE_NAME, help="rclone remote name")
    parser.add_argument("--remote-dir", default=REMOTE_DIR, help="folder on the remote")
    parser.add_argument("--reserve-gb", type=float, default=RESERVE_BYTES / 1e9,
                        help="stop uploading when Drive free space would drop below this")
    parser.add_argument("--dry-run", action="store_true", help="report only; no upload, move or log")
    parser.add_argument("--once", action="store_true", help="run one pass and exit")
    parser.add_argument("--interval", type=float, default=600, help="seconds between passes without --once")
    parser.add_argument("--quiet", dest="verbose", action="store_false", help="less output")
    args = parser.parse_args(argv)

    if args.once or args.dry_run:
        return run_pass(args)
    while True:
        code = run_pass(args)
        if code in (EXIT_NO_RCLONE, EXIT_REMOTE_UNAVAILABLE):
            return code
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
