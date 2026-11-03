# Data dictionary

`confirmation_480.csv` has one row per method, condition, supply and paired network seed. `origin` identifies a new execution or a previously collected internal-control record. `coverage_pct` is the percentage of source-round obligations with a delivered state at most four 15-minute rounds old; `source_coverage_p5_pct` is the network's fifth percentile across its 100 source coverages; `source_coverage_jain` is Jain's index over those coverages; and `aoi_mean_minutes` averages end-of-round information age.

`sample_completion_pct` counts sampled obligations against all 134400 source-round obligations. `fixed_demand_packet_delivery_pct` counts delivered packets against the same fixed denominator. `actual_energy_j` is the sum of the 100 nodes' base, data and control charges over 14 days. The terminal columns `delivered`, `expired`, `overflow`, `outstanding`, `unsensed` and `routing_drop` sum to 134400. Missing outcome categories are represented by zero.

`node_records_48000.csv.gz` contains one row per node and case. `coverage_pct` and `aoi_mean_minutes` are computed from the saved latest-delivery trajectory. Initial battery plus harvested energy equals spill plus base, data and control charges plus final battery, within the locked numerical tolerance. The file is a compact node-level summary record.

In statistical CSVs, `mean_difference` is JLC-R minus the control except for AoI, where it is control minus JLC-R; positive always means improvement. The 95% intervals are nominal, and `adjusted_p` reports the Holm-adjusted value within the corresponding family. When contrast variance is zero, paired-t inference is undefined and is conservatively coded as p = 1 with an empty interval.
