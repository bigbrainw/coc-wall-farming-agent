# Android ADB farming controller — runbook (2026-11-03)

## Current objective: full destruction — 2026-11-08

Target 100% / three stars on every first ordinary opponent. The user reports
all walls upgraded: stop wall spending. The 2,500 cumulative attack target is
unchanged. This section supersedes the historical 50% instructions below.

At verified home between battles, close only the owning watcher, verify its
exit, then restart with `--stream --auto-return-home --view-jpeg --target-percent 100`.
100 is also the new default. Existing processes keep their previous behavior;
never arm an old 50% watcher for the new objective.

Use the same guarded `spam_attack` with current legal anchors and complete
inventory. It now checks battle identity and damage between bounded batches
without surrendering at 50%, 99%, or 100%. Deploy all troops, four heroes, own
siege, all spells and abilities; verify hero spawns separately from zero troop
badges. Let the battle end naturally. No early exit for secured loot or a
stalled push. Use 4× when its live control appears.

On a verified natural result, monitoring disarms, queued combat is cancelled,
and `cutoff.completionReason` is `natural_result` (the legacy field name is
retained for receipt compatibility). With auto-return enabled it saves the
settled result and returns once. If bonus animation outlasts settling, inspect
the frame and retry `{"command":"return_home_after_result"}`; the retry is
refused after a Return input has already been issued. Save the actual outcome,
loot, inventory, timing and footage. A result below 100% remains a completed
attack, not a successful triple. Do not fabricate a 50% cutoff authorization.

The game controller is `scripts/android_agent/coc_android.py`: it takes screenshots
over ADB and sends input through a scrcpy-server control socket (no root, real
multi-touch). It replaces native CUA for the game (see AGENTS.md). All AGENTS.md
rules still apply: ordinary farming only (never ranked), legal deployment ground,
full army and all spells, ≤20 inputs / 20 s per batch, observe before each batch.

## Setup (once per BlueStacks start)

```sh
adb connect 127.0.0.1:5555          # BlueStacks Air, local ADB enabled in its settings
export COC_ANDROID_SERIAL=127.0.0.1:5555 COC_ANDROID_ALLOW_LIVE=1
C=/Users/elijah/program/coc/scripts/android_agent
python3 $C/coc_android.py info      # expect size [1280, 960], input scrcpy
```

If CoC is not in front: `adb -s 127.0.0.1:5555 shell monkey -p com.supercell.clashofclans -c android.intent.category.LAUNCHER 1`.
BlueStacks may be minimized. Screen is 1280x960 landscape; all points use that space.

## Commands

### Stream reader (integrated, opt-in) — updated 2026-11-03

`farming_cutoff.py --stream` serves every observation (polls, post-batch frames,
`observe`) from a scrcpy video stream in the same process. Default is off.

- Freshness is proven per frame: each frame carries its device capture time
  (H.264 PTS), and only a frame captured after the request (+50 ms) is used.
  The emulator showed the stream can lag up to ~1 s, so "newest frame" alone is
  never trusted.
- Still screen (no frames for 0.6 s): the stream waits up to 1.5 s; if no
  packet arrives, nothing changed and the newest frame is used (receipt
  `staticScreen: true`). Screencap is used only if frames arrive but none is
  fresh, or no fresh frame comes within 1.2 s (`streamSkipped`). Raid 571's
  halt was a screencap fallback hanging 15 s on a still screen (2026-11-03).
- Receipts with `"source": "scrcpy-stream"` came from the stream.
- Emulator: `test_scrcpy_stream.py` 8/8 twice (10/10 changes fresh, 0 stale);
  watcher observe ~100-150 ms vs ~300 ms screencap. Needs vendored PyAV in
  `scripts/android_agent/_vendor` (cv2 and PyAV both bundle libavdevice;
  macOS prints an objc duplicate-class warning at start, harmless unless
  camera capture is used).
- Not yet verified in a live CoC battle. First live raid with `--stream` is a
  supervised trial: verify each post-batch frame as usual.
- `test_scrcpy_stream.py` changes Settings/Home: never run it on BlueStacks.

