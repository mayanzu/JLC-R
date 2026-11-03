# V6.3 Stage D — Independent Confirmation Specification

## 1. Confirmation Scope and Seed Protocol

- **Candidate Algorithm:** `RelayRepairHYB` (`v63_mechanism="relay_repair"`, designated `JLC-R-HYB-V63` / `JLC-R Final v1.1`)
- **Comparison Groups (5 groups):**
  1. `JLC-R-HYB-V63` (`RelayRepairHYB(..., v63_mechanism="relay_repair")`)
  2. `JLC-R-HYB` (`HYB60` baseline, `RelayRepairHYB(..., v63_mechanism="off")`)
  3. `PADC-AGE` (strong reactive baseline in winter/T3)
  4. `JLC-R-SA` (strong prefix-planning baseline in synthetic/spring)
  5. `PADC-AGE+V63` (`RelayRepairPADCAge(..., v63_mechanism="relay_repair")`, diagnostic control)
- **Weather–Supply Matrix (8 cells under `S200/G20`):**
  - Benign / moderate cells compared against `JLC-R-SA`: `SYNTHETIC_G20` (`1.0`, `0.7`), `T2_G20` (`1.0`, `0.7`)
  - Severe winter cells compared against `PADC-AGE`: `WINTER_G20` (`1.0`, `0.7`), `T3_G20` (`1.0`, `0.7`)
- **Confirmation Seed Sets:**
  1. **V6.0 / V6.2 12-Seed Benchmark Set (`150101, 150202, ..., 151212`):** Direct head-to-head comparison against the frozen 576-row V6.0/V6.2 table without altering any historical file.
  2. **V6.3 Clean Unseen 12-Seed Confirmation Set (`160101, 160202, ..., 161212`):** Verified via repository-wide token scan (`D_seed_search.csv`) to have zero prior occurrences in `code/`, `temp/`, git history, or test configs (`8 cells × 12 seeds × 5 groups = 480 runs`).

## 2. Pre-Registered Hypothesis Family and Statistical Protocol

- **Primary Noninferiority (NI) Family (32 tests):**
  - Across all 8 cells × 4 primary metrics against the designated strong baseline (`JLC-R-SA` in `SYNTHETIC_G20`/`T2_G20`; `PADC-AGE` in `WINTER_G20`/`T3_G20`):
    - Fresh Source Coverage (`coverage_pct`): lower NI margin $-1.0\text{ pp}$ ($d_s - (-1.0) > 0$)
    - Source Coverage P5 (`source_coverage_p5_pct`): lower NI margin $-1.0\text{ pp}$ ($d_s - (-1.0) > 0$)
    - Night-Off Rate (`night_off_pct`): upper NI margin $+1.0\text{ pp}$ ($1.0 - d_s > 0$)
    - Mean AoI (`aoi_mean_minutes`): upper relative NI margin $+5\%$ (evaluated under both the V6.0/V6.2 mean-baseline margin $0.05\bar{B} - d_s > 0$ and the paired relative margin $1.05 B_s - A_s > 0$)
- **Pre-Specified Superiority / Improvement Tests:**
  - 4 winter/T3 coverage superiority tests against `JLC-R-SA` (`WINTER_G20 1.0/0.7`, `T3_G20 1.0/0.7`)
  - 1 targeted Mean AoI repair test on `WINTER_G20 1.0`: `JLC-R-HYB-V63` vs `HYB60` ($B_{\text{HYB60}, s} - A_{\text{V63}, s} > 0$)
- **Multiplicity Control & Confidence Intervals:**
  - One-sided paired Student's $t$-tests ($\text{df} = 11$) with step-down Holm adjustment across the full family (`Holm-32`, `Holm-33`, `Holm-36`, and `Holm-37`) at $\alpha = 0.05$ (and additionally reported at the stricter $\alpha = 0.025$ threshold aligned with two-sided $95\%$ CIs), accompanied by two-sided $90\%$ and $95\%$ paired $t$ confidence intervals.
