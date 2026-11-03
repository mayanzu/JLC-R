# Stage C result tables (descriptive; nominal intervals)
## Reproduction check (stage C JLC-R vs stage B JLC-R)

exact=False; max abs diff per metric: coverage_pct=2.84e-14, source_coverage_p5_pct=7.11e-15, demand_delivery_pct=0, sample_completion_pct=0, consumed_j=4.33e-08

## E1 equal-condition means (8 cells x 24 seeds)
| Method | Coverage | Source P5 | Delivery | Sampling | Energy (J) |
|---|---|---|---|---|---|
| JLC-R | 40.62 | 16.01 | 21.94 | 68.20 | 1583.38 |
| Simple matched planner (SMP) | 34.07 | 12.44 | 18.62 | 68.80 | 1566.92 |
| Point planner (PP) | 41.00 | 16.35 | 22.14 | 68.03 | 1587.44 |
| No-joint PADC | 38.96 | 14.81 | 21.24 | 68.49 | 1575.00 |
| Cadence-only | 39.61 | 14.72 | 21.76 | 68.27 | 1582.31 |
| Simple PADC-cadence | 35.30 | 14.23 | 16.58 | 68.53 | 1578.08 |

## E1 paired deltas vs JLC-R (equal-condition mean of seed-level deltas, nominal 95% CI)
| Arm | Coverage | Source P5 | Delivery | Sampling | Energy (J) |
|---|---|---|---|---|---|
| SIMPLE-MATCHED-PLANNER − JLC-R | -6.54 [-7.04,-6.05] | -3.57 [-4.17,-2.97] | -3.33 [-3.57,-3.09] | +0.60 [+0.53,+0.67] | -16.46 [-17.49,-15.43] |
| POINT-PLANNER − JLC-R | +0.38 [+0.34,+0.43] | +0.33 [+0.23,+0.43] | +0.20 [+0.17,+0.22] | -0.16 [-0.18,-0.15] | +4.06 [+3.69,+4.43] |
| SIMPLE-MATCHED-PLANNER − No-joint PADC | -4.89 | -2.37 | -2.63 | +0.31 | -8.08 |
| POINT-PLANNER − No-joint PADC | +2.04 | +1.54 | +0.89 | -0.46 | +12.44 |

### Per-cell coverage / Source P5 deltas (SMP − JLC-R)
| Cell | ΔCoverage | ΔSource P5 |
|---|---|---|
| SYNTHETIC_G20|1.0 | -6.22 | -4.95 |
| SYNTHETIC_G20|0.7 | -8.18 | -4.47 |
| WINTER_G20|1.0 | -4.48 | -2.60 |
| WINTER_G20|0.7 | -7.81 | -2.52 |
| T2_G20|1.0 | -6.41 | -5.37 |
| T2_G20|0.7 | -7.10 | -3.48 |
| T3_G20|1.0 | -7.27 | -2.72 |
| T3_G20|0.7 | -4.88 | -2.44 |

## Planner cost and floor counters
| Arm | s/call | s/run | Σfloor violations | max shortfall (J) | ΣFDC asserts |
|---|---|---|---|---|---|
| JLC-R | 0.0671 | 22.5 | 0 | 0 | 0 |
| SIMPLE-MATCHED-PLANNER | 0.0208 | 7.0 | 645226 | 0.263 | 32818 |
| POINT-PLANNER | 0.0533 | 17.9 | 0 | 0 | 0 |

## E3 freshness-window sensitivity (supply 1.0, 24 seeds, mean [sd])
| D | Method | SYNTHETIC_G20 Cov / P5 | WINTER_G20 Cov / P5 | T2_G20 Cov / P5 | T3_G20 Cov / P5 |
|---|---|---|---|---|---|
| 2 | JLC-R | 46.89 / 17.83 | 24.89 / 4.66 | 57.25 / 23.56 | 11.44 / 2.36 |
| 2 | SIMPLE-MATCHED-PLANNER | 42.05 / 15.82 | 21.68 / 3.08 | 52.19 / 21.39 | 6.61 / 0.74 |
| 4 | JLC-R | 59.35 / 28.63 | 33.90 / 7.74 | 71.99 / 38.24 | 17.20 / 4.56 |
| 4 | SIMPLE-MATCHED-PLANNER | 53.13 / 23.68 | 29.42 / 5.15 | 65.58 / 32.87 | 9.92 / 1.83 |
| 8 | JLC-R | 69.52 / 40.35 | 42.28 / 9.15 | 84.82 / 54.87 | 23.37 / 6.58 |
| 8 | SIMPLE-MATCHED-PLANNER | 66.09 / 33.92 | 41.36 / 8.00 | 79.45 / 46.33 | 22.95 / 5.92 |

### JLC-R − SMP increment by D (coverage / Source P5)
| Cell | D=2 | D=4 | D=8 |
|---|---|---|---|
| SYNTHETIC_G20 | +4.85 / +2.01 | +6.22 / +4.95 | +3.43 / +6.43 |
| WINTER_G20 | +3.21 / +1.59 | +4.48 / +2.60 | +0.92 / +1.14 |
| T2_G20 | +5.06 / +2.17 | +6.41 / +5.37 | +5.37 / +8.54 |
| T3_G20 | +4.84 / +1.62 | +7.27 / +2.72 | +0.41 / +0.66 |