The updated0.6s window was used in a supervised ordinary battle (raid567):
247/291polls came from the stream, median686ms versus1544ms for screencap.
The game disconnected at47%;no cutoff success is claimed for that trial.
See `decision_traces/adb-farming-20261103/stream-codex-trial/trial-report.json`.
Afterward the watcher was fixed to OCR the center dialog area on every poll:
a disconnect can leave the battle header and damage readable underneath.
The saved disconnect frame and28targeted tests passed before resuming play.

### Attack footage recording — added 2026-11-03

With `--stream`, the watcher can record each attack for model training
(user: store attack footage on Google Drive for training models to play and
predict troop paths).

- `{"command":"record_start","raid":"r567"}` right after the verified scout
  appears (before deployment). It writes
  `/Volumes/T7/coc/attack-footage/incoming/<UTC>-r567/video.mkv` (H.264
  1280x960, ≤15 fps, device timestamps, no re-encode; starts at the latest
  key frame, so up to ~10 s lead-in) and `events.jsonl` (every batch's
  actions/points/issue times, every damage poll, cutoff states).
- `{"command":"record_stop","meta":{"opponent":…,"percent":…,"stars":…,"loot":…}}`
  after the settled result is read. `meta.json` is written last and marks the
  folder complete. `reset` and `close` also stop a running recording.
- `--record-root DIR` overrides the root. Recording errors never stop the
  stream or the battle (`recordError` in meta).
- Upload to Google Drive is a separate passive job reading these folders
  (scripts/footage/); it never touches the game.
- Recording repair (2026-11-03): retain Android's SPS/PPS at every buffered
  keyframe and use PyAV `add_mux_stream` for the pre-encoded packets. The
  original raid571–573 containers fail decoding; preserve them and their
  validation receipts. `python3 -m unittest test_stream_recording` is an
  offline regression check, including a recording started at a later IDR.
  This does not change the Android encoder settings or the uploader.
- `scout_pinch_out` (new): zoom out on a verified scout before deployment;
  refused at home, while armed and after a cutoff.

### Existing screencap controller

| Command | Effect |
|---|---|
| `observe OUT.png` | screenshot (~0.2 s, spikes to ~2 s); JSON has `frameId`, `capturedAtMs`, `size` |
| `tap X Y` | one ~45 ms tap |
| `batch FILE.json OUT.png` | guarded batch of taps, waits 1 s, then observes |
| `pinch out` / `pinch in` | zoom out / in at screen centre |
| `swipe X1 Y1 X2 Y2 MS` | drag; see hazards before using on home |
| `back` | Android Back key; see hazards |

Read the screen type and counts with the advisory reader:

```sh
python3 -c "import sys; sys.path.insert(0,'$C'); from screen_reader import ocr, classify_screen, read_counts
l=list(ocr(['OUT.png']).values())[0]; print(classify_screen(l)); print(read_counts(l))"
```

Screens: `home`, `battle_menu`, `scout`, `battle`, `results`, `replay`, `war_preview`,
`unknown`. Treat `unknown` as "look at the image". Counts are advisory: verified with
no wrong values on stream captures, but they miss badges silently; always confirm
counts on the image before "all deployed" or any spending decision.

## Batch file

```json
{"id": "raid12-main-1",
 "checkpoint": {"frameId": "…", "size": [1280, 960],
   "legalSpawns": [{"point": [212, 640], "evidence": "red boundary at ~x330 on this frame; point 120 px outside, open grass"}]},
 "actions": [
   {"kind": "select", "label": "barbarian slot", "point": [150, 900]},
   {"kind": "spawn",  "label": "barb 1", "point": [212, 640]}]}
```

The controller refuses: reused or missing `id`; more than 20 actions; any `spawn`
whose exact point lacks `legalSpawns` evidence; a checkpoint `size` different from
the screen; any off-screen point (checked before the first input). It stops at
20 s (`stopped: "time_cap"`). The receipt has `issued`, `inputMs`, `elapsedMs` and
the observation; `accepted` is always `null` until you verify the observation image.
`red_zone.py` is advisory only and never replaces reading the boundary yourself.

