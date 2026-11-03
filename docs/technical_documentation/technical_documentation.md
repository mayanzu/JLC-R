# JLC-R technical and reproducibility documentation

This document summarizes the simulator architecture, controller modules, baseline adaptations, and verification workflows. Full analytical proofs are provided in [analytical_proofs.md](analytical_proofs.md).

## 1. Implementation architecture and workload

- **Controller entry point**: `code/simulation/jlc_r.py:JLCR` (`horizon_days=3`, `trigger_mode=reference`, `v63_mechanism=relay_repair`), building on `v63_model.py:RelayRepairHYB` with multi-day member activity cadence, demand-triggered Guard protection, and bounded local recovery. Frozen source digests are mapped in `audit/frozen_source_mapping.json`.
- **Network and energy model**: 100 sources in 12 cells over a $300\,\mathrm{m} \times 300\,\mathrm{m}$ field with a boundary sink and 900-s rounds. Each source generates one 4000-bit sample per round with a four-round ($D=4$) expiry and freshness window. Links within 120 m follow the distance-dependent decoding profile. Nodes have a 4 J battery capacity, 3 J initial charge, and 0.15 J communication reserve. The simulator accounts for sensing, synchronization, listening, control requests/responses, data transmission/reception, failed admissions, and retries.
- **Irradiance trajectories**: Synthetic diurnal light plus measured NOAA SURFRAD trajectories (T1 Table Mountain winter, T2 Table Mountain spring, T3 Bondville winter, and the additional September 2024 Table Mountain trajectory) at supply multipliers 1.0 and 0.7.

## 2. Multi-timescale controller behavior

1. **Four-round joint listening-credit planner**: At each $T_L=4$-round boundary, a causal EWMA and four-path residual scenario bank drive two 15-step monotone bisection searches that maximize integer listening capacity subject to the communication credit floor and scenario reserve constraints, then maximize credit at the selected intensity. When prefix margins tighten under active demand, a demand-gated reactive mode applies the PADC duty rule while preserving live battery reserve and hold invariants.
2. **Window-matched activity cadence**: Divides battery above reserve over $N_D=3$ days plus the next-day causal harvest forecast to map the affordable member activity fraction to sampling intervals $q_i \in \{1, 2, 4\}$ rounds (extended to $q_i=8$ in the winter sensitivity study). Cluster heads and nodes holding foreign packets or forwarding commitments remain exempt from intentional sleep.
3. **Charged admission, holds, Guard, and recovery**: Admitted packets establish one-hop forwarding energy and slot commitments, scheduled with committed-first priority and local freshness tie-breaking. Member-to-CH admission enforces static transit headroom and triggers an additional Guard slot threshold when a reference upstream CH signals ready queued traffic. Non-reactive full-prefix CHs may execute at most two paid recovery attempts within existing budgets.

## 3. Baselines and ablations

- **External baselines**: EADCM (`eadcm_policy.py`, `eadcm_host.py`) and LANTERN (`lantern_policy.py`, `rpl_upward.py`, `rpl_trickle.py`, `causal_meter.py`, `router_mac.py`) are reimplemented in the shared physical and transaction ledger; see [external_baseline_audit.md](external_baseline_audit.md).
- **Internal ablations and planner controls**:
  - `JLC-Base` and `JLC-Core`: Progressive baseline variants without outer cadence, demand Guard, or bounded recovery.
  - `No floor`, `No hold`, `Neither floor nor hold`, `Cadence-only`, `No-joint PADC`, and `Simple PADC-cadence`: Evaluated across the 24-seed cohort (Section 5.5, Table 7).
  - `SIMPLE-MATCHED-PLANNER` and `POINT-PLANNER`: Matched budget-generation controls isolating the communication credit floor and scenario-stress paths (Section 5.5, Table 8), plus freshness-window sensitivity across $D \in \{2, 8\}$ (Table 9).

## 4. Verification workflows

- **Full package verification**: `python -B scripts/verify_current.py --work-dir NEW_DIRECTORY` verifies both the 24-seed primary evaluation (`evidence/stageB_20261030/` and `evidence/stageC_20261030/`) and the 12-seed diagnostic cohort (`results/`), checking all file digests, 100-node energy conservation ledgers, demand outcomes, and Holm–Bonferroni statistical families.
- **12-seed diagnostic verification**: `python -B scripts/reproduce.py --mode verify` checks the 463 manifest files, 480 confirmation runs, 768 factorial runs, 96 PADC-AGE pairs, sampling-conditional freshness ceilings (`scripts/freshness_ceiling.py`), Bondville temperature replays (`scripts/replay_temperature.py`), strawberry-field irrigation replays (`scripts/strawberry_replay.py`), and ns-3 component receipts.
