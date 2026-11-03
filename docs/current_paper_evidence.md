# Evidence map for the JLC-R manuscript

The manuscript reports a primary 24-seed evaluation (Sections 5.1, 5.2, and 5.5) and a complementary 12-seed diagnostic cohort (Sections 5.3 and 5.4) using disjoint network seeds.

| Manuscript item | Evidence and scripts |
|---|---|
| Tables 1–2, controller and inputs | `code/simulation/`, `configs/`, `docs/technical_documentation/technical_documentation.md`, and `docs/external_baseline_audit.md`. |
| Table 3 and Figures 3–4, 24-seed five-method comparison | `evidence/stageB_20261030/original_five_method_analysis/`; source records in `compact_evidence_complete/`, `original_controls_compact/`, and `case_records.zip`. Figure scripts and assets in `evidence/stageB_20261030/figures/`. |
| Table 4, winter spatial summaries | `evidence/stageB_20261030/spatial_24_final/` and `audit_spatial_24seed.py`. |
| Table 5, runtime mechanism counters | `evidence/additional_mechanism_audit/` (96 hash-matched run records, condition summaries, and `audit_mechanism_counts.py`). |
| Figure 5, 12-seed $2^3$ factorial | `results/rc2_supplement/factorial_seed_records_768.csv`, `factorial_primary_holm14.csv`, and `scripts/plot_factorial.py`. |
| Table 6 and Figure 6, 12-seed sampling, fairness, and gaps | `results/confirmation_480.csv`, `results/monitoring_gaps_480.csv`, `results/statistics/`, `scripts/analysis_core.py`, and `scripts/plot_panels.py`. |
| Table 7, core floor/hold ablations and comparators | `evidence/stageB_20261030/descriptive_followup_complete/`, `analysis_complete/`, `signflip_sensitivity_24/`, and `compact_evidence_complete/`. |
| Tables 8–9, matched planners and freshness windows | `evidence/stageC_20261030/analysis_complete/`, `protocol_predefined.json`, `run_stage_c.py`, `case_records.zip`, and `analyze_stage_c.py`. |
| September trajectory, $q=8$, and 1.32-fold framing stress | `evidence/stageB_20261030/new_weather/`, `q8_analysis_complete/`, `overhead_analysis_complete/`, and `packet_trace_analysis/`. |
| ns-3 link-layer fragmentation | `evidence/ns3_fragment/fragment_micro.cc`, `fragment_protocol.json`, `fragment_lock.json`, `fragment_trials_128.csv`, and `summarize_fragment.py`. |
| Temperature, strawberry, and sampling-ceiling analyses | `results/rc2_supplement/`, `data/strawberry/`, `scripts/replay_temperature.py`, `scripts/strawberry_replay.py`, and `scripts/freshness_ceiling.py`. |

The six manuscript figures (`fig1_system` through `fig6_boundaries`, in both PDF and SVG formats) and their build manifest are stored in `evidence/current_paper_figures/`.

## Verification and single-case rerun commands

- `python -B scripts/verify_current.py --work-dir NEW_DIRECTORY` extracts the case archives into a new external directory and verifies all stored records, node energy ledgers, and statistical summaries without launching simulations. Results are written to `verification.json`.
- `python -B scripts/rerun_current_case.py --study STUDY --case-index N --output NEW_DIRECTORY` reruns a single saved case (add `--dry-run` to inspect the configuration without executing). Supported `STUDY` values are `confirmation`, `extra_confirmation`, `new_weather_confirmation`, `q8_confirmation`, `overhead_confirmation`, `original_controls_confirmation`, `e1`, and `e3`.
- To recompile and run the standalone ns-3 3.41 component test (`evidence/ns3_fragment/fragment_micro.cc`), follow `evidence/ns3_fragment/FRAGMENT_README.md`.