## Known UI points (1280x960, re-ground on the current frame before use)

- Home: Battle button (95, 900); Build (1185, 900).
- Battle hub (`battle_menu`): left card "Battle / Find a Match" (gold cost, ~240, 655) is
  ordinary farming. The right card "Ranked Battle / Find a Match" (~630, 660) is
  **forbidden**. OCR the frame and confirm the left card's "Battle" label first.
- Build side panel: close X (1245, 35). "Welcome Back" popup: Okay (655, 737).
- Ordinary Attack Log: Home Battle -> scroll button at(146,262) on the left
  ordinary Battle card -> Attack Log at(770,224). Keep the upper Battle tab;
  never use Ranked Battle. Close logs at(1195,152). No replay is needed to
  recover settled damage, stars, base loot and expended troops.
- Quit dialog "Confirm Exit": Cancel (483, 595).

## Hazards found live (2026-11-03)

- **Selected buildings move.** A swipe can register as a tap and select a building;
  the next drag that starts on it moves it (a wall was moved once and restored).
  On home: never swipe while anything is selected (a name/level label and
  Info/Upgrade bar are visible). Prefer pinch for camera changes. In battle,
  dragging does not move buildings.
- **Deselecting:** Back does not deselect. Taps on "empty" ground on this base
  often select a wall. Opening and closing a panel (Build, then X) clears selection.
- **Back key:** closes the Battle hub; does not close the Build panel; on plain home
  it opens "Confirm Exit". Use Back only on screens where it was verified.
- **Reaction delay:** CoC reacts 0.4–0.8 s after a tap. The batch waits 1 s before
  observing (`settleSeconds` in the batch overrides it). Do not judge a tap from a
  frame taken earlier.
- **Unplanned screen:** once, the Battle hub opened between two pinches (not reproduced).
  After every gesture, classify the new frame before the next input.
- The Upgrade bar of a selected wall sits at y≈760–800: keep battle-free home taps
  away from it.

## Live battle verification — 2026-11-03

Ordinary matchmaking, scout, legal deployment, troop/spell counts, all four
damage abilities, own siege, End/confirmation and Return were verified in raids
546–549. Continue inspecting each <=20-input batch during the supervised trial.
Raid548 detected50%, issued End961ms after its frame and settled53%, with11Valkyries
cancelled. Raid549 recovered a compact-header OCR miss, detected50% and settled52%.
The live1x speed button appeared with52seconds remaining in raid549; the queued
speed clicks were cancelled at cutoff, so4x input has not yet been verified.

## Recovery

- `adb devices` shows nothing: `adb connect 127.0.0.1:5555`; if refused, BlueStacks
  ADB setting is off or BlueStacks is not running.
- scrcpy start fails: retry once; else `COC_ANDROID_INPUT=adb` (slower `input tap`,
  no pinch) for navigation only, then report.
- Unexpected screen: stop the batch, observe, classify, then decide one input.

## Immediate 50% cutoff — user approved 2026-11-03

The user confirmed "End immediately at 50%", including with unused troops or
spells, followed by "deploy everything at once" / "just spam it". Prepare rapid
full deployment in <=20-input batches with fresh checks; the cutoff takes
priority if 50% is reached first. This authorized remainder is not a failure.

`scripts/android_agent/farming_cutoff.py` holds the sole Device and lock for its
whole lifetime. It accepts JSON lines on stdin and polls the battle HUD while
armed. Only its main thread observes or inputs; the stdin reader only queues
commands. Do not invoke another Device/CLI while it is running.

```sh
COC_ANDROID_SERIAL=127.0.0.1:5555 COC_ANDROID_ALLOW_LIVE=1 \
  python3 -u scripts/android_agent/farming_cutoff.py --out decision_traces/adb-farming-20261103/cutoff-live
```

Commands: `{"command":"observe"}`, `{"command":"status"}`, and
`{"command":"batch","batch":BATCH}` use the existing guarded batch schema.
On the first combat batch add `"armCutoff":true` beside `batch`. Subsequent
batches get a fresh threshold check before input; after cutoff, further spawn,
spell and ability commands are cancelled. Continue visually verifying each
post-batch frame/count and the unchanged legal boundary during this live trial.

