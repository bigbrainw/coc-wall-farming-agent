# CoC farming agent rules

Work directly in the current agent. No subagents, delegation, agent harnesses,
enrollment, routing, or planner/builder/reviewer pipelines unless the user
explicitly requests them for the current task.

## Full destruction — user update 2026-11-08 (current objective)

User: "i've update the entire walls and what we need right now is targeting
100 percent on all base." Aim for **100% destruction / three stars on every
ordinary opponent**. The former 50% cutoff and resource-secured/stalled-push
early exits are superseded. Deploy the whole army, all spells, all four heroes
and own siege promptly, then let the battle finish naturally. Never surrender
at 50%, 99% or 100%; record the actual settled outcome even when below target.
Keep first-opponent matchmaking, the current loadout and guarded ring spam;
inspect failures and improve tactics toward full destruction.

Walls are complete according to the user. Stop wall spending and resource-cap
wall triggers. Preserve previous verified counts as historical; do not invent
a live count audit. The cumulative 2,500 attack target remains unchanged.

Restart only the owning watcher at verified home between attacks with
`--stream --auto-return-home --view-jpeg --target-percent 100`. The default is
now 100; a running old watcher still uses 50 and must not be armed. Full mode
observes natural results and cancels queued combat without End/Okay inputs.
All sole-owner, ordinary-only, legal-ground, batch, timer and recording rules
remain in force. This section supersedes conflicting older guidance below.

## Current meta army — user update 2026-11-08

User: "we should just started to get the current meta, and the meta base the
most complicated designed base." Move from the Valkyrie/Earthquake ring spam
to a current three-star meta army, because meta bases are the most complicated
designs and full destruction needs a real meta attack.

- First verify live, in the game: Town Hall level, unlocked troops/spells/
  siege, hero and equipment levels. Do not assume a Town Hall from old notes
  (they mention TH11 through TH19).
- Pick one meta army that those live unlocks support. 2026 community guides
  (community opinion, not official balance data) list, e.g.:
  TH18: Meteor Golem Smash + Super Yeti, Root Rider Valkyries, Queen Charge +
  Meteor Golem, Hydra, Dragons + Totem; TH17: Root Rider + Yeti, Root Rider +
  Electro Titan Smash, Queen Charge Lalo, Blizzard Lalo, Super Bowler smash.
  Sources: blueprintcoc.com/blogs/town-hall-18/best-th18-attack-strategies,
  cocbasemaster.com/guide/th18-attack-strategy,
  cocbasemaster.com/guide/th17-attack-strategy,
  cocbasedrop.com/blog/how-to-3-star-th17-in-war-2026.
- Before training the new army, tell the user the live Town Hall, the chosen
  army, spells, siege and hero equipment. Record the choice here. Until then
  the current loadout stays.
- A meta army needs a planned, staged attack (funnel, main push, hero/spell
  timing). Ring spam does not fit it. Read the base on the scout, plan the
  funnel and push, and keep every legal-ground, batch, sole-owner and
  ordinary-only rule. Ranked matchmaking stays forbidden.

### Own meta base layout

The user also wants our home village switched to a current meta defensive
layout ("Also copy a meta layout", 2026-11-08).

- Choose a current meta layout for the live-verified Town Hall level, from a
  recent base-layout source. Name the source and layout to the user and get
  their OK before applying it.
- Apply it with the game's own layout editor or its official copy-layout link,
  into a spare layout slot first. Check that every building is placed, then
  make it the active home layout. Keep the old layout slot as a fallback.
- No purchases, gems or resource spending for the layout change. Apply it only
  at verified home between attacks, under the sole-controller rules.

## Battle mode — updated 2026-11-02

Ordinary resource farming only. The user explicitly instructed: "do not play
any ranked battle" and "just farm normally". Do not enter ranked matchmaking.

## Hammer Jam strategy — user update 2026-11-03

