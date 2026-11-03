# JLC-R — Reproducibility Package

This reproducibility repository accompanies the manuscript
"Joint Listening-Credit Planning and Relay Protection for Fresh Data Collection
in Solar-Powered Wireless Sensor Networks." It contains the simulator source
code, configuration files, processed NOAA SURFRAD irradiance inputs, ns-3
link-layer framing scripts, seed-level evaluation records, and verification and
reproduction scripts for both the 24-seed primary evaluation and the 12-seed
diagnostic cohort.

## Quick start

```bash
python -m pip install -r requirements.txt
# Full saved-evidence verification (target directory must not exist and must be outside the package):
python -B scripts/verify_current.py --work-dir /path/to/new-verification-directory
# Inspect or rerun a single 24-seed case (omit --dry-run to execute):
python -B scripts/rerun_current_case.py --study confirmation --case-index 1 --output /path/to/new-rerun --dry-run
```

`verify_current.py` extracts compressed case records into the supplied working
directory and verifies the 12-seed diagnostic cohort, the 24-seed Stage B
ledgers and statistical families, the Stage C 960 planner/deadline records, and
the ns-3 fragmentation records without launching new simulations. See
`docs/current_paper_evidence.md` for the complete evidence map across all
manuscript tables and figures.

## 12-seed diagnostic cohort commands

The commands below operate on the 12-seed diagnostic cohort (`results/`):

```bash
# Read-only verification of hashes, node energy/sample ledgers, outcomes, and paired tests:
python scripts/reproduce.py --mode verify

# Regenerate diagnostic tables, figure assets, statistical families, and 40 condition means:
python scripts/reproduce.py --mode reproduce

# Inspect or explicitly rerun a recorded 12-seed confirmation or factorial case:
python scripts/reproduce.py --mode rerun --study confirmation --dry-run
python scripts/reproduce.py --mode rerun --study confirmation --case-index 0
python scripts/reproduce.py --mode rerun --study factorial --dry-run
python scripts/reproduce.py --mode rerun --study factorial --case-index 0
```

## Package contents

- `code/simulation/` and `configs/`: Complete JLC-R controller (`jlc_r.py:JLCR`), common-environment adaptations of EADCM and LANTERN (`docs/external_baseline_audit.md`), ablation variants, and locked protocol configurations.
- `evidence/stageB_20261030/`: 24-seed primary five-method evaluation, winter spatial decomposition, core credit-floor and hold ablations, PADC comparators, September 2024 Table Mountain trajectory, winter $q=8$ cadence extension, 1.32-fold link-layer framing overhead stress, and winter packet-path replays.
- `evidence/stageC_20261030/`: 24-seed matched budget-generation controls (simple proportional planner and point planner) and freshness-window sensitivity ($D \in \{2, 8\}$).
- `evidence/ns3_fragment/` and `audit/rc2_supplement/`: ns-3 3.41 IEEE 802.15.4 fragmentation (5 × 104-byte MAC payloads) and three-node LR-WPAN component checks.
- `evidence/additional_mechanism_audit/`: Runtime Guard, bounded recovery, and forwarding-hold counter records and audit script.
- `evidence/current_paper_figures/`: Final manuscript figures (`fig1_system` through `fig6_boundaries` in PDF and SVG) and plotting scripts.
- `results/` and `results/rc2_supplement/`: 12-seed diagnostic cohort records (`confirmation_480.csv`, `node_records_48000.csv.gz`), $2^3$ outer-mechanism factorial records (`factorial_seed_records_768.csv`), PADC-AGE comparison, sampling-conditional freshness ceiling masks (`sensing_mask_480.npz`), Bondville air-temperature replay, and strawberry-field soil-moisture/valve replay.
- `data/surfrad/` and `data/strawberry/`: Provenance metadata for processed NOAA SURFRAD irradiance inputs and CC BY 4.0 field-monitoring data from Manzano et al. (2023), Mendeley Data V3, DOI `10.17632/cjb4vy4mzj.3` (see `THIRD_PARTY_NOTICES.md`).
- `docs/`: Evidence maps (`current_paper_evidence.md`, `reproduction_map.md`), analytical proofs (`analytical_proofs.md`), baseline adaptation notes (`external_baseline_audit.md`), data dictionary (`data_dictionary.md`), and technical documentation (`technical_documentation/technical_documentation.md`).
