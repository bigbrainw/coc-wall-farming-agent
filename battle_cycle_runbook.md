# Farming cycle runbook — completion-v3

## Current objective — 2026-11-08

Aim for 100% / three stars on every first ordinary opponent. The user reports
every wall upgraded, so stop wall spending. Preserve the 2,500 cumulative
attack target. Use only the owning Android ADB + scrcpy watcher, restarted at
verified home with `--stream --auto-return-home --view-jpeg --target-percent 100`.
The former 50% cutoff and early exits when resources are secured or the push
stalls are superseded. Deploy everything in guarded ring-spam batches, verify
actual inventory and hero/siege deployment, and let the battle end naturally.
Save settled results, home balances and footage before the next paid search.
This section takes precedence over conflicting historical guidance below;
`android_farming_batch.md` is the current controller/receipt interface.

## Current priority — 2026-10-31

The user removed efficiency requirements and authorized resuming play. Complete
2,500 cumulative attacks, preserving the completed total (target updated
2026-11-05). Also max every wall, verified in the live game; continue beyond
2,500 attacks if needed. There is no maximum
home-to-home duration, cycle-second-190 stop, forced timed exit, efficiency trial
or required streak. Actual elapsed time, unused scouts, wall work and recovery
remain recorded honestly, without preventing the next attack.

Use the sole native Codex CUA controller. Import `scripts/native_farming_batch.mjs`
once in its owning context. Bound each input call to 20 inputs / 20 seconds and
observe actual counts and screen afterward. Keep actual battle-countdown guards,
legal spawn evidence, full trained army, all spells, four heroes and one own
siege. A returned input is not proof that the game accepted it.

An immediate BlueStacks image may precede rendering. On `observation_required`,
keep inputs stopped and obtain a distinct follow-up observation before deciding
whether input failed. Continue grounded recovery after fresh observations; no
fixed recovery-attempt cap or mandatory manual-only hold applies. Reconcile
remaining counts before a new batch; never replay uncertain inputs.

Use 4× when the live control is available. After full deployment, exit when the
resource bank is secured, the push stalls, or the game finishes naturally.
Read the settled result and Return in the same decision turn, then capture
settled home balances and save one complete `cocLedgerRaid` receipt before the
next paid search. End, confirmation and Return each require their current screen.

Save with `python3 scripts/save_emitted_coc_raid.py --receipt RECEIPT.json --raid N`.
Use actual receipt times for `searchStart`, `firstDeploymentIssuedAt`,
`fullDeploymentVerifiedAt`, `resultObservedAt`, `returnIssuedAt` and `homeVerifiedAt`.
Unknown times remain unknown. Failed deployment needs evidence and the writer's
`--allow-failed-deployment`; attack-log recovery needs explicit provenance.

## Standard farming transition — adopted 2026-10-28

The user approved merging the home-navigation trial into the main workflow and
removing routine army rechecks while the farming loadout is unchanged.

1. Read the settled battle result once, retain loot/outcome in memory, and return
   home in the same action turn. Defer the detailed route review.
2. Use one settled home observation for balances and the home-ready timestamp.
   Refresh only when the returned view is still loading or something is unclear;
   do not repeat an already readable, settled balance check.
3. Combine necessary ledger/route-note writes into one save at home and continue
   directly to navigation in that turn. Do not reread reports, preload helpers,
   perform research, or narrate a separate recap between those actions.
4. Handle required, already-authorized wall spending together when due. Click a
   clearly identified lowest-level wall directly in the village; do not open
   the Build hub by default. Preserve all spending/builder restrictions and
   retain that time in operational totals. See the wall fast path below.
5. Open ordinary Battle → Find a Match → Attack using the current grounded UI.
   Reuse the established army snapshot throughout unchanged-loadout farming.
   The game's army dialog still needs its Attack click, but it is navigation,
   not a separate loadout-review task. Do not open Edit Army, recount/relist the
   roster, or add a screenshot solely to recheck an unchanged army.
6. Refresh the inventory snapshot after a loadout change, game/runtime reset,
   or visible discrepancy. Fresh scout grounding and normal deployment/count
   checks remain part of combat, using the observations already needed there.

Use native Codex Computer Use and exactly one owning session, as required by
`AGENTS.md`. An investigation session stays log-only while another session owns
the game. Confirm the previous owner is paused/finished before a user-requested
handoff. Do not send prompts to another session, switch controllers, or add a
parallel executor.
Keep the established full-army, all-spell, four-hero and own-siege requirements.

Measured evidence: `decision_traces/home-search-trial-20261028.json` records
28.020 s from settled home receipt to search action and 34.241 s to the verified
scout receipt. This trial still included an army review, so the effect of skipping
that review is not measured yet. It charged one 1,700-gold search fee, deployed
no troops, and returned home; it is not a completed raid or a ten-run average.
Continue recording actual home/search/scout receipt times, all fees, wall work,
and interruptions with the existing passive recorder.

## Wall-upgrade fast path

1. In the current home view, click a clearly identified lowest-level wall.
   Confirm the selected level and displayed gold/elixir cost in its controls.
2. Use the grounded row/group selection controls when useful. Verify the chosen
   count, tier and total cost before confirming the authorized currency spend.
3. Verify the new level/count and exact resource deduction. Remain in the village
   and select the next untouched lowest-level row for the next currency batch.
   Do not restart the Build hub search or perform another inventory audit.
4. Use Build hub/Buildings & Heroes only if the lowest-level wall cannot be
   identified directly. Once located, return to direct village selection.

Use current wall positions and controls; camera changes invalidate old pixel
coordinates. Do not enter the layout editor or move walls to perform upgrades.

Historical alternate-controller recipes are archived in
`plans/battle_cycle_recipe.cmux-historical.md`; they are not executable current instructions.