At a confidently read >=50% in the lower-right Overall Damage HUD, it rechecks
the full battle screen, taps End Battle, observes, verifies the actual End
Battle?/Surrender? dialog plus Cancel/Okay, then taps Okay and observes results.
An unknown screen, lost HUD or unverified dialog stops further deployment.
Never replay an uncertain batch. End/confirmation are two bounded input batches.
The percentage can increase during capture/OCR and the game's confirmation;
report detected and settled percentages and measured latency, not an exact50 claim.

It does not return home or start another raid. Read/save the settled result,
Return through this controller, then `{"command":"reset"}` at verified home
before the next attack. `{"command":"disarm"}` stops polling;
`{"command":"close"}` closes the controller and releases its lock.
Use action `kind: "speed"` for the visible battle-speed button. It shares the
fresh HUD and cutoff guards; a queued speed click is cancelled if the battle
ends first. It also refuses while unarmed. Do not use generic `ui` for speed.
Receipts: `damage-polls.jsonl`, immutable cutoff trigger/below50 frames,
`cutoff-*.json`, and `controller-state.json` under `--out`.

If the first post-End frame still shows battle or a loading transition, the
same owner keeps observing in `awaiting_confirmation`, with all deployment
cancelled. It confirms only a freshly verified End Battle dialog. It never
repeats End, or repeats an Okay whose delivery is uncertain. Disconnect, exit
and maintenance overlays halt this recovery. End latency is recorded even
when confirmation needs a later frame.

### Reliable command delivery

The interactive terminal previously truncated large canonical input lines.
Startup now disables ICANON/ECHO and restores terminal settings on exit. The
scrcpy ADB child must use `stdin=DEVNULL`: inherited stdin let it steal later
controller commands, including short commands. Offline tests cover both faults.

Prefer a private FIFO and a matching response for every command:

```sh
mkdir -p TRACE_DIR
mkfifo -m 600 /tmp/coc-cutoff-owner.fifo
exec 3<>/tmp/coc-cutoff-owner.fifo
COC_ANDROID_SERIAL=127.0.0.1:5555 COC_ANDROID_ALLOW_LIVE=1 \
  python3 -u scripts/android_agent/farming_cutoff.py --out TRACE_DIR \
  <&3 >TRACE_DIR/events.jsonl 2>TRACE_DIR/stderr.log
```

Send through `scripts/android_agent/cutoff_command.py --fifo FIFO --events EVENTS`
with one JSON request on stdin, including a unique `id`. This helper only delivers
commands to the already owning process; it never creates a Device. A timeout is
uncertain delivery: inspect existing receipts and obtain a fresh observation;
do not resend an uncertain batch.

On a compact header miss with readable damage and End/Surrender, the watcher
requires full-screen battle classification and no disconnect/exit/maintenance
overlay before continuing. Otherwise it halts deployment. A missing damage value
also cancels a pending deployment batch, while read-only polling continues.
After visually confirming the live screen/counts, `{"command":"resume"}` obtains
a new same-controller frame and checks it before allowing further deployment.
It cannot resume after a cutoff, or while already armed. Keep `reset` for verified
home between attacks. Never clear a live-battle stop by resetting as if at home.

### Consecutive prepared batches — 2026-11-03

Badge reader update — 2026-11-04: quantity prefixes `x`, `×`, and the OCR
lookalike Cyrillic `х` are recognized. Ambiguous Cyrillic digits are never
translated. A missing Valkyrie count gets three thresholded pixel re-reads;
it is recovered only when at least two high-confidence readings agree and no
other readable value conflicts. Missing/conflicting counts still stop the plan.
Offline validation: 35 controller tests passed; 23 agent-labelled saved battle
frames gave 21 exact readings, 2 unknown, 0 wrong. The 37-Valkyrie mismatch was
read as 37, so a prepared expectation of 36 still stops. Report:
`decision_traces/adb-farming-20261103/recorded-wall-farming-v5/badge-recovery-validation-20261104/final-report.json`.
Restart only the owning watcher at verified home to load this change.

