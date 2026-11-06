# JLC-R

Joint Listening-Credit and Reservation (JLC-R) coordinates listening capacity, communication credit and source-aware admission in solar-powered multihop sensor networks. The repository keeps the controller source compact and provides a separate, versioned evidence bundle for reproducing the manuscript comparisons.

- **Implementation:** `JLC-R-SOURCE-SPATIAL-20261106`
- **Public entry:** `code/simulation/jlc_r.py:JLCR`
- **Default admission mode:** `spatial` (topology-weighted source competition)
- **Versioned algorithm snapshot:** [`v2026.11.06-spatial`](https://github.com/mayanzu/JLC-R/tree/v2026.11.06-spatial)
- **Comparison reproduction release:** [`v2026.11.06-reproducible`](https://github.com/mayanzu/JLC-R/releases/tag/v2026.11.06-reproducible)

## Installation

Use Python 3.12. Clone the latest code and install the NumPy and SciPy dependencies:

```shell
git clone --depth 1 https://github.com/mayanzu/JLC-R.git
cd JLC-R
python -m pip install -r requirements.txt
```

## Verification

Check file hashes and the runtime dependency closure:

```shell
python -B verify.py
```

Add a two-round synthetic smoke check of the default controller, resource accounting and credit floor:

```shell
python -B verify.py --smoke
```

Verification ignores Git metadata and Python bytecode caches. The smoke check writes no result files and does not start a full performance experiment. `.gitattributes` preserves source bytes across Git checkouts so that line-ending conversion does not alter the frozen-module hashes.

## Running the controller

Run a 14-day synthetic-weather scenario:

```shell
python -B run.py --seed 1320352547 --days 14 --supply 1.0 --output "../jlc-r-runs/example01"
```

The output directory must be new and outside this code package. The runner saves the configuration, environment versions, source/input identity and simulation metrics in `run.json`. It also saves `arrays.npz` with per-source freshness ages, terminal sample statuses, source distances and longest non-fresh runs. The metrics include far-source coverage and longest-gap source P95, allowing these endpoints to be independently recomputed from the arrays.

Synthetic weather is the default. To supply measured irradiance, pass `--weather path/to/ghi_15min.csv`. The CSV must have a header and nonnegative, finite global horizontal irradiance (GHI, W/m²) in its second column, sampled every 15 minutes. Its length must cover the scenario's warm-up period, evaluated rounds and forecast tail. Measured inputs and saved experimental results are maintained separately from this code package.

Use `python -B run.py --help` for all command-line options.

## Reproducing the manuscript comparisons

Install the pinned numerical-analysis environment, then run:

```shell
python -m pip install -r requirements-comparisons.txt
python -B reproduce_paper.py --mode reproduce --output "../jlcr-comparisons-new"
```

The command downloads the approximately 70 MiB [comparison evidence bundle](https://github.com/mayanzu/JLC-R/releases/download/v2026.11.06-reproducible/jlc-r-comparisons-20261106.zip), checks its SHA-256 and all 2,740 manifest entries, and recomputes the comparison data from the original saved records. The cache defaults to a sibling directory outside this repository; use `--cache` to choose another location. `--output` must be new and outside both the repository and evidence bundle. For offline use, supply the exact release ZIP with `--archive`.

This numerical reproduction does not require LaTeX, plotting fonts or ns-3. It reanalyzes saved network/MAC records and re-executes the small transaction-kernel examples; it does not automatically start hundreds of full-network simulations.

| Evidence | Records and regenerated outputs |
|---|---|
| Final independent comparison and matched ablations | 448 runs, all seven controllers; coverage, Source P5, far coverage, longest-gap P95, recorded energy, paired intervals and all fixed Holm families. `tables/table2_benchmark.csv`, `tables/table3_all_prespecified_contrasts.csv`, `final/analysis/`. |
| Agricultural-state comparisons | Farm and eight-site SCAN replays; 32,256 window/mapping/band rows, usable/open-valve visibility and conditional/common-epoch errors. `tables/table4_agricultural_states.csv`, `field_replay/`. |
| Supporting source-history comparison | 384 runs and its original paired analyses. `support/`. |
| Transaction-duration and development comparisons | 192 retained duration records and 96 retained development records, with reuse provenance preserved. `duration/`, `development/`. |
| Local mechanism and MAC comparisons | Two bottleneck constructions, 80 conditional kernel executions and 6,144 saved ns-3 episodes. `witness/`, `conditional_gain/`, `mac/`. |
| Numerical figure sources | Paired benchmark differences, weather-cell contrasts, source-gap CDF, duration source tables and agricultural seed means. `figure_data/`. |

The generated `receipt.json` confirms agreement with 28 archived reference CSVs at absolute/relative tolerance `1e-10`. Table 3's export includes every prespecified contrast; the manuscript displays a subset. External total-energy entries remain unavailable where the original native records did not report them. These entries are not imputed.

Download and verify the evidence without recomputing tables:

```shell
python -B reproduce_paper.py --mode verify
```

### Rerunning simulations from their original protocols

The evidence bundle includes the exact inputs, protocols and frozen runtime snapshots, including the adapted EADCM and LANTERN implementations. To rerun a saved final-cohort case and compare its full age/sample-status arrays bit for bit:

```shell
python -B reproduce_paper.py --mode rerun --suite final --case-index 0 --output "../jlcr-case0-new"
```

Final cases 0, 4 and 5 are the matched JLC-R, EADCM and LANTERN synthetic cases for the first seed. `--suite support`, `--suite duration` and `--suite development` select the other retained protocols. To explicitly rerun all 448 final cases, replace `--case-index 0` with `--all-cases` and use a new output directory. Full simulation reruns can take many hours; the default table-reproduction command uses the saved original records instead.

The MAC audit reproduces statistics from the saved episodes. Rebuilding and executing the ns-3 component is separate; its C++ source, ns-3 3.41 build commands, protocol and matched RNG runs are included in the bundle. The bundle also retains data attribution and third-party licenses.

## Configuration and admission modes

`config.json` exports the shared execution settings of the current research controller. The controller locks the reserve-budget horizon to three days, the trigger mode to `reference` and the inherited mechanism to `relay_repair`.

The `--source-protection` option selects:

| Mode | Admission rule |
|---|---|
| `spatial` | Topology-weighted incoming-versus-waiting source competition; the default. |
| `unweighted` | The same source competition with every geometric hop weight set to one. |
| `off` | Packet-funded admission without source-opportunity protection. |
| `admission` | Waiting-source protection without incoming-source competition. |
| `headroom` | Unconditional headroom for a waiting sample. |

The public entry also retains the explicit `priority` and `joint` modes.

## Repository contents

The repository contains 30 transitive runtime source modules, a standalone runner, integrity and comparison-reproduction entry points, execution configuration, dependency declarations, source/evidence manifests, this README, the MIT license and Git byte-preservation settings. All 18 frozen parent modules retain their original bytes; historical identifiers in their filenames identify dependencies required by the current controller.

Large scientific records are distributed through the release attachment rather than the source tree. The evidence archive excludes the manuscript PDF and figure artwork.

## License

[MIT](LICENSE).
