# CoC Agent — Competitive AI Research Direction
_Status: planning brief from owner discussion, 2026-11-20. This is a proposed research roadmap, not a claim that the described models have been trained or benchmarks achieved._

## North-star objective

**Build an AI system that can outperform professional Clash of Clans players on competitive attacking**, especially by producing consistently strong three-star attacks on difficult **unseen** base layouts under comparable conditions.

This is **not** a general natural-language prompt-to-goal project like SIMA 2, nor merely an automated resource farmer. The objective is competitive strategic performance. We do not need frontier-scale models or compute if we can demonstrate strong specialist performance with efficient learning and planning.

Clarification still worth obtaining later: whether the final artifact should autonomously execute attacks or produce plans a human executes. Build shared offline strategic components first; do not assume authorization for live competitive automation.

## Where the current repository stands

- Existing README documents an AI-controlled Android/BlueStacks farming system using screenshot/stream observations, a Codex decision-maker, guarded ADB/scrcpy actions, OCR, receipts, and recording.
- README reports 2,107 completed attacks as of 2026-11-08, 1,169 wall upgrades performed by the agent, and ~3.46B tokens across Codex/Claude tooling. These are **repository-reported historical figures**, not an audited competitive benchmark.
- The original farming objective used repeated Valkyrie/Earthquake attacks and a 50% cutoff. Current AGENTS.md supersedes that historical objective: pursue full destruction/three stars, with a planned meta attack; walls are finished and spending should stop.
- Recorded footage, actions, timing, and outcomes are a promising start to a training dataset, but many examples come from a repetitive farming policy. **Do not conflate 2,107 raids with 2,107 diverse, validated expert demonstrations.**
- This repository currently implements a frontier-model-driven orchestration/controller, **not a demonstrated independently trained superhuman model**.
- Preserve existing execution safety, receipts, controller ownership, and provenance; do not silently rewrite historical metrics.

## Competitive definition of success

Compare the AI with professionals using **held-out competitive-style bases** and matched conditions (Town Hall level, available army, troop/hero/equipment levels, spells, deployment rules, and planning/execution time as appropriate).

Primary metric: three-star rate. Supporting metrics:
- destruction percentage and time remaining;
- performance by base archetype, difficulty, and game patch;
- generalization to layouts not seen during model development;
- reliability and variance over repeat trials in an authorized simulator;
- inference latency, compute cost, and human intervention;
- calibration of predicted destruction/three-star probability.

A claim of "beating pros" requires transparent evidence from comparable, independently evaluated matchups or benchmarks, not occasional 100% attacks on random farming opponents. Record sample sizes and uncertainty intervals. Prevent train/test leakage: split by **layout identity/family**, time/patch, and relevant opponents—not by neighboring video frames.

## Research thesis and differentiation

Prior game-AI milestones include AlphaStar (StarCraft II) and OpenAI Five (Dota 2): superhuman results in specialized games with major training infrastructure. SIMA 2 is a generalist, instruction/goal-conditioned agent across virtual worlds; it is not *just* prompting, because it also uses trained behavior and learning from experience.

Potential differentiation for this project, **to be validated rather than asserted**:
1. Compact specialist vision/action policy rather than a frontier LLM reasoning through every click.
2. High-quality learning from real recorded experiences, professional replays where permitted, and failures.
3. A learned model of troops, defenses, targeting, timing, and consequences of deployments.
4. Search/planning over candidate attacks to maximize three-star likelihood.
5. A reliable and reproducible evaluation stack with constrained compute.
6. Transferable visual-agent infrastructure and offline benchmarks, even if a full game-playing agent is not ultimately feasible.

Teacher–student distillation, imitation learning, and world-model planning are existing ideas; novelty must come from a convincingly demonstrated method, dataset, system, or evaluation result.

## Proposed architecture (research target, not implemented)

1. **Base perception:** parse building positions, defensive types/levels, compartments, deployment boundaries, and uncertainty from screenshots or authorized replay images.
2. **Dynamics / world model:** predict troop movement, targeting, damage evolution, spell effects, and future outcomes conditioned on state and actions.
3. **Strategic planner:** evaluate army composition, funnel formation, push routes, deployment points, spell/hero ability timing, and contingency policies. Compare multiple candidates using simulation or an approximate learned dynamics model.
4. **Execution policy:** turn a plan into precise, timed action sequences and adapt to observed changes.
5. **Outcome and learning:** save ground-truth actions/results, compare prediction versus outcome, and train/evaluate on separated data.