After the agent visually verifies all four deployed hero health bars and the own
siege, `deployment_plan` can carry an agent-prepared list of up to five existing
batches. Each remains limited to20inputs/20seconds, retains its actual battle
deadline and current legal spawn evidence, and gets a fresh same-controller HUD
check before and after input. Fixed per-slot Valkyrie/Earthquake badge crops are
read before the plan and after every batch; exact expected counts are mandatory.
A missing, low-confidence or mismatching count stops the remaining plan. The
50%cutoff cancels all subsequent steps. The agent still inspects the final frame
and all-deployed inventory before claiming full deployment. This command never
returns home, searches, spends resources or chooses an entry.

Offline count validation:10correct of11savedADBframes;one11-Valkyrie badge was
low-confidence and returnedunknown, withzero wrong readings. Transport/cutoff/
plan guards passed15offline unit tests. The live trial must verify saved frames.

`home_pinch_out` obtains and classifies a fresh home frame before using the same
Device to pinch out once, then observes. It refuses while a battle is armed.
Rapid taps now have60ms release spacing and200ms after unit selections; the
input time remains inside the existing20second batch limit.

### Scout camera recovery — 2026-11-03

For restoring a changed army between raids, `army_picker_pan` scrolls the
bottom troop/spell picker through the existing sole Device. First visually open
the picker in My Army. Send `start`/`end` within x80..1180, y700..915, horizontally
at least150px apart, with `durationMs`200..2000 (default500). A fresh frame must
show My Army, Saved Recipes and Cookbook without a blocking overlay; the command
refuses while armed or after cutoff. Inspect the returned frame before choosing
units. This is navigation only; it does not select or change the army itself.

If a400ms scout pinch has no visible zoom effect, inspect the next frame;
`scout_pinch_out` accepts `durationMs`200..2000. A1200ms gesture worked live
before raid568 after400ms only selected buildings. `scout_pan` also exists
for a verified, unarmed scout only: `start`/`end` must each lie within
x200..1000,y220..600, and it uses the same Device swipe. It refuses home,
battle, armed or cutoff state. No pan has yet been needed live.32targeted
stream/controller tests passed before the sole owner restarted at home.

With the0.6s stream window, raids568and569 triggered cutoff from stream
frames: detected52/50%,End876/884mslater,settled54/52%. Both retained1V;
the prepared plan safely stopped at an unreadable1badge. Use a19V third
batch (leaving2) and2V final batch to avoid that recurring low-confidence
badge. Do not weaken inventory matching or replay an uncertain batch.

### Disabled Earthquake badge recovery — 2026-11-04 UTC

Raid570stopped after its first prepared batch because the disabled grey x0EQ
badge was not read, despite a correct41V count.23Vultimatelydeployed;
21remained when the45s guard applied.1x appeared and one click directly4x
was verified. Natural result47%,zero stars,no bonus;counted as completed
with failed deployment,not autonomous success.

The count reader now retries only a missing EQ badge on three binarized views
of that same saved frame(thresholds60/70/80). It recovers only0,requiring two
high-confidence agreeing reads and no conflicting value. It never fills a
missing Valkyrie count. Saved-frame validation:10cases,zero wrong readings;
full readings7->8,the actual missing0recovered.34targeted tests passed.
See `decision_traces/adb-farming-20261103/inventory-recovery/report.json`.

## Fast search and Valkyrie ring — user request 2026-11-05

User: "from battle to attack should only cost 3 click ... always attack the first
we find" and "always spam valkerie around the base like a circle so it should be
much quicker". Goal: fewer agent turns per raid (each turn costs 30–50 s).

### `search_to_scout` (one command instead of three turns)
`{"command":"search_to_scout"}` — only from a reset controller at verified home.
It taps Battle → the ordinary (left, non-ranked) Find a Match → My Army Attack!,
and OCR-verifies each screen before each tap. The ranked Find a Match is never
accepted. It waits up to 30 s (`scoutTimeout`) for the scout and returns
`stopped: "scout_reached_agent_verification_required"`, the scout observation and
`armyCounts`. Any other `stopped` value means inputs stopped on that screen:
inspect it. Nothing is deployed and the cutoff is not armed. It can take up to
~50 s, so send it with a client timeout of at least 60 s (not 25 s) and never
resend while one is pending. Then take that first opponent: no Next.

