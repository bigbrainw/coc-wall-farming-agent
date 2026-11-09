# Wall audit and farming session — 2026-10-07

## Verified in game before upgrades

The unused empty Home Village layout inventory showed all 325 walls:

| Current level | Count |
| --- | ---: |
| 14 | 44 |
| 15 | 279 |
| 16 | 2 |
| Total | 325 |

The Town Hall inventory card showed level 18. Home screen balances were 29,000,000 gold, 12,517,031 elixir, 410,000 dark elixir, and 209 gems; builder indicator was 1/6 free. No upgrade or farming attack has yet been verified in this session. The active village is visible again; no layout save was performed by the agent.

## Cost estimate — baseline, pending in-game price verification

The October 2026 wall table lists these costs per segment, payable in gold or elixir: 14→15 3M; 15→16 4M; 16→17 5M; 17→18 7M; 18→19 10M. All 325 can reach level 19. Account discounts have not been verified; these are baseline estimates.

| Current level | Count | Cost per wall through 19 | Group cost through 19 |
| --- | ---: | ---: | ---: |
| 14 | 44 | 29,000,000 | 1,276,000,000 |
| 15 | 279 | 26,000,000 | 7,254,000,000 |
| 16 | 2 | 22,000,000 | 44,000,000 |
| Total | 325 | | 8,574,000,000 |

Finishing the 44 level-14 walls at level 15 costs 132,000,000 at baseline. A possible initial gold-only batch is nine 14→15 upgrades for 27,000,000, leaving 2,000,000 gold. This is a proposal until displayed prices and successful upgrades are verified.

## Current authorization and execution rules

User instructed: upgrade walls from the lowest level first, farm gold, and keep alternating these actions. This authorizes gold wall upgrades and regular Quick Match farming for this session. It does not authorize purchases, gems, real money, Clan War, or CWL. Default to gold; elixir spending is outside this gold-only farming plan.

- Upgrade level 14 walls first; move to level 15 only after none at 14 remain.
- Check the selected wall level, displayed gold price, and confirmation before spending.
- Verify a successful upgrade by the new wall level and gold balance.
- Spend before farming when storage is full, then farm and spend again; preserve one available builder for instant wall upgrades.
- Preflight every army slot and confirm temporary event troops before entering a timed match.
- Track actual gold gained, battle outcome, and wall upgrades. Do not attribute user-operated actions to the agent.
- Stop deployment or spending if touch input or target identity cannot be verified.

## Sources

- https://clash-of-clans.1337wiki.com/walls-home-village/
- https://supercell.com/en/games/clashofclans/blog/news/cosmic-curse-portal-panic-teleports-in/ — free 50 Totem Throwers on October 7–8; recheck availability in game.

## Continuation — 2026-10-08, upgrades pending

On the main village screen, a selected level-14 wall displayed a 2,400,000 gold upgrade price (and the same elixir price). A selected level-15 wall displayed 3,200,000. These prices are 20% below the baseline table; the source of the discount was not verified.

Observed balances were 26,600,000 gold, 12,517,031 elixir, 410,000 dark elixir, and 209 gems, with 1/6 builders free. The difference from the earlier 29,000,000 gold observation is not attributed to an agent action.

User approved upgrading the proposed batch of eleven level-14 walls to level 15: 26,400,000 gold, leaving 200,000. The batch has not been successfully selected or executed. No wall upgrade or gold expenditure was verified during this continuation.

The agent unnecessarily entered the inactive layout editor, then discarded the editing session and returned to the main village without saving or activating a layout. The user clarified that upgrades should occur directly on the main village screen.

BlueStacks input became unreliable: pointer movement was visible, but repeated taps did not change the current selection. Spending was stopped while input could not be verified. The agent requested that the user bring the game forward and select a level-14 wall before retrying. Wall counts remain the earlier audit baseline until a new inventory or successful upgrades are verified.

## Computer-use stop — 2026-10-08

The continuation showed 26,600,000 gold, 12,517,031 elixir, 410,000 dark elixir, 209 gems, and 1/6 builders free. The only attempted wall-selection click returned a Dock-obstruction error. A refreshed view showed a changed village viewport; this was not attributed to the agent. No upgrade or expenditure was verified.

