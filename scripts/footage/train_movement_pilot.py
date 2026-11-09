#!/usr/bin/env python3
"""Colab-only, position-history pilot; rejects unreviewed movement packets.

No game access, action imitation, video generation or three-star objective.
Imports torch only after dataset checks and the existing Colab-only restriction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time


SIZE = (1280, 960)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_colab():
    # Keep the existing project's training-location rule. No local bypass flag.
    if os.environ.get('COLAB_RELEASE_TAG'):
        return
    try:
        import google.colab  # noqa: F401
    except ImportError as exc:
        raise RuntimeError('Optimization is Colab-only; reconnect the existing notebook.') from exc


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def windows_for_track(track, recording_id, group_id):
    """Three past observations predict one later position, at about +1 video s."""
    result = []
    for i in range(2, len(track) - 1):
        past = track[i-2:i+1]
        gaps = [past[k+1]['t'] - past[k]['t'] for k in range(2)]
        if not all(0 < gap <= 1.5 for gap in gaps):
            continue
        future = [p for p in track[i+1:] if .75 <= p['t'] - past[-1]['t'] <= 1.25]
        if not future:
            continue
        target = min(future, key=lambda p: abs(p['t'] - past[-1]['t'] - 1))
        horizon = target['t'] - past[-1]['t']
        points = [[p['xy'][k] / SIZE[k] for k in range(2)] for p in past]
        velocities = [[(points[j+1][k]-points[j][k])/gaps[j] for k in range(2)] for j in range(2)]
        cv = [points[-1][k] + velocities[-1][k]*horizon for k in range(2)]
        target_xy = [target['xy'][k]/SIZE[k] for k in range(2)]
        # The future position is a label only. Future images, events and results
        # never enter these features. The horizon is the requested query time.
        features = points[-1] + velocities[-1] + velocities[0] + gaps + [horizon]
        result.append({'recording_id': recording_id, 'group_id': group_id,
                       'observed_until_video_s': past[-1]['t'], 'target_video_s': target['t'],
                       'features': features, 'cv': cv, 'stationary': points[-1],
                       'target': target_xy,
                       'residual': [target_xy[k]-cv[k] for k in range(2)]})
    return result


def load_windows(dataset):
    selection = json.loads((dataset / 'pilot_selection.json').read_text())
    if not (dataset / 'split_review.json').is_file():
        raise ValueError('Missing split_review.json: visual layout review has not been completed.')
    split_review = json.loads((dataset / 'split_review.json').read_text())
    if split_review.get('status') != 'frozen_after_visual_layout_review':
        raise ValueError('Whole-layout splits must be reviewed and frozen before training.')
    assignments = split_review['recordings']
    output = {'train': [], 'val': [], 'test': []}
    layout_splits, video_splits, opponent_splits = defaultdict(set), defaultdict(set), defaultdict(set)
    provenance = {'pilot_selection_sha256': digest(dataset / 'pilot_selection.json'),
                  'split_review_sha256': digest(dataset / 'split_review.json'), 'labels': {}}
    seen_ids = set()
    for row in selection:
        rid = row['id']
        if rid in seen_ids:
            raise ValueError('Duplicate recording in pilot selection: ' + rid)
        seen_ids.add(rid)
        assignment = assignments[rid]
        split, layout = assignment['split'], assignment['layout_group']
        if split not in output or not isinstance(layout, str) or not layout.strip():
            raise ValueError('Invalid layout/split assignment for ' + rid)
        layout_splits[layout].add(split)
        video_splits[row['video_sha256']].add(split)
        if row.get('opponent_group'):
            opponent_splits[row['opponent_group']].add(split)
        folder = dataset / 'annotation_packets' / rid
        label_path = folder / 'labels.json'
        labels = json.loads(label_path.read_text())
        provenance['labels'][rid] = digest(label_path)
        if (labels.get('recording_id') != rid or labels.get('video_sha256') != row['video_sha256']
                or labels.get('label_status') != 'reviewed'
                or labels.get('coordinates') != 'original_1280x960_screen_pixels'
                or labels.get('camera_review') != 'stable_in_sampled_frames'):
            raise ValueError('Source, label or camera review incomplete for ' + rid)
        tracks = defaultdict(list)
        previous_t = -math.inf
        for frame in labels['frames']:
            t = frame['source_video_ms'] / 1000
            if not finite(t) or t <= previous_t:
                raise ValueError('Non-monotonic frame timestamps for ' + rid)
            previous_t = t
            image_path = folder / frame['image']
            if image_path.parent.resolve() != folder.resolve() or digest(image_path) != frame['sha256']:
                raise ValueError('Frame provenance mismatch for ' + rid)
            if frame.get('review_status') != 'reviewed':
                raise ValueError('Every selected frame needs review: ' + rid)
            present = set()
            for group in frame['troop_groups']:
                gid = group['id']
                if not isinstance(gid, str) or not gid.strip() or gid in present:
                    raise ValueError('Missing or repeated troop-group ID for ' + rid)
                present.add(gid)
                # Occluded/ambiguous observations break a track. They must not
                # be silently bridged as if identity had remained visible.
                if (group.get('review_status') != 'reviewed'
                        or group.get('visibility') != 'clear'
                        or group.get('side') != 'attacker'):
                    tracks[gid].append(None)
                    continue
                xy = group['center_px']
                uncertainty = group.get('uncertainty_px')
                if (not isinstance(xy, list) or len(xy) != 2
                        or not all(finite(v) and 0 <= v < SIZE[k] for k, v in enumerate(xy))
                        or not finite(uncertainty) or not 0 <= uncertainty <= 32):
                    raise ValueError('Invalid position/uncertainty for ' + rid)
                tracks[gid].append({'t': t, 'xy': xy})
            for gid in tracks.keys() - present:
                tracks[gid].append(None)
        for gid, observations in tracks.items():
            segment = []
            for observation in observations + [None]:
                if observation is None:
                    output[split].extend(windows_for_track(segment, rid, gid))
                    segment = []
                else:
                    segment.append(observation)
    if any(len(splits) > 1 for splits in layout_splits.values()):
        raise ValueError('A visual layout occurs in multiple splits.')
    if any(len(splits) > 1 for splits in video_splits.values()):
        raise ValueError('Identical source videos occur in multiple splits.')
    if any(len(splits) > 1 for splits in opponent_splits.values()):
        raise ValueError('A repeated opponent occurs in multiple splits.')
    for split, windows in output.items():
        recording_count = len({w['recording_id'] for w in windows})
        if not windows or recording_count < (3 if split == 'train' else 2):
            raise ValueError('Too few reviewed, continuous tracks in ' + split)
    return output, provenance


def position_errors(predictions, targets):
    return [math.hypot((p[0]-t[0])*SIZE[0], (p[1]-t[1])*SIZE[1])
            for p, t in zip(predictions, targets)]


def run(args):
    require_colab()
    windows, provenance = load_windows(args.dataset)
    if args.out.exists():
        raise ValueError('Use a fresh run output directory.')
    import numpy as np
    import torch
    random.seed(42); np.random.seed(42); torch.manual_seed(42)
    torch.set_num_threads(2)
    x = torch.tensor([w['features'] for w in windows['train']], dtype=torch.float32)
    y = torch.tensor([w['residual'] for w in windows['train']], dtype=torch.float32)
    mean, scale = x.mean(0), x.std(0, unbiased=False).clamp_min(1e-4)
    x = (x-mean)/scale
    model = torch.nn.Sequential(torch.nn.Linear(9, 32), torch.nn.ReLU(),
                                torch.nn.Linear(32, 32), torch.nn.ReLU(), torch.nn.Linear(32, 2))
    torch.nn.init.zeros_(model[-1].weight); torch.nn.init.zeros_(model[-1].bias)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.001)
    args.out.mkdir(parents=True)

    def assess(split):
        records = windows[split]
        features = torch.tensor([w['features'] for w in records], dtype=torch.float32)
        with torch.no_grad():
            residuals = model((features-mean)/scale).tolist()
        target = [w['target'] for w in records]
        predictions = [[w['cv'][k]+r[k] for k in range(2)] for w, r in zip(records, residuals)]
        candidates = {'stationary': [w['stationary'] for w in records],
                      'constant_velocity': [w['cv'] for w in records], 'learned_residual': predictions}
        metrics = {}
        for name, values in candidates.items():
            errors = position_errors(values, target)
            by_recording = defaultdict(list)
            for row, error in zip(records, errors):
                by_recording[row['recording_id']].append(error)
            metrics[name] = {'mean_endpoint_error_px': float(np.mean(errors)),
                             'median_endpoint_error_px': float(np.median(errors)),
                             'per_recording_mean_px': {rid: float(np.mean(v)) for rid, v in by_recording.items()}}
        return metrics

    # Zero residual begins as constant velocity. Validation chooses checkpoints;
    # test metrics are computed only with the explicit final-evaluation flag.
    best = assess('val')['constant_velocity']['mean_endpoint_error_px']
    best_state = copy.deepcopy(model.state_dict()); best_epoch = 0
    started = time.monotonic(); steps = 0; epochs = 0
    for epoch in range(1, 101):
        if time.monotonic()-started >= 60:
            break
        for batch in torch.randperm(len(x)).split(32):
            optimizer.zero_grad()
            loss = torch.nn.functional.smooth_l1_loss(model(x[batch]), y[batch])
            loss.backward(); optimizer.step(); steps += 1
            if time.monotonic()-started >= 60:
                break
        epochs = epoch
        score = assess('val')['learned_residual']['mean_endpoint_error_px']
        if score < best:
            best, best_state, best_epoch = score, copy.deepcopy(model.state_dict()), epoch
    model.load_state_dict(best_state)
    metrics = {'task': 'observed_attacker_group_position_from_position_history',
               'horizon': '0.75-1.25 video seconds, queried at actual sample timestamp',
               'limitations': ['requires supplied tracked positions', 'no base geometry or target model',
                               'future actions unconditioned', 'screen pixels; game speed unverified'],
               'runtime': 'Colab CPU', 'seed': 42, 'optimizer_steps': steps,
               'elapsed_optimizer_seconds': time.monotonic()-started, 'epochs': epochs,
               'selected_epoch': best_epoch, 'provenance': provenance,
               'trainer_sha256': digest(Path(__file__)),
               'windows': {s: len(v) for s, v in windows.items()}, 'validation': assess('val')}
    if args.evaluate_test:
        metrics['test'] = assess('test')
    else:
        metrics['test_status'] = 'not_evaluated'
    torch.save({'model': best_state, 'feature_mean': mean, 'feature_scale': scale,
                'provenance': provenance, 'task': metrics['task']}, args.out / 'checkpoint.pt')
    (args.out / 'metrics.json').write_text(json.dumps(metrics, indent=2)+'\n')
    print(json.dumps(metrics, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--check-only', action='store_true', help='validate labels without optimization')
    parser.add_argument('--evaluate-test', action='store_true', help='final evaluation after fixing model choices')
    args = parser.parse_args()
    if args.check_only:
        windows, _ = load_windows(args.dataset)
        print(json.dumps({s: len(v) for s, v in windows.items()}))
    else:
        if args.out is None:
            parser.error('--out is required for training')
        run(args)


if __name__ == '__main__':
    main()
