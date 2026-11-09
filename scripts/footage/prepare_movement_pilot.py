#!/usr/bin/env python3
"""Read-only footage audit and source-bound movement annotation packet.

Writes only to a fresh derived output directory. No optimizer or game access.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import unicodedata

from dataset_index import build_row, read_events
from footage_common import incoming_folders, uploaded_folders, volume_available


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def inspect_recording(root, folder, hash_video=True):
    meta = load_json(folder / 'meta.json')
    validation = load_json(folder / 'validation.json')
    events, bad = read_events(folder / 'events.jsonl')
    reasons = []
    if validation.get('usableVideoVerified') is not True:
        reasons.append('saved_video_validation_failed_or_missing')
    if validation.get('monotonicPts') is not True:
        reasons.append('monotonic_timestamps_not_verified')
    if meta.get('recordError'):
        reasons.append('recorder_error')
    if meta.get('size') != [1280, 960]:
        reasons.append('unexpected_geometry')
    if bad:
        reasons.append('malformed_event_lines')
    if not events:
        reasons.append('missing_events')
    video = folder / 'video.mkv'
    if not video.is_file() or video.stat().st_size == 0:
        reasons.append('missing_or_empty_video')
    start = meta.get('videoStartHostMs')
    duration = meta.get('durationMs')
    if not finite_number(start) or not finite_number(duration) or duration <= 0:
        reasons.append('missing_clock_mapping')
    issued_spawns, issued_actions, action_stats = [], [], Counter()
    for event in events:
        if event.get('type') != 'batch':
            continue
        actions, receipts = event.get('actions') or [], event.get('issued') or []
        action_stats['planned'] += len(actions)
        action_stats['issued_receipts'] += len(receipts)
        for i, action in enumerate(actions):
            # Planned actions without a corresponding sent-input receipt are
            # not admitted as deployment anchors, even if a batch time exists.
            if i >= len(receipts) or not isinstance(action, dict):
                continue
            receipt = receipts[i]
            if not isinstance(receipt, dict):
                continue
            if (receipt.get('label') != action.get('label')
                    or (action.get('issuedAtMs') is not None
                        and action['issuedAtMs'] != receipt.get('issuedAtMs'))):
                action_stats['mismatched_receipts'] += 1
                continue
            action_time = receipt.get('issuedAtMs')
            if not finite_number(action_time):
                continue
            if not finite_number(start) or not finite_number(duration):
                continue
            at = action_time - start
            point = action.get('point')
            if (not 0 <= at < duration
                    or not isinstance(point, list) or len(point) != 2
                    or not all(finite_number(x) for x in point)
                    or not (0 <= point[0] < 1280 and 0 <= point[1] < 960)):
                continue
            sent = {'kind': action.get('kind'), 'label': action.get('label'), 'point': point,
                    'video_ms': at, 'batch_id': event.get('id'),
                    'acceptance': 'sent_input_not_visually_verified'}
            issued_actions.append(sent)
            if action.get('kind') == 'spawn':
                issued_spawns.append(sent)
    issued_spawns.sort(key=lambda s: s['video_ms'])
    issued_actions.sort(key=lambda s: s['video_ms'])
    opponent = meta.get('opponent')
    normalized = unicodedata.normalize('NFKC', opponent).casefold().strip() if isinstance(opponent, str) else ''
    group = hashlib.sha256(normalized.encode()).hexdigest() if normalized else 'unknown-opponent'
    bucket = int(hashlib.sha256(('movement-pilot-v1:' + group).encode()).hexdigest()[:8], 16) % 100
    split = 'train' if bucket < 70 else 'val' if bucket < 85 else 'test'
    valk = [s for s in issued_spawns if re.search('valk', str(s.get('label')), re.I)]
    row = build_row(root, folder, 'uploaded' if 'uploaded' in folder.relative_to(root).parts else 'pending_upload', {})
    row.update({
        'source_sha256': {name: sha256(folder / name) for name in
                          ['meta.json', 'events.jsonl', 'validation.json'] if (folder / name).is_file()},
        'video_sha256': sha256(video) if hash_video and video.is_file() else None,
        'saved_validation': validation,
        'validation_status': ('verified' if validation.get('usableVideoVerified') is True
                              else 'failed' if validation else 'missing'),
        'eligibility': 'excluded' if reasons else 'eligible_by_saved_validation',
        'exclusion_reasons': reasons, 'opponent_group': group,
        'provisional_split': split, 'visual_layout_dedup_pending': True,
        'issued_spawns': issued_spawns, 'issued_actions': issued_actions,
        'issued_action_stats': dict(action_stats),
        'movement_labels': 0, 'training_ready': False,
        'pilot_start_ms': max(0, valk[0]['video_ms'] - 500) if valk else None,
        'scout_time_ms': max(0, issued_spawns[0]['video_ms'] - 1000) if issued_spawns else None,
    })
    return row


def select_pilot(rows, counts=None):
    counts = counts or {'train': 14, 'val': 3, 'test': 3}
    selected, groups = [], set()
    for split, wanted in counts.items():
        if wanted <= 0:
            continue
        candidates = sorted((r for r in rows
                             if r['eligibility'] == 'eligible_by_saved_validation'
                             and r.get('pilot_start_ms') is not None
                             and r['pilot_start_ms'] + 8000 < r['videoDurationMs']
                             and r['opponent_group'] != 'unknown-opponent'
                             and r['provisional_split'] == split),
                            key=lambda r: hashlib.sha256(r['id'].encode()).hexdigest())
        taken = 0
        for row in candidates:
            if row['opponent_group'] in groups:
                continue
            selected.append(row); groups.add(row['opponent_group']); taken += 1
            if taken >= wanted:
                break
    return selected


def extract_packet(root, output, row, ffmpeg):
    from PIL import Image, ImageDraw
    packet = output / 'annotation_packets' / row['id']
    packet.mkdir(parents=True)
    video = root / row['localPath'] / 'video.mkv'
    start = row['pilot_start_ms'] / 1000
    command = [ffmpeg, '-hide_banner', '-nostdin', '-ss', str(start), '-t', '8',
               '-copyts', '-i', str(video), '-an', '-vf',
               f"trim=start={start}:end={start+8},select='isnan(prev_selected_t)+gte(t-prev_selected_t,0.5)',showinfo",
               '-fps_mode', 'vfr', '-frames:v', '16', '-q:v', '2', str(packet / 'frame-%03d.jpg')]
    run = subprocess.run(command, capture_output=True, text=True, timeout=90)
    (packet / 'decode.log').write_text(run.stderr)
    times = [float(x) for x in re.findall(r'\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([\d.eE+-]+)', run.stderr)]
    frames = sorted(packet.glob('frame-*.jpg'))
    if (run.returncode or len(frames) != len(times) or len(frames) < 8
            or times[0] < start - .002 or times[-1] > start + 8.002
            or any(b <= a for a, b in zip(times, times[1:]))):
        raise RuntimeError('Frame/PTS extraction failed for ' + row['id'])
    labels = {'schema_version': 1, 'recording_id': row['id'],
              'video_sha256': row['video_sha256'], 'split': row['provisional_split'],
              'split_status': 'provisional_pending_visual_layout_dedup',
              'label_status': 'unlabeled', 'coordinates': 'original_1280x960_screen_pixels',
              'camera_review': 'pending', 'playback_speed': None,
              'clock_mapping_review': 'pending_packet_arrival_time_is_not_capture_time',
              'maximum_sample_gap_ms': round(max(b-a for a, b in zip(times, times[1:])) * 1000, 3),
              'issued_actions': row['issued_actions'],
              'extraction_command': command,
              'frames': [{'image': p.name, 'sha256': sha256(p), 'source_video_ms': round(t * 1000, 3),
                          'troop_groups': [], 'visible_targets': [], 'review_status': 'pending'}
                         for p, t in zip(frames, times)]}
    (packet / 'labels.json').write_text(json.dumps(labels, indent=2) + '\n')
    sheet = Image.new('RGB', (1280, 4 * 264), '#202020'); draw = ImageDraw.Draw(sheet)
    for i, (path, t) in enumerate(zip(frames, times)):
        with Image.open(path) as image:
            sheet.paste(image.resize((320, 240)), ((i % 4) * 320, (i // 4) * 264 + 24))
        draw.text(((i % 4) * 320 + 5, (i // 4) * 264 + 5), f'{i+1}: {t:.3f}s', fill='white')
    sheet.save(packet / 'contact-sheet.jpg', quality=88)
    return {'recording_id': row['id'], 'split': row['provisional_split'], 'frames': len(frames),
            'source_first_ms': times[0] * 1000, 'source_last_ms': times[-1] * 1000,
            'label_status': 'unlabeled', 'path': str(packet.relative_to(output))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/Volumes/T7/coc/attack-footage'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--extract-pilot', action='store_true')
    parser.add_argument('--ffmpeg', default='/opt/homebrew/bin/ffmpeg')
    args = parser.parse_args()
    if not volume_available(args.root):
        parser.error('Footage volume is not mounted')
    if args.out.exists() or args.out.resolve().is_relative_to((args.root / 'uploaded').resolve()) or args.out.resolve().is_relative_to((args.root / 'incoming').resolve()):
        parser.error('Use a fresh derived output path outside raw recording folders')
    args.out.mkdir(parents=True)
    rows = []
    folders = uploaded_folders(args.root) + [p for p in incoming_folders(args.root) if (p / 'meta.json').is_file()]
    for i, folder in enumerate(folders):
        rows.append(inspect_recording(args.root, folder))
        if (i + 1) % 20 == 0:
            print(f'audited {i+1}/{len(folders)} recordings', flush=True)
    pilot = select_pilot(rows)
    (args.out / 'catalog.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
    report = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'preparation_script_sha256': sha256(Path(__file__)),
              'recordings': len(rows), 'eligibility': dict(Counter(r['eligibility'] for r in rows)),
              'storage_states': dict(Counter(r['state'] for r in rows)),
              'saved_validation_status': dict(Counter(r['validation_status'] for r in rows)),
              'excluded': [{'id': r['id'], 'reasons': r['exclusion_reasons']} for r in rows if r['exclusion_reasons']],
              'eligible_video_minutes': sum(r['videoDurationMs'] for r in rows if not r['exclusion_reasons']) / 60000,
              'pilot_recordings': len(pilot), 'pilot_splits': dict(Counter(r['provisional_split'] for r in pilot)),
              'movement_labels': 0, 'training_ready': False,
              'remaining': ['troop trajectory/target annotation', 'clock and camera review',
                            'visual layout deduplication before freezing splits', 'training runtime connection']}
    (args.out / 'quality_report.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.out / 'pilot_selection.json').write_text(json.dumps([{'id': r['id'], 'opponent_group': r['opponent_group'],
        'split': r['provisional_split'], 'video_sha256': r['video_sha256'], 'pilot_start_ms': r['pilot_start_ms']}
        for r in pilot], indent=2) + '\n')
    packets = []
    if args.extract_pilot:
        for row in pilot:
            try:
                packets.append(extract_packet(args.root, args.out, row, args.ffmpeg))
                print('prepared ' + row['id'], flush=True)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                packets.append({'recording_id': row['id'], 'status': 'extraction_failed',
                                'error': str(exc)})
                print('extraction failed ' + row['id'] + ': ' + str(exc), flush=True)
        (args.out / 'annotation_packets.json').write_text(json.dumps(packets, indent=2) + '\n')
        report['packets_prepared'] = sum(p.get('label_status') == 'unlabeled' for p in packets)
        report['packet_failures'] = [p for p in packets if p.get('status') == 'extraction_failed']
        (args.out / 'quality_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
