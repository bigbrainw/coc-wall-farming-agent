# CoC strategy gate

## Current objective and controller — 2026-11-08

Target **100% destruction / three stars** on every first ordinary opponent.
Never ranked. Use the sole Android ADB + scrcpy watcher described in
`android_farming_batch.md`, with `--target-percent 100`. Deploy the full army,
all spells, four heroes and own siege in guarded ring-spam batches with
current legal-ground evidence. Let each attack finish naturally; no 50%
cutoff, loot-secured exit or stalled-push surrender. Record actual results
and failures. The user reports all walls complete: stop wall spending.
The cumulative target remains 2,500. This section supersedes conflicting
older objective, controller and staged-deployment notes below.

Current target (user update, 2026-11-05): **2,500 total completed attacks**,
including the already-counted Clan War attacks. The user added 1,000 to the former
1,500 target. Preserve existing progress. Completion also requires every wall
at its live-verified maximum level; continue beyond 2,500 attacks if needed.
All other rules remain in force.

Current priority (2026-10-31): **finish the attacks; no efficiency deadline**.
Follow `battle_cycle_runbook.md`. The user removed cycle-time gates, forced timed
exits and efficiency holds. Keep actual battle-countdown guards and all legal,
full-deployment, resource, spending and controller rules.

## Hard rule: one Computer Use controller and session

Use native Codex Computer Use only, with exactly one session operating or
observing the game through Computer Use. No cmux-CUA, alternate controller or
parallel session. While the farming session owns the game, timing/investigation
sessions are log-only. Handoff requires explicit user direction and confirmation
that the previous controller is paused or finished; a home screen alone is not
a handoff. Do not inject prompts into another session. See `AGENTS.md`; these
rules override every historical controller note below.

## Current between-battle workflow — 2026-10-28

The user approved the fast home transition in `battle_cycle_runbook.md` as the
main farming workflow. Use one settled home/balance check, one combined save,
then navigate straight to ordinary search. Reuse the verified army snapshot
while the loadout is unchanged; do not perform a separate army review each raid.
Pass through the mandatory army dialog as navigation. Refresh inventory only
after a loadout change, reset, or visible discrepancy; retain normal battle
grounding, deployment/count checks and all full-army/spending requirements.
Use native Codex Computer Use only. No prompts to another session or added
controller. The measured 28.020 s navigation trial included the army review;
the newly approved omission of that review has not been timed yet.

When wall spending is due, click a clearly identified lowest-level wall directly
in the home village, verify its level/price, and use row/group upgrades as useful.
Keep the village view for the next untouched row and currency batch. Build hub
is a fallback only when the lowest-level walls cannot be identified directly;
do not routinely reopen or scroll it. See `battle_cycle_runbook.md` for the wall
fast path. Preserve all spending and upgrade-verification requirements.

Historical controller notes are archived in `plans/controller_history.pre-four-minute-v2.md`.

Use this gate for every live attack with the current native Codex Computer Use
controller. The game screen is the source of truth. The historical cmux and
90-second full-cycle trials do not authorize a controller or model-setting change.
Use `battle_cycle_runbook.md` for the adopted home transition and retain continuous
timing; all full-deployment and spending rules remain.

## Before deployment

Choose one objective: three stars/destruction or resource farming. Read a fresh
base view and identify the Town Hall, key defensive clusters, defending heroes,
entry edges, open paths, and likely failure route. Do not deploy while any of
those facts are materially unclear.

### Hard rule: no deployment into red ground

For troop, initial hero and siege placements, identify the current red
no-deployment boundary and choose clearly legal ground with a visible margin
outside it. Apply this to both funnel anchors, the main entry and cleanup drops.
Empty wall compartments and the desired resource bank may still be inside the
red zone; approach them from a legal spawn instead of dropping onto them.
Record the legal anchors with the attack card and reuse them only while the
camera, layout and boundary remain unchanged. A `legal: true` label alone is not
visual verification. If uncertain, choose a clearly legal point farther outside
or refresh before deployment. Never guess an offset or repeat a rejected point.
On rejected placement or an unexpected unchanged counter, stop the remaining
batch and reground from fresh state. Spell targets inside the base are allowed
when the game's spell rules permit them; they are not troop spawn points.