Use Ace's guide https://www.youtube.com/watch?v=0HvRyRbUc1M and the transcript
provided by the user. Fill the army with regular Valkyries and all spell slots
with Earthquakes (current capacity: 44 Valkyries / 11 Earthquakes). Use the four
current heroes with damage equipment: King Spiky Ball, Queen Giant Arrow,
Warden Fireball, Dragon Duke Rocket Backpack. Use abilities early to clear
buildings; spread legal hero entries and Valkyries along resource-rich edges.
Take the first ordinary opponent without routine loot rerolls. Aim for 50%
destruction and the farming bonus. The user explicitly confirmed "End immediately
at 50%", even if troops or spells remain, and then instructed "deploy everything
at once" / "just spam it". Prepare the whole army/hero/siege/spell deployment and
issue it rapidly in guarded batches, but cancel any remaining deployment and end
as soon as the same-controller watcher detects at least 50%. This explicit cutoff
supersedes the former full-deployment requirement when 50% is reached first;
record remaining inventory honestly without treating it as a deployment failure.
Take readily reachable storages/collectors along the way. Keep legal red-boundary margins,
fresh checks after each <=20-input / 20-second batch, spending restrictions,
single ADB ownership and honest timing. This changes the farming objective;
it introduces no cycle-time gate or efficiency hold.

## Completion priority — updated 2026-10-31

The user instructed: "remove what ever blocked the play i don't care abuot the efficiency".
Completing the cumulative attack target (now 2,500) takes priority. There is no cycle-time
limit, cycle-second-190 deployment stop, forced efficiency exit, speed trial,
compliant streak or efficiency-related execution hold. Record actual elapsed
time and all failures without making timing a condition for continuing play.
This supersedes the former four-minute target and every older timing gate.

This instruction authorizes the current session to take over after the previous
owner's terminal turn was verified. Do not repeatedly ask for the same handoff.
Keep exactly one game-controller owner, the current army, legal deployment,
full-army/all-spell requirements and authorized resource spending.

Native input batches remain capped at 20 inputs / 20 seconds before fresh state
and count checks. These bound actual UI input and prevent issuing clicks into an
unexpected screen; they are not an attack-efficiency target. Retain guards based
on the actual live battle countdown. After ineffective input, inspect fresh state
and continue grounded recovery diagnostics through the active controller.
There is no fixed focus-recovery attempt cap or mandatory manual-only hold.
Observe each attempt before choosing the next; do not replay uncertain batches.
Use `android_farming_batch.md` for the controller and receipt interface
(`native_farming_batch.md` is the former CUA interface, historical).

## Current attack target — updated 2026-11-05 23:45

The user (2026-11-05): "add the total for another 1k". The target is now
**2,500 total completed attacks** (former 1,500 + 1,000), including the
already-counted Clan War attacks. Preserve completed progress (978 at
2026-11-05 23:37); this is a cumulative target. Record the change in the
ledger's `targetHistory`. Keep all current farming, spending and controller
rules. Completion also requires every wall at its live-verified maximum level;
continue beyond 2,500 attacks if needed to finish the walls.
(History: 1,000 → 1,500 on 2026-11-04 → 2,500 on 2026-11-05.)

## Game controller: Android ADB — updated 2026-11-03

The user approved switching ("can you onboard codex?") after live integration
tests on 2026-11-03. The game controller is now the ADB + scrcpy controller
`scripts/android_agent/coc_android.py` on BlueStacks `127.0.0.1:5555`.
Follow `android_farming_batch.md` for setup, commands, batches and checks.

- Do not use native CUA (`mcp__cua_repl`), cmux-CUA or any other input path for
  game input or game screenshots. One backend only: never mix ADB and CUA in a
  session. If the ADB controller fails and cannot be recovered with the steps
  in `android_farming_batch.md`, stop and report; switching back to CUA needs
  the user's direction.
- BlueStacks may stay minimized; ADB control and screenshots work minimized.
- Battle use is new: the first attacks are a supervised trial. Observe after
  every batch and verify counts, screen and red boundary on the fresh frame.

## Controller code update — 2026-11-03 18:03 PST (restart required)

User: "fix it and let the codex know to use new code". `scrcpy_stream.py` and
`coc_android.py` changed at 18:03: a still screen no longer falls back to
`screencap` (it hung 15 s and halted the watcher at raid 571); the stream
proves "no change" from 1.5 s of silence (receipt `staticScreen: true`).
`farming_cutoff.py` also has `record_start`/`record_stop`/`scout_pinch_out`.
A running watcher keeps the code it started with. At the next verified home
between attacks (not armed, no battle), send `{"command":"close"}` to your own
watcher and start it again with `--stream`; then start recording attacks.
Tests: test_scrcpy_stream 9/9 x2 (emulator), test_device_stream 7/7,
test_farming_cutoff 23/23.

## Faster raids — user request 2026-11-05 (restart required)

