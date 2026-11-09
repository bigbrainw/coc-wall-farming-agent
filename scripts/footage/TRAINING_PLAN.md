# From attack recordings to three-star decisions

Draft: 2026-11-04. User's final objective: three-star bases. This document plans
offline data work; it does not change the current farming instructions.

Implementation update, 2026-11-05: the user chose movement prediction first.
A source-hashed audit and 20-recording / 252-frame annotation pilot are prepared
on the mini. No optimization has run. See [MOVEMENT_PILOT.md](MOVEMENT_PILOT.md)
for the actual artifacts, checks, label requirements and Colab status.

## What to build first

Build a small perception-and-prediction pilot, then use its predictions to
compare decisions. The useful question is: **given this base, army and action,
what will happen next, and does that improve the chance of a three-star?**

The working loop is:

`frame + army state -> base/troop state -> candidate action -> predicted outcome -> decision`

A direct policy that copies the current recordings would mostly learn the
existing farming strategy and its 50% stop. A learned predictor can help later
decision-making, but only after showing that it beats simple baselines on bases
it has not seen. Perfect simulation or a large video model is not a prerequisite.

## Evidence available now

- Drive inventory checked on 2026-11-04: 4,324,392,487 bytes, 431 files.
- 107 recording folders each have `video.mkv`, `events.jsonl`, `meta.json`
  and `validation.json`. The remaining files include a setup test and two
  result correction/recovery sidecars.
- Recovery update on 2026-11-05: 18 more recordings were uploaded and MD5
  verified. The live Drive recount is now 125 videos, 504 files and
  4,920,168,566 bytes. All 125 recordings are marked uploaded in the mini's index.
- Videos are recorded at 1280x960, with variable frame timing up to 15 fps.
- Events include input batches, issue timestamps, damage readings and cutoff
  events. Metadata can contain results, loot and remaining inventory.
- Sample inspection: r571's validation reports a decode failure despite
  `recordError: null` in its metadata. r676 reports full PyAV decode with 1,653
  frames and monotonic timestamps. This is sample evidence, not a quality audit
  of all recordings. r623's metadata was read; its validation read timed out.
- Update 2026-11-05: T7 is mounted on the Mac mini, accessible through
  `ssh mini` over Tailscale. The laptop's missing local mount is expected.
  Large video processing should run against T7 on the mini or cloud scratch
  storage; see `MINI_SERVER.md` for the storage/upload roles.

## First deliverable: a trustworthy catalog

Extend the existing `dataset_index.py` rather than create a separate competing
recording index. Produce a versioned manifest and a quality report with one row
per recording, covering:

1. Source paths, sizes, hashes, recording ID, raid ID and source schema/version.
2. Video decode status, usable intervals, timestamp continuity and frame count.
   Read the existing validations, record their provenance, and flag unknown or
   failed recordings. Preserve every original, including broken recordings.
3. Parsed events, issued-input counts, clock mapping and alignment confidence.
4. Army, heroes, equipment, remaining inventory, relevant levels and game version
   where known; unknown values remain unknown.
5. Observed outcome and its source, result corrections, disconnects and whether
   the battle ended at the farming cutoff or ran to a natural conclusion.

Keep raw files immutable. Store manifests, labels, clips, frame samples and
model outputs in separate versioned derived folders. Identify duplicates by
content, not filename alone. Keep large derived frame collections temporary;
retain the source PTS and extraction recipe so they can be reproduced.

### Correctness details that matter

- A logged input is an attempted action. Use each batch's `issued` receipt to
  distinguish sent inputs from planned but unissued actions; use visual/count
  evidence to establish game acceptance. The current index can fall back to a
  batch timestamp when `issuedAtMs` is absent, so index entries alone are not
  confirmed deployments.
- `videoStartHostMs` is packet arrival time. Validate alignment against visible
  deployment effects and capture timestamps; retain an uncertainty estimate.
  Existing recordings can contain substantial lead-in before `record_start`.
- Keep wall-clock/video time separate from game time. Verify replay speed from
  the footage or evidence before interpreting a movement horizon in game seconds.