### Separated resource/defense layouts

During farming, fully target the resource area. On layouts like the user's
2026-10-28 example with a large empty wall grid and separate building clusters,
identify the actual gold/elixir banks and enter directly beside the richest
reachable resource cluster. Funnel and concentrate the full trained army,
heroes, own siege and spells on that resource route; then pursue another
worthwhile bank if reachable. Avoid splitting troops across empty wall areas or
committing them to a defense-only cluster for destruction while reachable loot
remains. Clear defenses/walls that obstruct or threaten the resource push.
Ground the bank and entry on this scout; never turn the example into a fixed
screen-coordinate or compass-direction rule.

Write one compact attack card before the first troop:

```text
GOAL / ENTRY: objective, clock direction, landmark, and reason
RESOURCE BANK / ROUTE: actual gold/elixir cluster and direct approach during farming
LEGAL SPAWNS: funnel, main and cleanup anchors clearly outside the current red boundary
FUNNEL: exact units and anchors that remove the two side paths
MAIN: exact group, entry order, and route to the Town Hall or targets
SPELLS: each spell, target, and visible trigger
HEROES / SIEGE: lane, order, and ability cues
FULL DEPLOYMENT: all trained troops, all spells, all four heroes and one own siege
CLEANUP: safe early points and release condition
FAILURE: one fallback if the funnel or main route breaks
```

The card must account for the whole verified inventory. The latest user instruction requires full trained army and all spells in every
attack, with no routine reserve. Deploy support promptly on visible active groups
and verify every troop and spell counter reaches zero. Zero counters alone do not
prove a successful attack; verify the settled result and home balances.

## Farming battle speed

Whenever the live battle speed control becomes available during farming, switch
to **4× immediately**. Check for it in the normal battle observations; do not
wait for another deployment stage or add a separate screenshot-polling loop.
If the control cycles through speeds, use its visible current state to advance
to 4× and leave it there; issue ONE click and inspect the next state before
another speed click. Do not click an already active 4× control back to 1×.

There is no cycle-time limit or forced timed exit. After full deployment, end
when the bank is secured or the push stalls, or allow natural completion.
Record actual elapsed time including wall work and recovery.

## Execute in stages

Before a main/support batch, check the absolute battle deadline at the
actual JavaScript call entry, using the most recent observed battle clock and
its receipt timestamp. Require at least 45 seconds remaining. Split the planned
inputs into chunks of at most 20 inputs and 20 seconds of input issuance, leaving
room for observation within the 30-second tool limit. If less remains, issue no input and observe fresh state;
do not let a preplanned batch continue through timeout into result/home/shop
screens. This guard was added after raid281 crossed timeout; raid282 passed it
with 120.137 seconds remaining and verified full deployment.

1. Funneling batch: deploy only the planned side anchors and observe.
2. Main batch: deploy the core group on the confirmed route and observe.
3. Support batch: use spells and hero abilities on visible threats, then observe.
   Timing exception after repeated verified timer failures: when another decision
   round trip would prevent the latest full-army/all-spell instruction, combine
   the carded main and support actions only when they fit one 20-input/20-second chunk after the funnel
   verifies the identical legal spawn. Prewrite every spell target and trigger;
   make no new route or targeting decision inside the batch. Verify all troop
   and spell counters and route immediately afterward. This changes timing only;
   rejected-input and camera/count-mismatch stop rules remain in force.
4. Confirm full deployment: every troop and spell counter is zero; no routine reserves.

After each batch, verify the fresh screenshot, screen identity, camera, troop
counts, spell counts, and route. Stop on rejected input, count mismatch, stale
observation, changed camera, user input, or an unexpected screen. Do not replay
an uncertain batch or invent a new route during the battle.

## Review

Record the first decisive strategic mistake separately from tool failures. For
each clean attack, compare the planned entry, funnel, route, timing, reserve,
and result. Change one tactical rule at a time and keep assisted attacks out of
the autonomous score.