User: "from battle to attack should only cost 3 click, which we should always
attack the first we find it doesn't matter if we can fight more" and "always
spam valkerie around the base like a circle so it should be much quicker".
`farming_cutoff.py` gained `search_to_scout` (Battle → ordinary Find a Match →
Attack! in one command, each tap on an OCR-verified screen, ranked never
accepted) and `ring_deploy` (all Valkyries round-robin over 6–16 agent-verified
legal anchors around the whole base, in guarded <=20-input steps). Always
attack the first ordinary opponent found. Place Valkyries in a ring around the
base instead of one cluster; the red-boundary rule is unchanged, so every
anchor is read on the current frame with a visible margin. Usage is in
`android_farming_batch.md`, "Fast search and Valkyrie ring". A running watcher
keeps its old code: at the next verified home between attacks, close your own
watcher and restart it with
`--stream --auto-return-home --view-jpeg` (user approved "yes" 2026-11-05: the
watcher saves the settled result and taps Return Home itself; view the
`.view.jpg` copies to keep your context small). Then follow the per-raid flow
in `android_farming_batch.md`. Code updated again 2026-11-05 14:00 (0-Valkyrie
count fix, "Zero Valkyries left"): restart the watcher once more at home with
the same flags. Updated again 2026-11-05 16:05 (Cyrillic x16 badge
fix): restart once more at home with the same flags.
Updated again 2026-11-05 16:20 (recording to the mini, see
`android_farming_batch.md` "Recording to the mini"): same restart, same flags;
record_start / record_stop work again.

## Spam attack — user request 2026-11-07 (restart required)

User: "we should just spam the army when we got an opponants. instead of
reading the layout and the valkerie always got delayed deploy time", "we
always deployed all the heros and after they died we then deploy valkerie",
then "let's try this update". Use `spam_attack` (see
`android_farming_batch.md`, "Spam attack") for every raid: read the red
boundary once on the scout, give 6–16 legal anchors, and the command deploys
siege, heroes, all Valkyries and all Earthquakes together in back-to-back
<=20-input batches. Do not read the layout for a resource side or deploy heroes
first and Valkyries later. This replaces the per-batch inventory count check
with a fresh battle/50% check per batch plus counts before and after the whole
deployment (approved by the user). It supersedes resource-side routing and the
heroes-first opening for these raids. The red-boundary rule, the 50% cutoff,
ordinary-only battles and sole-controller rules are unchanged. Restart the
watcher at the next verified home between attacks with the same flags.
Updated again 2026-11-08 14:35 (spam count re-reads, see `android_farming_batch.md`
"Spam count re-reads"): restart once more at home with the same flags.

## Attack footage recording — user request 2026-11-03

The user wants every attack recorded and stored on Google Drive
(the footage Google account, 5 TB) to train models that play and predict troop paths.

- Run the watcher with the stream: `farming_cutoff.py --stream --out DIR`
  (see `android_farming_batch.md`, "Attack footage recording").
- Each attack: after the verified ordinary scout appears and before any
  deployment, send `{"command":"record_start","raid":"r<N>"}`. After the
  settled result is read, send `{"command":"record_stop","meta":{"opponent":…,
  "percent":…,"stars":…,"loot":…,"bonus":…}}`. `reset`/`close` also stop it.
- Footage goes to `/Volumes/T7/coc/attack-footage/incoming/`; the launchd job
  `com.elijah.coc-footage-upload` (scripts/footage/upload_footage.py, rclone
  remote `coc-gdrive`) uploads complete folders every 2 h and never touches
  the game. Do not delete footage.
- Storage location clarified by the user on 2026-11-05: **T7 is attached to
  the Mac mini**, reached with `ssh mini` over Tailscale. Treat the mini as the
  remote home server for footage, uploads and offline data work. A missing
  `/Volumes/T7` on the laptop is expected; verify the mount and queue on the
  mini before diagnosing a storage outage. See `scripts/footage/MINI_SERVER.md`
  for verified state and uploader migration. Moving T7 does not automatically
  redirect a laptop recorder; preserve sole-controller ownership when adopting
  any recording transport changes.
- Recording must never block or delay play: if `record_start` fails (T7 not
  mounted, stream fallback), note it and continue the attack normally.
- Do not change video settings or the uploader without the user.

## One controller and session — hard rule

