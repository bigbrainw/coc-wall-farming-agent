#!/usr/bin/env python3
"""Build <footage root>/index.jsonl: one row per attack recording.

Reads recordings under incoming/ and uploaded/ (read-only) plus
upload-log.jsonl, and rewrites index.jsonl atomically. Rerunning is safe and
reflects the current state. See DATASET.md for the row schema and how video
time lines up with event time.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from footage_common import (  # noqa: E402
    atomic_write_text,
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

INDEX_VERSION = 1
DEPLOY_KINDS = ("spawn", "spell", "ability")


def read_events(path: Path) -> tuple[list[dict], int]:
    events, bad = [], 0
    try:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    bad += 1  # e.g. a partial last line of an unfinished recording
                    continue
                if isinstance(row, dict):
                    events.append(row)
                else:
                    bad += 1
    except OSError:
        pass
    return events, bad


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def video_ms(host_ms, video_start_host_ms):
    """Milliseconds into video.mkv for a host-clock time (file PTS starts at 0)."""
    if host_ms is None or video_start_host_ms is None:
        return None
    return host_ms - video_start_host_ms


def summarize_events(events: list[dict], video_start_host_ms) -> dict:
    deploys, damage_curve, counts, action_counts = [], [], {}, {}
    cutoff = None
    last_damage = None
    for event in events:
        kind = event.get("type")
        counts[kind] = counts.get(kind, 0) + 1
        t = _number(event.get("t"))
        if kind == "batch":
            for order, action in enumerate(event.get("actions") or []):
                if not isinstance(action, dict):
                    continue
                action_kind = action.get("kind")
                action_counts[action_kind] = action_counts.get(action_kind, 0) + 1
                if action_kind not in DEPLOY_KINDS:
                    continue
                issued = _number(action.get("issuedAtMs"))
                at = issued if issued is not None else t
                point = action.get("point")
                deploys.append({
                    "kind": action_kind,
                    "label": action.get("label"),
                    "point": point if isinstance(point, list) else None,
                    "hostMs": at,
                    "timeSource": "issuedAtMs" if issued is not None else "batchEvent",
                    "videoMs": video_ms(at, video_start_host_ms),
                    "batchId": event.get("id"),
                    "order": order,
                })
        elif kind == "damage":
            damage = _number(event.get("damage"))
            if damage is not None:
                damage_curve.append({"hostMs": t, "videoMs": video_ms(t, video_start_host_ms),
                                     "percent": damage})
                last_damage = damage
        elif kind == "cutoff":
            cutoff = {"hostMs": t, "status": event.get("status"), "damage": event.get("damage")}
    return {
        "deploys": deploys,
        "damageCurve": damage_curve,
        "eventCounts": counts,
        "actionCounts": action_counts,
        "cutoff": cutoff,
        "lastDamage": last_damage,
    }


def final_percent(meta: dict, summary: dict):
    for key in ("percent", "destruction", "damage"):
        value = _number(meta.get(key))
        if value is not None:
            return value, "meta." + key
    cutoff_meta = meta.get("cutoff") if isinstance(meta.get("cutoff"), dict) else {}
    if _number(cutoff_meta.get("damage")) is not None:
        return cutoff_meta["damage"], "meta.cutoff.damage"
    cutoff = summary.get("cutoff") or {}
    if _number(cutoff.get("damage")) is not None:
        return cutoff["damage"], "events.cutoff"
    if summary.get("lastDamage") is not None:
        return summary["lastDamage"], "events.lastDamage"
    return None, None


def build_row(root: Path, folder: Path, state: str, uploads: dict) -> dict:
    recording_id = folder.name
    meta = read_json(folder / "meta.json") or {}
    events, bad_lines = read_events(folder / "events.jsonl")
    video_start_host_ms = _number(meta.get("videoStartHostMs"))
    summary = summarize_events(events, video_start_host_ms)
    started, ended = _number(meta.get("startedAtMs")), _number(meta.get("endedAtMs"))
    if started is None and events:
        started = _number(events[0].get("t"))
    if ended is None and events:
        ended = _number(events[-1].get("t"))
    percent, percent_source = final_percent(meta, summary)
    upload = uploads.get(recording_id) or {}
    video = folder / "video.mkv"
    return {
        "indexVersion": INDEX_VERSION,
        "id": recording_id,
        "raid": meta.get("raid"),
        "date": recording_date(recording_id, meta),
        "state": state,
        "uploaded": state == "uploaded",
        "remotePath": upload.get("remote"),
        "uploadedAt": upload.get("ts"),
        "localPath": str(folder.relative_to(root)),
        "startedAtMs": started,
        "endedAtMs": ended,
        "hostDurationMs": (ended - started) if started is not None and ended is not None else None,
        "videoDurationMs": _number(meta.get("durationMs")),
        "frames": _number(meta.get("frames")),
        "videoBytes": video.stat().st_size if video.is_file() else None,
        "folderBytes": folder_bytes(folder),
        "size": meta.get("size"),
        "videoStartPtsUs": _number(meta.get("videoStartPtsUs")),
        "videoStartHostMs": video_start_host_ms,
        "opponent": meta.get("opponent"),
        "loot": meta.get("loot"),
        "stars": meta.get("stars"),
        "finalPercent": percent,
        "finalPercentSource": percent_source,
        "stopReason": meta.get("stopReason"),
        "recordError": meta.get("recordError"),
        "deploys": summary["deploys"],
        "damageCurve": summary["damageCurve"],
        "cutoff": summary["cutoff"],
        "eventCounts": summary["eventCounts"],
        "actionCounts": summary["actionCounts"],
        "badEventLines": bad_lines,
    }


def build_index(root: Path, now: float | None = None) -> list[dict]:
    uploads = {}
    for row in read_log(root):
        if row.get("action") == "uploaded" and row.get("recordingId"):
            uploads[row["recordingId"]] = row
    rows = []
    for folder in uploaded_folders(root):
        rows.append(build_row(root, folder, "uploaded", uploads))
    for folder in incoming_folders(root):
        state = classify_incoming(folder, now)
        state = {"complete": "pending_upload"}.get(state, state)
        rows.append(build_row(root, folder, state, uploads))
    rows.sort(key=lambda r: r["id"])
    return rows


def write_index(root: Path, rows: list[dict]) -> Path:
    path = root / "index.jsonl"
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", default=str(default_root()), help="footage root directory")
    parser.add_argument("--stdout", action="store_true", help="print rows instead of writing index.jsonl")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not volume_available(root) or not root.is_dir():
        print(f"footage root {root} not available; nothing indexed")
        return 0
    rows = build_index(root, time.time())
    if args.stdout:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
        return 0
    path = write_index(root, rows)
    states = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    print(f"wrote {len(rows)} rows to {path} {json.dumps(states)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
