# Third-party notices

## NOAA SURFRAD input

Measured irradiance is derived from the NOAA Global Monitoring Laboratory
Surface Radiation Budget (SURFRAD) network. The bundled processed inputs are
15-minute GHI means with provenance and quality records; the upstream raw
`.dat` files are not bundled. Source URLs, per-file SHA-256 and
transformation steps are retained in:

- `code/results/expansion_measured/weather/provenance.json`
- `code/results/strengthening_weather/T2/quality.json`
- `code/results/strengthening_weather/T3/quality.json`

Upstream sources (checked October 2026) include, for example:

- https://gml.noaa.gov/aftp/data/radiation/surfrad/Boulder_CO/2024/tbl24001.dat
- https://gml.noaa.gov/grad/surfrad/

This project does not assert ownership of the provider's input data or
relicense it under MIT. Use provider data according to its applicable terms
and attribution notices; the software license in this repository covers the
project's own software.

Data/Image provided by NOAA Global Monitoring Laboratory, Boulder, Colorado,
USA (https://gml.noaa.gov).

The bundled 15-minute inputs were processed by the authors and are not official
NOAA processed products. The provider's data-use and attribution conditions are
described at https://gml.noaa.gov/about/disclaimer.html . No NOAA endorsement is
implied.

## Strawberry-farm soil-moisture and valve data

`data/strawberry/D_moisture.txt` and `D_valve.txt` are unmodified files from:
Manzano, Jose Maria; Orihuela, Luis; Tapia Córdoba, Alejandro; Pacheco, Erid;
and Bareiro, Jorge (2023), “Smart irrigation control system data with soil
moisture, flow meter and electrovalve relay”, Mendeley Data, Version 3,
https://doi.org/10.17632/cjb4vy4mzj.3 . They are shared under the Creative
Commons Attribution 4.0 International licence:
https://creativecommons.org/licenses/by/4.0/ . The original files' publisher
hashes are in `data/strawberry/download_receipt.json`. The flow-meter file was
downloaded for provenance but is not used or included in this compact package.

The field-window CSV and replay outputs are derived from the originals by the
study authors, including backward timestamp alignment and finite data-age
limits documented in `configs/rc2_supplement/strawberry_protocol_original.json`.
The source contributors do not endorse the present analysis or simulated
network. The project's software licence does not replace the data licence.

## Dependencies and typography

NumPy, SciPy, Matplotlib, requests, pandas, tabulate and their dependencies are installed separately and retain
their respective upstream licenses. No third-party library binaries or font
files are bundled. Supplied figure exports retain existing typography;
DejaVu Sans is used for regenerated quantitative panels. Availability of
other fonts on another machine is not guaranteed.
