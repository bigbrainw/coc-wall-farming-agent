# CoC wall-farming agent

An AI agent that plays ordinary (non-ranked) resource-farming attacks in an
Android emulator and spends the loot on wall upgrades. It runs unattended for
days, ending each attack at 50% destruction, and records every attack to
build a training dataset.

The run started on 2026-10-25. Its goal was **2,500 completed attacks and
every wall at the maximum level (19)**. The walls were finished on
2026-11-08, after about 2,100 attacks.

## How it works

```
Codex agent (decides)  ──JSON commands──▶  farming_cutoff.py watcher  ──ADB/scrcpy──▶  BlueStacks
       ▲                                         │  (guards, 50% cutoff,
       └──────── receipts + small JPEG views ────┘   OCR, recording)
```

- **Controller:** `scripts/android_agent/coc_android.py` drives BlueStacks
  (`127.0.0.1:5555`) over ADB and scrcpy. It reads frames from the scrcpy
  video stream, so the emulator can stay minimized.
- **Watcher:** `scripts/android_agent/farming_cutoff.py` is one long-running
  process that owns all input. It reads the damage percentage with macOS
  Vision OCR (`vision_ocr.swift`), ends the battle as soon as 50% is reached,
  waits for the result screen to settle, saves it and taps Return Home.
- **Commands:**
  - `search_to_scout` goes Battle → ordinary Find a Match → Attack, checking
    the screen with OCR before each tap. It never enters a ranked battle.
  - `spam_attack` deploys the whole army at once. The siege machine, 4 heroes,
    44 Valkyries (in a ring) and 11 Earthquakes go out in back-to-back batches
    of at most 20 inputs, with a fresh battle/50% check around every batch.
- **Safety rules:**
  - Units are only placed on ground outside the red no-deploy zone, read from
    the current scout frame and with a visible margin.
  - At most 20 inputs or 20 s per batch, then a fresh screen check.
  - Only one controller may run at a time (enforced with a lock file).
  - Troop counts are checked before and after deployment; a failed deployment
    is never retried blindly.
- **Army:** 44 Valkyries, 11 Earthquakes, Barbarian King (Spiky Ball), Archer
  Queen (Giant Arrow), Grand Warden (Fireball), Dragon Duke (Rocket Backpack),
  and a Log Launcher.
- **Wall spending:** gold and elixir are saved until either storage is about
  90% full, then spent on the lowest-level walls, keeping a 200K gold reserve.
  Each upgrade's balance deduction is checked against the screen.
- **Footage:** every attack is recorded (`record_start` / `record_stop`). The
  shipper (`footage_shipper.py`) copies each finished recording to a Mac mini
  over Tailscale and checks it with SHA-256 before deleting the local copy.
  From there it is uploaded to Google Drive as a dataset for troop-path
  prediction (`scripts/footage/`).
- **Ledger:** `fifty-attack-run-2026-10-26.json` holds a receipt for every
  raid: loot, percentage, timings and the evidence frames.

## Results (as of 2026-11-08)

| | |
|---|---|
| Completed attacks | 2,107 (target 2,500) |
| Stars | 2,326 (22 three-star attacks) |
| Loot won | 1.79B gold, 1.90B elixir, 17.4M dark elixir |
| Walls | all 325 at level 19 (max) |

### Wall upgrade cost (level 15 → 19)

Upgrades by the agent, each with a verified balance deduction:

| Upgrade | Walls | Price per wall | Gold | Elixir | Total |
|---|---|---|---|---|---|
| 15 → 16 | 310 | 3.2M | 464.0M | 528.0M | 992.0M |
| 16 → 17 | 287 | 4.0M → 2.5M → 2.1M | 332.6M | 314.0M | 646.6M |
| 17 → 18 | 325 | 2.94M | 449.8M | 505.7M | 955.5M |
| 18 → 19 | 247 | 4.2M → 4.0M | 510.2M | 481.6M | 991.8M |
| **Total by the agent** | **1,169** | | **1,756.6M** | **1,829.3M** | **3,585.9M** |

Wall prices dropped during the run. The player upgraded about 78 walls from
18 → 19 by hand (about 312M), so the full cost of maxing all 325 walls was
**about 3.9B gold + elixir**. A further 15 upgrades of 15 → 16 and 38 of
16 → 17 are not in the ledger; those walls were either already at that level
or upgraded by hand (at most about 150M more).

### Speed

| Version | Median time per raid | Raids per hour | Loot per hour |
|---|---|---|---|
| Layout reading, heroes first, Valkyries after (raids 1690–1789) | 147 s | ~21 | ~33M |
| `spam_attack`, whole army at once (from raid 1803) | 121–127 s | ~22 | ~37M |

The raid at 147 s broke down as follows: 22 s at home, 45 s from search to
first troop, 50 s of fighting and 5 s back to home. About 90 s of every raid
was agent decision time rather than game time.

### AI token usage

| Agent | Input (cached) | New input | Output | Total |
|---|---|---|---|---|
| Codex (game controller, 16 sessions) | 3,194.7M | 74.4M | 8.37M (2.45M reasoning) | 3,277.4M |
| Claude Code (tooling and fixes, 9 sessions) | 175.4M cache reads + 4.8M cache writes | <0.01M | 0.71M | 181.0M |
| **Total** | | | | **about 3.46B** |

That is about 1.56M Codex tokens per attack: roughly 35K new input and 4K
output, with the rest being cached context. About 98% of all input was cache
hits. The agents ran on subscription accounts, so the real cost was
subscription quota rather than per-token billing.

## Running

```bash
# watcher (owns the game input; one instance only)
python3 scripts/android_agent/farming_cutoff.py --stream --auto-return-home --view-jpeg --out <trace-dir>

# tests
cd scripts/android_agent
python3 test_farming_cutoff.py
python3 test_search_to_scout.py
```

The command formats are in `android_farming_batch.md`. The agent rules
(ordinary battles only, the red-zone rule, the 50% cutoff and spending rules)
are in `AGENTS.md`.

## Notes

- This is a personal automation and research project. Automating Clash of
  Clans is against Supercell's Terms of Service and can get the account
  banned; use at your own risk.
- The recorded frames and decision traces (`decision_traces/`) are large and
  are archived off-machine; they are not part of the repository.
