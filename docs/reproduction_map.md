# 12-seed diagnostic cohort evidence map

This document maps the 12-seed diagnostic cohort files (`results/` and `results/rc2_supplement/`). For the full manuscript evidence map including the 24-seed evaluation, see `current_paper_evidence.md`.

| Analysis item | Saved input | Verification and regeneration |
|---|---|---|
| Five methods across eight conditions | `results/confirmation_480.csv` | `--mode reproduce` generates `condition_means_40.csv` |
| Coverage and Source P5 contrasts | Seed records and `results/statistics/primary_holm8.csv` | `--mode verify` recomputes; `--mode reproduce` writes summary tables |
| Condition-specific contrasts | Seed records and `cell_primary_endpoints_holm64.csv` | Complete 64-test Holm–Bonferroni family recomputed |
| Jain fairness and mean AoI contrasts | Seed records and `fairness_age_holm72.csv` | Complete 72-test secondary family recomputed |
| Sign-flip sensitivity | Seed records and `sign_flip_holm8.csv` | All 4,096 sign patterns recomputed with Holm–Bonferroni adjustment |
| Sampling, delivery, and energy ledgers | Seed records and `node_records_48000.csv.gz` | `--mode verify` checks demand conservation, all 48,000 node balances, and 480 run totals |
| Source tradeoffs and monitoring gaps | `source_degradation_384.csv`, `monitoring_gaps_480.csv` | Per-source coverage change and longest non-fresh interval summaries |
| Conditional sampling ceiling | `results/rc2_supplement/sensing_mask_480.npz` | `scripts/freshness_ceiling.py` verifies source bounds and decomposes $C_{sample}-C_{fresh}$ |
| Multi-metric tradeoff points | `confirmation_480.csv` and `pareto_observed_points_45.csv` | `scripts/pareto_descriptive.py` checks pairwise relations across coverage, sampling, Jain, and energy |
| $2^3$ outer-mechanism factorial | `results/rc2_supplement/factorial_seed_records_768.csv` | `--mode verify` recomputes the 14-test Holm–Bonferroni family and sign-flip sensitivity |
| PADC-AGE comparison | `results/rc2_supplement/paired_seed_records_96.csv` | Paired evaluation of JLC-R against the age-aware PADC baseline |
| Bondville temperature replay | `results/rc2_supplement/temperature_15m_1344.csv` and `seed_task_metrics_144.csv` | Trace-driven cold-state tracking evaluation using measured SURFRAD air temperature |
| Strawberry-field monitoring replay | `data/strawberry/`, `delivery_fresh_age_480.npz`, and `strawberry_seed_window_metrics_1920.csv` | `scripts/strawberry_replay.py` recomputes four 14-day field windows across 480 trajectories |
| LR-WPAN component microcheck | `audit/rc2_supplement/ns3_micro_results.json` and `execution_sources/ns3_lrwpan_micro.cc` | Verified by `--mode verify` against stored SHA-256 digests |
| Frozen execution-source mapping | `audit/frozen_source_mapping.json` and `configs/formal_protocol_original.json` | `--mode verify` checks SHA-256 digests of all 51 mapped source files |
