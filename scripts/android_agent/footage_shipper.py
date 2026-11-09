"""Move complete attack recordings from the laptop outbox to the Mac mini's T7.

The recorder writes <outbox>/incoming/<id>/ and publishes meta.json last.
This shipper (a background thread inside the watcher, never touching the game):

  1. copies a complete folder to <remote>/.transfer/<id>/ over `ssh mini`
     (hidden folder: the mini's uploader ignores it),
  2. checks the SHA-256 of every file on both sides,
  3. renames it to <remote>/incoming/<id> in one step on the same volume,
     so the uploader only ever sees complete recordings,
  4. removes the laptop copy only after 1-3 succeeded.

Any failure leaves the laptop copy in place and retries later.

  python3 footage_shipper.py --once     # ship the current backlog and exit
"""
import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

DEFAULT_OUTBOX = Path.home() / "coc-footage-outbox"
DEFAULT_REMOTE = "mini:/Volumes/T7/coc/attack-footage"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def local_hashes(folder):
    out = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
            out[str(path.relative_to(folder))] = digest.hexdigest()
    return out


class Shipper:
    def __init__(self, outbox=DEFAULT_OUTBOX, remote=DEFAULT_REMOTE, retry_s=300, log=None, run=None):
        self.outbox = Path(outbox).expanduser()
        self.host, self.root = remote.split(":", 1)
        self.retry_s = retry_s
        self.log_path = Path(log) if log else self.outbox / "ship-log.jsonl"
        # SSH must never inherit the watcher's command FIFO. Besides consuming
        # commands, it can set the shared stdin descriptor nonblocking and make
        # the command reader mistake a temporarily empty FIFO for EOF.
        self.run = run or (lambda cmd, **kw: subprocess.run(cmd, stdin=subprocess.DEVNULL,
                                                          capture_output=True, text=True,
                                                          timeout=1800, **kw))
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.thread = None

    # -- helpers -----------------------------------------------------------
    def note(self, **row):
        row = {"t": int(time.time() * 1000), **row}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a") as stream:
            stream.write(json.dumps(row) + "\n")

    def ssh(self, command):
        return self.run(SSH + [self.host, command])

    def pending(self):
        incoming = self.outbox / "incoming"
        if not incoming.is_dir():
            return []
        return sorted(p for p in incoming.iterdir()
                      if p.is_dir() and not p.name.startswith(".") and (p / "meta.json").is_file())

    # -- one folder ----------------------------------------------------------
    def ship(self, folder):
        rid = folder.name
        q = shlex.quote
        transfer = f"{self.root}/.transfer/{rid}"
        final = f"{self.root}/incoming/{rid}"
        r = self.ssh(f"test -d {q(self.root + '/incoming')} && test ! -e {q(final)} "
                     f"&& rm -rf {q(transfer)} && mkdir -p {q(transfer)}")
        if r.returncode:
            raise RuntimeError(f"mini not ready or {rid} already there: {r.stderr.strip()[:200]}")
        r = self.run(["rsync", "-a", "-e", " ".join(SSH), f"{folder}/", f"{self.host}:{transfer}/"])
        if r.returncode:
            raise RuntimeError(f"rsync failed: {r.stderr.strip()[:200]}")
        want = local_hashes(folder)
        r = self.ssh(f"cd {q(transfer)} && find . -type f -print0 | xargs -0 shasum -a 256")
        if r.returncode:
            raise RuntimeError(f"remote checksum failed: {r.stderr.strip()[:200]}")
        got = {}
        for line in r.stdout.splitlines():
            digest, _, name = line.partition("  ")
            got[name[2:] if name.startswith("./") else name] = digest
        if got != want:
            raise RuntimeError(f"checksum mismatch for {rid}")
        r = self.ssh(f"test ! -e {q(final)} && mv {q(transfer)} {q(final)}")
        if r.returncode:
            raise RuntimeError(f"final rename failed: {r.stderr.strip()[:200]}")
        size = sum((folder / n).stat().st_size for n in want)
        shutil.rmtree(folder)  # only after the verified copy is in the mini's incoming/
        self.note(event="shipped", id=rid, files=len(want), bytes=size)

    def ship_all(self):
        with self.lock:
            done = failed = 0
            for folder in self.pending():
                try:
                    self.ship(folder)
                    done += 1
                except Exception as exc:  # keep the laptop copy, retry later
                    failed += 1
                    self.note(event="ship_failed", id=folder.name, error=str(exc)[:300])
            return {"shipped": done, "failed": failed}

    # -- background ------------------------------------------------------------
    def start(self):
        def loop():
            while True:
                self.ship_all()
                self.wake.wait(self.retry_s)
                self.wake.clear()
        self.thread = threading.Thread(target=loop, name="footage-shipper", daemon=True)
        self.thread.start()
        return self

    def kick(self):
        self.wake.set()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--outbox", default=str(DEFAULT_OUTBOX))
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    shipper = Shipper(args.outbox, args.remote)
    if args.once:
        print(json.dumps(shipper.ship_all()))
    else:
        shipper.start().thread.join()
