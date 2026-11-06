# JLC-R

Joint Listening-Credit and Reservation (JLC-R) coordinates listening capacity, communication credit and source-aware admission in solar-powered multihop sensor networks. This repository contains the minimal runtime dependency closure of the current controller.

- **Implementation:** `JLC-R-SOURCE-SPATIAL-20261106`
- **Public entry:** `code/simulation/jlc_r.py:JLCR`
- **Default admission mode:** `spatial` (topology-weighted source competition)
- **Versioned algorithm snapshot:** [`v2026.11.06-spatial`](https://github.com/mayanzu/JLC-R/tree/v2026.11.06-spatial)

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

The output directory must be new and outside this code package. The runner saves the configuration, input identity and simulation metrics in `run.json`.

Synthetic weather is the default. To supply measured irradiance, pass `--weather path/to/ghi_15min.csv`. The CSV must have a header and nonnegative, finite global horizontal irradiance (GHI, W/m²) in its second column, sampled every 15 minutes. Its length must cover the scenario's warm-up period, evaluated rounds and forecast tail. Measured inputs and saved experimental results are maintained separately from this code package.

Use `python -B run.py --help` for all command-line options.

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

The package contains 30 transitive runtime source modules, a standalone runner, an integrity verifier, execution configuration, dependency declarations, a source manifest, this README, the MIT license and Git byte-preservation settings. All 18 frozen parent modules retain their original bytes; historical identifiers in their filenames identify dependencies required by the current controller.

This package supports algorithm execution. Reproducing the manuscript's numerical tables additionally requires the separately maintained per-seed records and experimental inputs.

## License

[MIT](LICENSE).
