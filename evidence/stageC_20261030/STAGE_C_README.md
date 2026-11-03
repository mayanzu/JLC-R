# Stage C: matched planner controls (study E1) and freshness-window sensitivity (study E3)

Follow-up evaluation on the 24-seed cohort examining matched budget-generation rules (`e1`) and freshness-window deadlines $D \in \{2, 8\}$ (`e3`). All outputs reside in this directory; the Stage B baseline records are hash-verified.

## Study arms

**Study E1 (Matched planner budget controls).** Compares JLC-R against two matched controls that retain cadence, queue priority, paid admission, one-hop holds, demand Guard, bounded recovery, the credit-floor formula, and the stage-2 prefix-credit solver unchanged, varying only the budget generation in `OptimizedSimulator.install_plan`:

| Method | Specification relative to JLC-R |
|---|---|
| `JLC-R` | Full joint listening-credit search with scenario-stress paths (replication arm and timing baseline) |
| `SIMPLE-MATCHED-PLANNER` | Stage-1 listening budget from a one-shot proportional rule on the point forecast; stage-2 prefix-credit solver unchanged |
| `POINT-PLANNER` | Identical planning search and floor feasibility, replacing planning-time scenario stress paths with the point path |

Any credit-floor shortfall under `SIMPLE-MATCHED-PLANNER` is recorded (`joint_floor_violations`, `max_floor_shortfall_j`) while execution proceeds with available credit.

**Study E3 (Freshness-window sensitivity).** Evaluates `JLC-R` and `SIMPLE-MATCHED-PLANNER` at freshness deadlines $D \in \{2, 8\}$ (`sim.c['deadline_rounds']`) while keeping the demand period $T_L=4$ and cadence rule $q \in \{1,2,4\}$ fixed across the four weather trajectories at supply 1.0 over 24 seeds (14 days per run).

## Workflow

1. `prepare_stage_c.py` generates `protocol_predefined.json`.
2. `lock_stage_c.py` records runner and protocol SHA-256 digests in `study_lock.json`.
3. `run_stage_c.py --phase confirmation --group e1|e3` executes the cases.
4. `analyze_stage_c.py` pairs against Stage B outcomes and writes `analysis_complete/stage_c_summary.json` and `stage_c_tables.md`.