### `ring_deploy` (all Valkyries around the base in one command)
1. On the scout, send `record_start`, then the armed opening batch
   (`armCutoff: true`: heroes, siege and Valkyrie select) as now.
2. On a fresh frame that shows the red zone (Valkyries selected), choose 6–16
   anchors in ring order around the whole base. Each must be on clearly legal
   ground with a visible margin outside the red boundary. Spread them on all
   sides that have legal ground in view.
3. Send:
```json
{"command":"ring_deploy","id":"r<N>-ring","anchors":[[x,y],...],
 "checkpoint":{"frameId":"<boundary frame>","size":[1280,960],
   "legalSpawns":[{"point":[x,y],"evidence":"<visible red-boundary margin for this anchor>"},...]},
 "boundaryCapturedAtMs":<capturedAtMs of the frame you read>,
 "valkyrieSelect":[150,780],"valkyries":<current>,"earthquakes":<current>,
 "deadline":{"seconds":<live>,"capturedAtMs":<ms>,"rate":1}}
```
It spreads every remaining Valkyrie round-robin over the anchors (one per
anchor per lap) in steps of at most 20 inputs, through `deployment_plan`. The
checkpoint must include visual legal-spawn evidence for every anchor; it is
preserved in each generated batch for the Device's deployment guard. The
existing guards still apply: armed battle, deadline, inventory checked after
each step, and stop on 50% or any mismatch. It refuses HUD/troop-bar points,
anchors closer than 30 px, too few anchors, and a boundary frame older than
90 s or taken before the last `scout_pinch_out`/`scout_pan`. It cannot see the
red zone itself: legality is still the agent's reading of the current frame.
An automatic red-zone detector was tried and rejected because it missed part
of the zone.
4. Earthquakes and abilities follow in their usual batch; the 50% cutoff ends
   the battle as before.

Tests: test_search_to_scout 4/4 (real recorded frames + real OCR),
test_farming_cutoff 38/38.

### Auto Return Home and small viewing copies — user approved 2026-11-05
Start the watcher with:
`farming_cutoff.py --stream --auto-return-home --view-jpeg --out DIR`
- `--auto-return-home`: after the verified 50% End → Okay, the watcher waits up
  to 15 s for a settled result (two identical results frames). It saves it as
  `cutoff.settledResult` (`path`, `viewPath`, OCR `text`), then taps the
  OCR-located Return Home once and verifies home. Final `cutoff.status`:
  - `returned_home`: read loot/stars/% from `settledResult`, then send
    `record_stop` with meta, then `search_to_scout`. A verified return counts
    as the reset, so no `reset` is needed.
  - `result_not_settled_agent_return_required` / `return_home_unverified` /
    `return_home_blocked_overlay`: inspect and handle as before.
  Do not send your own Return Home batch: the watcher refuses it
  (`return_home_already_handled_by_watcher`), because that tap would land on
  the village.
- `--view-jpeg`: each saved frame also gets `<frame>.view.jpg` (`viewPath` in
  the observation, about 0.37 MB instead of 2.6 MB). View that copy, not the
  PNG, so your conversation stays small; the PNG remains the record. HUD polls
  are skipped.

Per-raid flow: `search_to_scout` → read scout + `record_start` → armed opening
batch → `ring_deploy` → earthquakes → (watcher: 50% End/Okay/result/Return
Home) → read `settledResult` → `record_stop` → next `search_to_scout`.
Tests: test_search_to_scout 6/6 (real frames), test_device_stream 11/11,
test_farming_cutoff 38/38.