A simplified flow:
`visual base -> structured state -> world-model rollouts -> strategy search -> action policy -> outcome verification -> dataset`

## Staged roadmap for Codex

### Stage 0 — Inventory and feasibility audit (start here)
- Inspect current repo files, test suite, footage/event schemas, and data-shipper paths. Don't assume archived video/traces are available locally or in GitHub.
- Report current capabilities versus missing pieces for competitive attack planning, and summarize existing AGENTS.md priorities without changing them.
- Audit data integrity: valid decodable videos, timestamp synchronization between frames and actions, result labels, duplicate raids, strategic diversity, and patch metadata.
- Identify available research compute and access to authorized replays/simulation, if known. Otherwise explicitly list unknowns.
- Produce a small, feasible milestone plan with dependencies, evaluation protocol, and resource estimates. Do **not** launch massive training by default.

### Stage 1 — Establish honest baselines and dataset
- Define a versioned standardized schema: layout ID/metadata, observation sequence, action/event sequence, army/equipment, result, provenance, patch/version, consent/rights where applicable.
- Create deterministic validation and quality reports; don't overwrite raw source data.
- Train/test splits must segregate distinct base layouts and near duplicates.
- Baselines: scripted/ring deployment, current Codex policy (only where legitimately measurable), simple heuristic strategy, and expert demonstrations when available.
- Build a reproducible **offline** evaluation harness and clear metrics.

### Stage 2 — Start with tractable learned components
- First project: parse bases and predict short-horizon troop trajectories/target selection from replay frames.
- Evaluate on unseen layouts against simple physical/heuristic baselines, with uncertainty.
- Second project: behavior cloning of deployment decisions from **diverse, quality-controlled** demonstrations; compare against a scripted strategy.
- Prefer small model experiments over unbounded frontier-model token usage.

### Stage 3 — Planning and stronger training
- Develop an approximate simulator/world model (troop movement, targeting, defenses, spells, hero abilities) and quantify simulator-to-reality discrepancy.
- Search/optimize candidate plans in that simulator; add offline RL or other policy improvement only when baselines and evaluation are trustworthy.
- Explore held-out meta bases, adaptation to patch changes, and performance under fixed resources.
- Study failure modes: perception errors, wrong targeting predictions, bad funnels, timing mistakes, and distribution shift.

### Stage 4 — Human/pro-level comparison
- Curate an authorized, held-out professional-level benchmark with matched attack configurations.
- Evaluate three-star rate, destruction, speed, variability, and statistical uncertainty.
- Use replay analysis or explicitly permitted test environments, not unauthorized bot participation in ranked or tournament play.
- Publish results and limitations, including failures and reproducibility details.

## Immediate next deliverables

Codex should begin **with a read-only audit and a proposed implementation plan**, not by changing live match automation.

Suggested output:
1. `docs/competitive_ai_inventory.md`: code and data inventory; current versus missing capabilities; what can be verified.
2. `docs/competitive_ai_experiment_plan.md`: first experiments, datasets, baselines, metrics, splits, compute budget, risks and acceptance criteria.
3. A recommendation for the **smallest useful experiment**, likely offline troop-trajectory prediction using a handful of validated recordings, with a simple baseline.
4. Only after review: bounded code and unit tests for offline parsers, dataset validation, or evaluation.

Do not claim success or create invented performance numbers. Keep existing running agents untouched unless separately directed.

## Operational and legal boundaries

Supercell terms prohibit gameplay bots/automation. Treat live-game automation and competitive use as **not authorized by this roadmap**. Use owned/permitted replay footage, offline analysis, original or properly licensed simulators, or an explicitly authorized testing partnership. Respect platform rights, player privacy, and data licenses. Do not build tournament cheating or evasion functionality.

This document describes research direction. It does **not** override existing AGENTS.md operating/safety rules or authorize live actions, spending, matchmaking, or changes to the running watcher.

## Decision point

There are two possible final products:
- **Autonomous competitor:** plans and executes full attacks in an explicitly authorized setting; requires both elite strategy and flawless execution.
- **Expert-level strategist:** generates high-quality attack plans for human execution; permits stronger focus on reasoning, world modeling, and planning.

Both share the same base-perception, simulation, evaluation, and data foundations. The declared north star remains **professional-level or better attacking performance**, with precise scope to be agreed before claiming it.