- Normalize coordinates to a stable map view, or attach an explicit camera
  transform. A camera pan or zoom must not become a troop movement label.
- Hero ability buttons, spell targets and troop spawn points have different
  meanings. Track which unit was selected before interpreting a map tap.
- HUD destruction percentage does not identify which building fell. Building
  identity and destruction time need visual evidence.
- Use result correction sidecars with documented provenance. Never silently
  rewrite an original result or confuse cutoff detection with the settled result.

## Pilot: understand and predict a short interval

Select 10-20 usable, distinct bases spanning different entry sides, wall layouts,
resource placement, clutter and hero interactions. Reserve held-out base groups
before annotation. Start with a few hundred selected frames and short clips;
size the next annotation batch from observed errors.

Label the base geometry needed for movement: buildings with stable IDs, walls,
openings and legal spawn boundary. Label troop groups, visible heroes, current
targets where observable, and destroyed buildings. Use group locations or
occupancy maps for dense Valkyrie swarms; individual identities are often
ambiguous. Mark occlusion and uncertainty explicitly.

The first prediction task is:

> Given a short observed clip and known actions up to time t, predict a troop
> group's next target and approximate location over the next few seconds.

Start with video-time horizons and record speed; report game-time horizons only
when speed is verified. Evaluate no-action intervals first, then intervals
conditioned on the actions that actually occurred. Do not use future frames,
future damage readings or final results as input to the predictor.

Compare against constant-velocity motion and an approximate geometry/targeting
baseline. Score target accuracy, position error in map units, uncertainty and
failures around walls, target changes and hero effects. Compare performance
across base types, not only an overall average.

Split by whole base/layout group and recording, never random adjacent frames.
Keep duplicate or visually equivalent layouts in one split. Fit models and
normalization on training data; choose settings on validation data; reserve the
test groups for the final comparison. Many frames from 125 raids are still only
125 recorded runs, with potentially fewer independent layouts.

Proceed when prediction improves meaningfully over the baselines on held-out
bases and label/timing errors no longer dominate. If it does not, inspect the
errors and improve the relevant labels or baseline before scaling training.

## Turn prediction into better decisions

After the pilot, test a small set of candidate deployment positions and timings,
spell placements and hero ability timings. Predict short-term consequences,
choose an action, then reconsider after the next observation. Restrict choices
to known legal actions and record uncertainty for unfamiliar states.

Training on one observed action does not establish what every unchosen action
would have done. Keep early action comparisons near the observed data, collect
targeted examples of uncertain situations, and evaluate candidate policies
offline before proposing any live integration.

Reuse existing recognition or policy work only after checking its artifacts,
labels and performance on these Android recordings. Do not assume older native
screenshots or earlier army strategies transfer unchanged.

## Data needed for the final three-star objective

The current 50% cutoff truncates later combat. These recordings can teach early
movement and deployment effects, but a surrender at 50% does not tell us whether
the army would eventually achieve 100%. Treat that outcome as unobserved for
three-star learning, rather than labeling it an inherent strategic failure.

A later collection phase needs complete battles: successful three-stars and
failures, with army/hero/equipment state, timing and base difficulty recorded.
Include late cleanup, time failures, troops stuck on walls, wrong target choices
and hero survival. Deliberately vary the situations missing from this farming
policy. Current ordinary-farming and 50% cutoff instructions remain in effect
until the user explicitly changes the collection mode.

Evaluate the final policy by three-star rate on previously unseen, comparable
bases, reporting confidence intervals and failure categories. Track results
separately by army, progression level, base family and game version. Broaden the
evaluation set as the policy improves; do not infer universal success from a
small favorable sample.

## Recommended next work

1. Audit all 125 recording folders into a source-bound catalog and quality report.
2. Select the pilot and freeze whole-base train/validation/test assignments.
3. Validate timing and annotate a small movement/target sample.
4. Run simple baselines, then one modest prediction experiment.
5. Use the measured errors to decide the next collection and annotation batch.

Training hardware and run size should be selected after the pilot's usable
example count is known. No training run or collection-policy change is started
by this plan.