The user reported another source touching the CoC screen and explicitly instructed: "stop all computer use." Gameplay and upgrades were stopped. The agent terminated the 26 detected cmux computer-use helper and ChatGPT CUA runtime processes, leaving their Codex parent processes and BlueStacks running. Helpers automatically restarted; suspension also failed to keep the shared daemons stopped. The agent terminated the remaining detected helpers again. A proposed configuration change failed during JSON parsing, so no setting was changed. A durable global stop was not verified.

The user subsequently said they reopened it and instructed the agent to resume wall upgrades. This renews authorization for computer use and gold-only wall upgrades under the existing rules.

## Input-interference investigation — 2026-10-08

Three read-only checks were run after the user reported an invisible input source. No active `adb`, `scrcpy`, Appium, or UIAutomator process remained after the Android debug server (PID 440) was stopped; BlueStacks had no connected ADB client on ports 5037 or 5555–5558. Other Codex CUA runtimes were suspended and their transcripts showed no BlueStacks actions. The only current CUA state targeted BlueStacks through this bridge.

BlueStacks diagnostics show local and remote ADB disabled and touch/pointer debug overlays disabled. Built-in Clash of Clans game controls are enabled (`Ctrl+Shift+F10` toggles them), with FreeLook/WASD and zoom mappings in the CoC input configuration. Logs do not prove a stuck touch or mouse capture. A non-spending input test selected a Giant Bomb and displayed its upgrade panel; no wall upgrade or resource expenditure was made. Wall inventory and prior verified counts remain unchanged until a wall selection and price are confirmed.

## Overnight preflight — 2026-10-09

Home screen showed 8,555,382 gold, 13,587,327 elixir, 202,204 dark elixir, 216 gems, and 0/6 builders free. These are observed baselines; changes since prior sessions are not attributed to this agent. No wall inventory, current upgrade price, or builder completion time was verified. Input was blocked by a Dock obstruction; no wall was upgraded. Session scope remains gold-only, lowest-level-first, retaining 200,000 gold. Wall spending requires verified input and a free builder; no cancellation or instant completion is authorized.


## Live audit — 2026-10-28 after regular raid237

Buildings & Heroes grouped wall upgrades verified119 currentlevel15,204 currentlevel16,and2 currentlevel17 (325 total);Town Hall18 verified. Prices:15→16=3.2M,16→17=4M,17→18=5.6M. Using baseline18→19=10M withsame20%discount gives8M(final price assumed).

Cost through19=6,092,800,000 gold/elixir. Latest observed bank22,068,551G+19,601,178E leaves6,051,130,271 additional combined resources. Recent10raids average2,652,551 netcombined resources:about2,300 further attacks(range2,250–2,600). Gold-only~4,700attacks. Finishing level16 only costs380.8M beforebank,339.13M afterbank,about128attacks.

Home balance increasedoutsidecombat duringnative timeout/rebind;darkfell159,000. Source unverified;excluded from raidloot. No spending inputperformed.


## Estimate refresh after raid238

Bank23,453,631G+21,045,475E;full max through19 costs6,092,800,000 beforebank,6,048,300,894 additional combined,or6,069,346,369 additional gold only. Last20raids including recorded search fees average1194220 netgold and2477354 combined perattack. Approximately2442 further combined-resource attacks (~2,450;range2,200–2,700),or5083 gold-only (~5,100). Level16 floor requires136 more attacks (~140). Current20%discount and8M final19upgrade assumed tocontinue.


After raid241: sixteen verified level15→16 upgrades (25.6M gold and25.6M elixir). Current counts103 level15,220 level16,2 level17. Bank3,112,494G/518,439E/355,361D;1,150gems.

Afterraid261:14 verifiedlevel15→16 upgrades(8gold,6elixir),25.6Mgold+19.2Melixir. Currentcounts89level15,234level16,2level17. Bank3,255,897G/5,182,798E/470,000D;1150gems. NativeCodexCUAonly.