### Zero Valkyries left — fix 2026-11-05
With 0 Valkyries left, the card turns grey and its "x0" badge is unreadable.
That stopped r785's final ring step with `inventory_mismatch_or_unreadable`.
Counts now read 0 only when OCR gives no number, no re-read conflicts, and the
card is a grey empty card: saturation <60, value 45–90, value std ≥15. Recorded
frames: live cards ≥148 saturation, empty ≤29 with value 63–65. Black or blank
frames never pass. Saved as `valkyrieCardSaturation` in each inventory record.
Replay over 46 recorded inventory frames: no known count changed; 2 unreadable
zeros → 0. Tests: test_search_to_scout 8/8, test_farming_cutoff 38/38,
test_device_stream 11/11. Needs a watcher restart (same flags).

### Spectators on live attacks — fix 2026-11-05

A live ordinary opponent can display `Spectators:` even during scouting.
This label alone no longer overrides verified scout/battle/result controls.
Explicit replay labels still take priority. The former classification prevented
the JANDER scout from zooming and arming; no units deployed, End returned home,
and the unused 1,700-gold search was recorded separately. Saved scout/battle
frames now classify correctly; 52 targeted tests passed. Restarted the sole
watcher at verified home with all three existing flags.

## Cyrillic x16 badge — fix 2026-11-05 16:05

Rings r809/r814/r816/r818 stopped with `inventory_mismatch_or_unreadable`
although the card showed x16: macOS OCR returns "ХІБ" (Cyrillic) at full
confidence. `inventory_badges` now adds two more views of the same badge
(inverted threshold 200, 2x-scaled threshold 200), which read Latin "x16" on
every recorded frame. Two agreeing readings are still required; no Cyrillic
digit is translated. Replay of all recorded inventory frames: no known count
changed; unreadable reads became 16/36/0. A running watcher keeps old code:
restart it at verified home with the same flags.

## Recording to the mini — user approved 2026-11-05 16:20 ("yes fix recording to the mini")

T7 is on the Mac mini. The watcher now records to the laptop outbox
`~/coc-footage-outbox/incoming/<id>/` (default `--record-root`) and a
background thread (`footage_shipper.py`, default `--ship-to
mini:/Volumes/T7/coc/attack-footage`) moves each complete folder (meta.json
present) to the mini: rsync over `ssh mini` into the hidden `.transfer/`,
SHA-256 check of every file on both sides, one-step rename into the mini's
`incoming/`, and only then removal of the laptop copy. Failures keep the
laptop copy and retry every 5 minutes; log `~/coc-footage-outbox/ship-log.jsonl`.
record_start refuses (and play continues) if the outbox has under 3 GB free.
The per-raid record_start / record_stop commands are unchanged. Backlog:
`python3 scripts/android_agent/footage_shipper.py --once`.

## Percentage OCR on scenery — fix 2026-11-06

If the composite HUD misses damage, the watcher re-reads two differently
cropped views of the same fixed damage-number region. Recovery requires two
agreeing exact percentages at confidence >=0.95; missing/conflicting reads
still stop deployment. Overlay and battle guards remain active.
Offline validation:42 controller tests passed; saved28% and50% frames read
correctly. Sole watcher90756 closed at verified home after r1116; exit
confirmed. Replacement33932 started with --stream --auto-return-home
--view-jpeg in damage-recovery-resume-r1117.

### Missing compact End button — 2026-11-06

r1303 post-batch HUD read56% but missed End Battle, delaying cutoff until63%. At a verified battle threshold, the watcher now OCR-checks the same full frame and recovers one exact, high-confidence End Battle/Surrender label only inside the live left button panel. Battle classification, overlay refusal and dialog verification remain mandatory. Offline54tests passed (1skipped), including non-battle/overlay guards; the actual56%frame recovered[104,667]. Own PID33932closed and exit verified at home; replacement PID21940started with stream/auto-return-home/view-jpeg before r1304.

## Spam attack — user request 2026-11-07 (restart required)

User (2026-11-07): "we should just spam the army when we got an opponants.
instead of reading the layout and the valkerie always got delayed deploy time"
and "we always deployed all the heros and after they died we then deploy
valkerie", then "let's try this update". Measured on raids 1690–1789: median
147 s per raid; 45 s from search to first troop and 34 s from first troop to
full army. Raid 1790: Valkyries started 47 s after the heroes.

