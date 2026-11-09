#!/usr/bin/env python3
"""Offline checks for pilot eligibility, receipt matching and held-out groups."""
import json
from pathlib import Path
import tempfile
import unittest

from prepare_movement_pilot import inspect_recording, select_pilot
from train_movement_pilot import load_windows, position_errors, windows_for_track


class MovementPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'uploaded/2026-11-04/20261104T030705Z-r574'
        self.folder.mkdir(parents=True)
        (self.folder / 'video.mkv').write_bytes(b'fixture-not-real-video')
        self.meta = {'videoStartHostMs': 1000, 'durationMs': 20000,
                     'size': [1280, 960], 'opponent': 'BASE Owner'}
        self.validation = {'usableVideoVerified': True, 'monotonicPts': True}
        self.events = [{'type': 'batch', 'actions': [
            {'kind': 'spawn', 'label': 'Valk', 'point': [200, 400], 'issuedAtMs': 3000}],
            'issued': [{'label': 'Valk', 'issuedAtMs': 3000}]}]

    def inspect(self):
        for filename, data in [('meta.json', self.meta), ('validation.json', self.validation)]:
            (self.folder / filename).write_text(json.dumps(data))
        (self.folder / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in self.events))
        return inspect_recording(self.root, self.folder)

    def test_validation_failure_excludes_even_with_no_recorder_error(self):
        self.meta['recordError'] = None
        self.validation['usableVideoVerified'] = False
        self.assertEqual(self.inspect()['eligibility'], 'excluded')

    def test_unissued_actions_are_not_anchors(self):
        self.events[0]['issued'] = []
        row = self.inspect()
        self.assertEqual(row['issued_spawns'], [])
        self.assertIsNone(row['pilot_start_ms'])

    def test_mismatched_receipts_are_not_anchors(self):
        self.events[0]['issued'][0]['label'] = 'Queen'
        self.assertEqual(self.inspect()['issued_spawns'], [])

    def test_only_in_range_times_and_screen_points_admitted(self):
        for at, point in [(900, [200, 400]), (21000, [200, 400]),
                          (3000, [-1, 400]), (3000, [1280, 400])]:
            with self.subTest(at=at, point=point):
                self.events[0]['actions'][0].update(issuedAtMs=at, point=point)
                self.events[0]['issued'][0]['issuedAtMs'] = at
                self.assertEqual(self.inspect()['issued_spawns'], [])

    def test_source_time_and_input_acceptance_are_explicit(self):
        row = self.inspect()
        self.assertEqual(row['issued_spawns'][0]['video_ms'], 2000)
        self.assertEqual(row['pilot_start_ms'], 1500)
        self.assertEqual(row['issued_spawns'][0]['acceptance'], 'sent_input_not_visually_verified')
        self.assertFalse(row['training_ready'])
        self.assertEqual(row['movement_labels'], 0)

    def test_same_normalized_opponent_stays_in_same_group(self):
        first = self.inspect()
        self.meta['opponent'] = '  base OWNER  '
        second = self.inspect()
        self.assertEqual(first['opponent_group'], second['opponent_group'])
        self.assertEqual(first['provisional_split'], second['provisional_split'])
        second['id'] = 'duplicate-recording'
        counts = {first['provisional_split']: 2}
        self.assertEqual(len(select_pilot([first, second], counts)), 1)

    def test_failed_recording_cannot_enter_pilot(self):
        row = self.inspect()
        row['eligibility'] = 'excluded'
        self.assertEqual(select_pilot([row], {row['provisional_split']: 1}), [])


class TrajectoryDataTests(unittest.TestCase):
    def test_features_do_not_include_future_position(self):
        track = [{'t': i*.5, 'xy': [100+i*10, 200+i*5]} for i in range(6)]
        first = windows_for_track(track, 'recording', 'group')[0]
        track[4]['xy'] = [500, 600]
        changed = windows_for_track(track, 'recording', 'group')[0]
        self.assertEqual(first['features'], changed['features'])
        self.assertNotEqual(first['target'], changed['target'])
        self.assertEqual(first['observed_until_video_s'], 1.)
        self.assertEqual(first['target_video_s'], 2.)

    def test_constant_velocity_baseline_on_linear_track(self):
        track = [{'t': i*.5, 'xy': [100+i*10, 200+i*5]} for i in range(6)]
        windows = windows_for_track(track, 'recording', 'group')
        errors = position_errors([w['cv'] for w in windows], [w['target'] for w in windows])
        self.assertTrue(all(error < 1e-10 for error in errors))

    def test_large_time_gaps_do_not_form_observed_history(self):
        track = [{'t': t, 'xy': [100, 200]} for t in [0, .5, 5, 6]]
        self.assertEqual(windows_for_track(track, 'recording', 'group'), [])

    def make_dataset(self, base):
        import hashlib
        selection, assignments = [], {}
        for split, count in [('train', 3), ('val', 2), ('test', 2)]:
            for i in range(count):
                rid = f'{split}-{i}'
                selection.append({'id': rid, 'video_sha256': rid})
                assignments[rid] = {'split': split, 'layout_group': rid}
                folder = base / 'annotation_packets' / rid
                folder.mkdir(parents=True)
                frames = []
                for j in range(6):
                    name = f'{j}.jpg'
                    (folder / name).write_bytes(f'{rid}-{j}'.encode())
                    frames.append({'image': name, 'sha256': hashlib.sha256((folder/name).read_bytes()).hexdigest(),
                                   'source_video_ms': j*500, 'review_status': 'reviewed',
                                   'troop_groups': [{'id': 'g', 'center_px': [100+j*10, 200],
                                                     'side': 'attacker', 'visibility': 'clear',
                                                     'uncertainty_px': 10, 'review_status': 'reviewed'}]})
                labels = {'recording_id': rid, 'video_sha256': rid, 'label_status': 'reviewed',
                          'camera_review': 'stable_in_sampled_frames',
                          'coordinates': 'original_1280x960_screen_pixels', 'frames': frames}
                (folder/'labels.json').write_text(json.dumps(labels))
        (base/'pilot_selection.json').write_text(json.dumps(selection))
        (base/'split_review.json').write_text(json.dumps({
            'status': 'frozen_after_visual_layout_review', 'recordings': assignments}))
        return assignments

    def test_layout_leak_and_unreviewed_labels_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            assignments = self.make_dataset(base)
            windows, _ = load_windows(base)
            self.assertTrue(all(windows.values()))
            assignments['val-0']['layout_group'] = 'train-0'
            (base/'split_review.json').write_text(json.dumps({
                'status': 'frozen_after_visual_layout_review', 'recordings': assignments}))
            with self.assertRaisesRegex(ValueError, 'multiple splits'):
                load_windows(base)
            labels = base/'annotation_packets/train-0/labels.json'
            value = json.loads(labels.read_text())
            value['label_status'] = 'unlabeled'
            labels.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'review incomplete'):
                load_windows(base)

    def test_occlusion_breaks_continuity(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            self.make_dataset(base)
            labels = base/'annotation_packets/train-0/labels.json'
            value = json.loads(labels.read_text())
            value['frames'][2]['troop_groups'][0]['visibility'] = 'occluded'
            labels.write_text(json.dumps(value))
            # No remaining contiguous segment in this recording has 3 past
            # observations plus a future target. It cannot pass the 3-base gate.
            with self.assertRaisesRegex(ValueError, 'Too few.*train'):
                load_windows(base)


if __name__ == '__main__':
    unittest.main()
