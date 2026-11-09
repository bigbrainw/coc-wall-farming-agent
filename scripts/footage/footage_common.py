"""Shared helpers for the attack-footage storage scripts.

Layout under the footage root (default /Volumes/T7/coc/attack-footage):

    incoming/<recordingId>/                 written by the recorder
    uploaded/<YYYY-MM-DD>/<recordingId>/    moved here after a verified upload
    upload-log.jsonl                        one line per uploader action
    index.jsonl                             dataset index (dataset_index.py)
    .upload.lock                            uploader lock file

A recording folder is complete only when meta.json exists (the recorder
writes it last, atomically).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
from pathlib import Path

DEFAULT_ROOT = "/Volumes/T7/coc/attack-footage"
ABANDONED_AFTER_S = 2 * 60 * 60
RECORDING_ID_RE = re.compile(r"^(\d{8})T(\d{6})Z-[A-Za-z0-9_-]+$")


def default_root() -> Path:
    return Path(os.environ.get("COC_FOOTAGE_ROOT", DEFAULT_ROOT))


def required_mount(root: Path) -> Path | None:
    """Return the /Volumes/<name> mount point the root lives on, if any."""
    parts = root.resolve().parts if root.exists() else Path(os.path.abspath(root)).parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        return Path("/", "Volumes", parts[2])
    return None


def volume_available(root: Path) -> bool:
    """False when the root is on an external volume that is not mounted.

    Prevents writing footage state onto the internal disk under a stale
    /Volumes/T7 directory.
    """
    mount = required_mount(Path(os.path.abspath(root)))
    if mount is None:
        return True
    return os.path.ismount(mount)


def recording_date(recording_id: str, meta: dict | None = None) -> str:
    """UTC date (YYYY-MM-DD) of a recording, from its id or meta."""
    match = RECORDING_ID_RE.match(recording_id)
    if match:
        day = match.group(1)
        return f"{day[0:4]}-{day[4:6]}-{day[6:8]}"
    started = (meta or {}).get("startedAtMs")
    if isinstance(started, (int, float)):
        return _dt.datetime.fromtimestamp(started / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")
    return "unknown-date"


def read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def newest_mtime(folder: Path) -> float:
    newest = folder.stat().st_mtime
    for child in folder.rglob("*"):
        try:
            newest = max(newest, child.stat().st_mtime)
        except OSError:
            pass
    return newest


def is_os_sidecar(name: str) -> bool:
    """macOS metadata files (AppleDouble on ExFAT, Finder state); not footage."""
    return name.startswith("._") or name == ".DS_Store"


def folder_bytes(folder: Path) -> int:
    total = 0
    for child in folder.rglob("*"):
        try:
            if child.is_file() and not is_os_sidecar(child.name):
                total += child.stat().st_size
        except OSError:
            pass
    return total


def classify_incoming(folder: Path, now: float | None = None) -> str:
    """'complete', 'recording' (still being written) or 'abandoned'."""
    if (folder / "meta.json").is_file():
        return "complete"
    now = time.time() if now is None else now
    if now - newest_mtime(folder) > ABANDONED_AFTER_S:
        return "abandoned"
    return "recording"


def incoming_folders(root: Path) -> list[Path]:
    base = root / "incoming"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))


def uploaded_folders(root: Path) -> list[Path]:
    base = root / "uploaded"
    if not base.is_dir():
        return []
    found = []
    for day in sorted(base.iterdir()):
        if day.is_dir() and not day.name.startswith("."):
            found.extend(sorted(p for p in day.iterdir() if p.is_dir() and not p.name.startswith(".")))
    return found


def read_log(root: Path) -> list[dict]:
    rows = []
    try:
        with open(root / "upload-log.jsonl", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name("." + path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