- Exactly **one session** may operate or observe the game. The controller holds
  an exclusive lock (`/tmp/coc_android_127.0.0.1_5555.lock`) per process; that
  lock does not span separate CLI calls, so session ownership still comes from
  the user. While another session owns the game, stay filesystem/log-only.
- A handoff requires the user's explicit direction and confirmation that the
  previous controlling session has paused or finished. A home screen or a gap
  between calls does not establish that the previous controller has stopped.
  Without a confirmed handoff, keep the current owner and remain log-only.
- Do not queue, paste, type, or inject prompts into another session to apply
  workflow changes. Do not restart or terminate another controller to take over.
- Passive recorders that read existing files are allowed and do not own inputs.
- Older CUA/cmux instructions in this project are historical for game input.

## Legal deployment ground — hard rule

- Never place troops, initial heroes, or siege in the red no-deployment area or
  on its boundary. Read the actual boundary in the current scout/battle view and
  choose clearly legal ground with a visible margin outside it. Empty ground,
  empty wall compartments, and a nearby resource bank are not proof of legality.
- Ground every funnel, main and cleanup spawn anchor on that current view. Reuse
  a confirmed legal anchor while its camera/layout/boundary remain unchanged;
  do not copy coordinates from another opponent or nudge a rejected point blindly.
  A stored `legal: true` flag without visual evidence is not sufficient.
- Resource-focused attacks must enter from legal ground and move toward the
  bank; do not drop directly onto resources inside the red zone. If the boundary
  is unclear, choose a clearly legal point farther outside it or refresh before
  deploying. Speed targets and full-deployment requirements do not override this.
- After a rejected deployment or unchanged expected count, stop the remaining
  deployment batch and inspect fresh state. Do not spam the point or replay the
  batch. Further deployment needs a newly confirmed legal anchor and counts.
- This restriction concerns spawning units. Spells may target inside the base
  when permitted by the game; hero ability buttons are not spawn points.

## Resource-focused farming on separated layouts

When resources, defenses and empty wall compartments occupy separate areas,
focus the whole attack on the actual gold/elixir resource banks. Choose a legal
entry directly beside the richest reachable bank, funnel toward that bank, and
concentrate the trained army, all four heroes, own siege and support spells on
the resource route. Continue toward another worthwhile resource bank when
reachable. Do not scatter the army across empty wall grids or route it through
a defense-only area for destruction while accessible resources remain.

Identify the resource buildings in the current scout; do not reuse coordinates
or assume every separated base has the same resource location. Clear defenses
and walls as needed to reach or protect the resource push. Preserve the full-army
and all-spell requirements and use 4× as soon as the live control is available.

## Direct wall upgrades

User reminder (2026-11-03): use **both gold and elixir** for wall upgrades.

User update (2026-11-05): **save resources until nearly full, then spend them
on walls together**. Do not upgrade a wall after each raid merely because one
upgrade is affordable. Use about 90% of either gold or elixir storage capacity
as the near-full trigger, grounded in live capacity. At that point do one wall
spending session using both currencies as available, retaining the 200K gold
reserve and all existing spending/level/price/deduction checks. Then resume
farming until the next near-full trigger. This supersedes routine per-raid
wall spending; the full wall completion goal remains unchanged.

When a wall-spending batch is due, click a clearly identified lowest-level wall
directly in the home village. Verify the selected wall's level and displayed
price, select the intended row/group when useful, and upgrade with authorized
gold or elixir. Verify the upgraded level/count and exact balance deduction.
Do not routinely open the Build hub/Buildings & Heroes list to find walls.
Use that list only when a lowest-level wall cannot be identified in the village.
Keep the village view for the next untouched wall row and currency batch rather
than reopening the hub or repeating a wall audit. Reground after camera changes;
do not reuse stale coordinates or upgrade the wrong wall tier.

Use `strategy_gate.md` for combat and `battle_cycle_runbook.md` for the adopted
home transition. These hard controller rules supersede conflicting older notes.

## Full wall completion — confirmed 2026-11-03, target updated 2026-11-05

The user answered **"Yes, max every wall"** when asked whether wall farming
should continue beyond the attack target if necessary. With the additional
1,000 attacks requested on 2026-11-05, completion requires **at least 2,500
cumulative completed attacks AND every wall at its maximum level, verified
in the live game**. Continue ordinary resource farming and authorized gold
and elixir upgrades of the lowest-level walls until both requirements are
met. Preserve all battle, 50% cutoff, legal deployment, spending and
sole-controller rules.
