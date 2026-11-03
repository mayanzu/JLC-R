# Stage B: 24-seed evaluation and sensitivity studies

This directory contains compact evidence and verification scripts for the 24-seed evaluation and follow-up studies (2,664 runs in total across the main comparison, core floor/hold ablations, PADC comparators, September Table Mountain trajectory, winter $q=8$ cadence extension, and 1.32-fold link-layer framing overhead stress). All source-controller code, predeclared conditions and statistical families, study locks, individual metric/validation records, and node energy ledgers are retained.

- `compact_evidence_complete/` and `original_controls_compact/` contain run-level outcomes and each source's fresh coverage and longest observed non-fresh interval, derived from the saved round-level arrays. The SHA-256 of every corresponding raw NPZ array is recorded in `run_metrics.csv`.
- Run `python -B verify_compact.py` and `python -B verify_original_five.py` (or use the top-level `python -B scripts/verify_current.py --work-dir NEW_DIRECTORY`) to verify the archived node ledgers, source/run summaries, the primary paired tests with Holm–Bonferroni adjustment, and the $q=8$ and framing-overhead sensitivity summaries without starting simulations.
- `new_weather/` contains the September 2024 NOAA SURFRAD Table Mountain inputs, quality-control provenance, and processed 15-minute irradiance series.
- `packet_trace_analysis/` contains the nine observational winter packet-path replays and verification script (`verify_packet_trace.py`).
