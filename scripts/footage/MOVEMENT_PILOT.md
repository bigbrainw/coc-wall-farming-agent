# Movement prediction pilot

Status: prepared on 2026-11-05; **no optimizer has run and no checkpoint exists**.
The user selected movement prediction as the first step toward a three-star
agent. This work does not operate the game or change farming/recording rules.

## Prepared data

The authoritative packet directory is on the Mac mini's T7:

```
/Volumes/T7/coc/attack-footage/derived/movement-pilot-20261105-v2
```

Use `ssh mini`; the laptop is a client and does not have this mount. Original
recordings remain untouched. `v1` is an incomplete extraction attempt; use `v2`.

The snapshot at 2026-11-06 05:03 UTC contains:

| Item | Count |
| --- | ---: |
| Completed recording folders on mini | 216 |
| Uploaded recording folders | 125 |
| New completed folders pending upload/validation | 91 |
| Recordings with passing saved video validation | 120 (403.5 minutes) |
| Failed saved validation | 5 |
| Pilot recordings | 20 |
| Provisional train / validation / test | 14 / 3 / 3 |
| Extracted original-resolution frames | 252 |
| Reviewed movement labels | **0** |

The previous Drive inventory was 504 files / 4,920,168,566 bytes. The 91 pending
recordings are not included in that uploaded count. Missing validation is an
unknown status, not a decode failure.

Packet checks independently matched all 252 timestamps against source-video
PTS using ffprobe, checked image SHA-256 and 1280x960 geometry, and found zero
opponent-group or identical-video collisions between provisional splits.
Actual sampling gaps vary, with a maximum of 1.383 video seconds. These are
variable-rate samples, not a synthetic fixed-rate movie.

Local copies of `quality_report.json`, `pilot_selection.json` and
`packet_integrity.json` are under `reports/movement-pilot-20261105/`.
The full source-hashed catalog and images stay on T7.

## First model

`train_movement_pilot.py` prepares a small position-history experiment. Given
three tracked positions, it predicts a group's position approximately one
video second later. A small residual MLP is compared with stationary and
constant-velocity baselines. It uses actual sample times and reports position
error in original screen pixels, including per-recording errors.

This isolates movement forecasting before adding perception and base geometry.
It requires supplied positions; it does not yet locate troops in images, infer
targets, model unchosen actions, or choose deployments. Future action changes
are unconditioned in this initial experiment. Target labels and an
action-conditioned geometry model are subsequent work. Game-second claims
require playback-speed verification.

Optimization remains **Colab-only**, matching the existing training project.
The prepared run uses CPU, up to 100 epochs and a 60-second loop budget; it
does not allocate a GPU, purchase credits or install a background job. Default
execution selects checkpoints on validation and leaves test evaluation off.

The Colab connector was awaiting pairing at the last check. A private pairing
code was copied to the laptop clipboard. Reconnect the existing notebook via
Tools → Command Palette → “Connect to a local Colab MCP server”. Runtime
availability has not been checked and no notebook operation was submitted.

## Annotation and split review still required

Each packet contains an original-size frame sequence, exact source times,
contact sheet, decode log, extraction command and an empty `labels.json`.
An empty `troop_groups` list currently means **unlabeled**, not “no troops”.
Receipts describe sent input; they do not prove game acceptance or unit position.

Contact-sheet review covered r623, r621, r678, r649 and r637, plus a coarse
20-layout overview. The sampled camera appears stationary in those five clips.
Crowded troops, hero effects and ability bursts make identities uncertain.
This review did not establish trajectories or approve labels. All packet review
fields remain pending. No obvious duplicate in a coarse gallery is insufficient
to freeze layout groups.

For each clear attacker troop group or hero, preserve one ID across visible
frames. A reviewed group entry has this structure (coordinates must come from
the actual frame):

```json
{
  "id": "valk-group-01",
  "unit_type": "valkyrie",
  "side": "attacker",
  "center_px": [0, 0],
  "uncertainty_px": 16,
  "visibility": "clear",
  "review_status": "reviewed",
  "target_id": null
}
```

The example coordinates are placeholders, not labels. Use group centers for
dense swarms. Mark partial/occluded observations explicitly and retire IDs at
ambiguous splits, merges or identity changes. Do not interpolate a guessed
trajectory. Unknown unit type or target remains unknown. The initial trainer
only uses clear, reviewed attacker positions with uncertainty at most 32 px;
occlusion or an absent ID breaks a track. Do not label an ability trail or
building health bar as a troop.

Review every selected frame and set its `review_status` to `reviewed`. Only
after actual review, set packet `label_status` to `reviewed` and `camera_review`
to `stable_in_sampled_frames`. A panning/zooming clip needs stabilization and
an explicit transform before this particular trainer can use it.

Complete `split_review.json` with a visually established `layout_group` for
every recording and change its status to `frozen_after_visual_layout_review`.
Equivalent layouts, repeated opponents and identical videos must remain in
one split. Review target trajectories without using held-out examples to choose
features, settings or labels in training examples. The trainer rejects visual
layout and source-video collisions.

## Validation and execution

No training is needed for these checks:

```sh
python3 -m unittest discover -s scripts/footage -p test_movement_pilot.py -v
python3 scripts/footage/train_movement_pilot.py --dataset DATASET --check-only
```

Twelve preparation/data tests pass on both the laptop and mini. They cover invalid validation,
unissued/mismatched receipts, time and coordinate bounds, group separation,
causal features, the constant-velocity baseline, occlusion breaks and leakage
rejection. These are not evidence that an optimizer or a trained model works.

In the connected Colab runtime, after annotation and split checks pass:

```sh
python train_movement_pilot.py --dataset DATASET --out FRESH_RUN_DIRECTORY
```

The script saves a checkpoint and metrics with label, manifest and trainer
hashes. Assess validation errors before deciding whether to scale annotations.
Use `--evaluate-test` only for the final fixed comparison. A run that cannot
beat constant velocity is useful evidence to improve the dataset/model, not
evidence of a successful movement predictor.

Current recordings end at the farming cutoff. They support an early-motion
pilot; they cannot establish whether those attacks would have three-starred.