`spam_attack` deploys the **whole army in one command** right after the
boundary read: own siege + 4 heroes (each on a different ring anchor), all
Valkyries round-robin over the same anchors, all Earthquakes on 1..N agent
targets, then the 4 hero abilities. Inputs go out back to back in <=20-input
batches (settle 0.25 s). Each batch still runs the batch command's fresh
battle/50% check before and after it, so 50% cancels everything left and the
watcher ends the battle. The slow inventory count (multi-OCR badge read) runs
only twice: before the first input (must equal the given counts, else no
input) and after the last batch.

Per raid: `search_to_scout` → `record_start` → `scout_pinch_out` → the
one-tap boundary batch (select Valkyries) → read the red boundary **once** and
pick 6–16 legal anchors with visible margin (same rule and `legalSpawns`
evidence as `ring_deploy`; don't spend time picking a resource side) →

```json
{"command":"spam_attack","id":"r<N>-spam",
 "anchors":[[x,y],...], "boundaryCapturedAtMs":<boundary frame capturedAtMs>,
 "checkpoint":{"frameId":"…","size":[1280,960],
               "legalSpawns":[{"point":[x,y],"evidence":"…"}, …every anchor]},
 "slots":{"valkyries":[150,780],"siege":[250,780],"king":[345,780],"queen":[345,900],
          "warden":[430,780],"duke":[430,900],"earthquakes":[530,780]},
 "valkyries":44,"earthquakes":11,"quakeTargets":[[x,y],[x,y],[x,y]],
 "deadline":{"seconds":<live>,"capturedAtMs":<frame>,"rate":1}}
```

Read the slot points from the current bottom bar (omit a hero that is not
available). `abilities:false` skips the ability taps. Do not arm with a
separate opening batch: the first spam batch arms the cutoff itself.

`stopped` values:
- `all_deployed_agent_verification_required` — counts 0/0 at the end.
- `cutoff_or_unexpected_screen` — 50% or another screen; the rest was cancelled.
- `initial_inventory_mismatch_or_unreadable` — no input was issued.
- `final_inventory_mismatch_or_unreadable` — some unit did not land; inspect
  the fresh frame and deploy the rest on a newly confirmed legal anchor. Never
  replay the spam.

Ledger: write raid receipts in a batch after a few raids if that is faster;
keep every field. Tests: test_farming_cutoff 50/50 (SpamAttackTests 5),
test_search_to_scout 9 (1 skipped); start counts read 44/11 on the real
r1790/r1791 boundary frames.

### Red rejection guard — 2026-11-07

`spam_attack` now stops after a fresh red deployment warning, preserving the
armed 50% watcher. The existing HUD OCR call also reads a colour-isolated crop
of the warning at y210–300; no per-batch inventory OCR was added. A warning
returns `deployment_rejected_agent_inspection_required`; inspect fresh counts
and red-boundary ground before any recovery. Do not replay the rejected ring.
Verified on saved r1807 frames (warnings in batches1–3, absent in4) and52
offline tests. Own watcher99794closed at verified home after r1807; temporary
watcher12918closed without any attack. Replacement13514started with stream,
auto-return-home and view-jpeg before r1808.

### Spam count re-reads — fix 2026-11-08 14:35 (restart required)

Raids 2076–2093 lost minutes after nearly every spam: the final frame showed
7 or 11 Earthquakes that settled to 0 a few seconds later, and r2083 refused
to start because the Earthquake badge was unreadable on one frame.
`spam_attack` now re-reads the start counts on up to 3 fresh frames before
refusing (still no input until they match), and after the last batch polls
fresh frames for up to ~6 s until 0/0 (each frame also runs the 50% check).
New receipt fields: `startReads`, `finalReads`. When `stopped` is
`all_deployed_agent_verification_required`, a quick look at the returned frame
is enough; do not run a separate recovery count. Choose anchors with a wider
margin from the red line: red-warning rejections (r2073, r2078, r2082, r2092)
each cost several minutes. Tests: test_farming_cutoff 53/53.
