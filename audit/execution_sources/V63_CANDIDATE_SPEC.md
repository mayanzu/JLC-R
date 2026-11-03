# V6.3 Stage B/C — Frozen Relay-Repair Candidate Specification

## 1. Stage A Attribution Summary (4 Development Seeds: `140101..140404`)

Across the four winter/T3 cells (`WINTER_G20` and `T3_G20` at supplies `1.0` and `0.7`), differential far-source ($\ge 200\text{ m}$ from sink) relay hop losses ($\Delta = \text{HYB60} - \text{PADC-AGE}$) are:

| Category | HYB60 | PADC-AGE | Differential $\Delta$ | Positive Share |
|---|---:|---:|---:|---:|
| **P** (Relay Queue Priority Starvation) | 60,729 | 45,812 | **+14,917** | **71.91%** |
| **C** (Transit Capacity Crowded Out by 1-Hop Members) | 12,175 | 6,553 | **+5,622** | **27.10%** |
| **Q** (Prefix Quota Constraint) | 205 | 0 | **+205** | **0.99%** |
| **S** (Physical Energy / Night-Off Shortage) | 109 | 112 | −3 | 0.00% |
| **L** (Link Loss Exhaustion) | 132 | 169 | −37 | 0.00% |
| **O** (Other / Residual) | 1,680 | 1,883 | −203 | 0.00% |

**Conclusion:** **P** (`71.91%`) and **C** (`27.10%`) jointly explain **`99.01%`** of positive differential far-source relay losses in winter.

## 2. Frozen V6.3 Candidate Mechanism (`RelayRepairHYB`)

Implemented in `code/simulation/v63_model.py` (`class RelayRepairHYB(HYBSimulator)`), controlled by `v63_mechanism`:
- `"off"`: Exact byte-for-byte reproduction of `HYB60` (`HYBSimulator`).
- `"relay_repair"` (default, also aliased as `"B"`): Parameter-free relay-repair mechanism combining three strictly local, topology- and ledger-derived rules:
  1. **Transit Protection Admission (`M-B`, addressing C):**
     For each CH $j \in \mathcal{C}$ at plan installation (`t % 4 == 0`), count upstream CHs $u \in \mathcal{C}$ that list $j \in \mathcal{N}_u$, set $\text{protect}_j = \min(1, |\{u \in \mathcal{C} : j \in \mathcal{N}_u\}|)$, and compute the worst-case single-packet transit energy hold
     $$
     E_{\text{transit}, j} = \max_{u \in \mathcal{C} : j \in \mathcal{N}_u} E_{\text{ctrl, rx}}(u, j) + E_{\text{rx}} + E_{\text{fwd}}(j, \text{next}_j).
     $$
     When a 1-hop non-CH member $i \notin \mathcal{C}$ requests a grant from CH $j \in \mathcal{C}$, require that $j$ retain at least $\text{protect}_j$ free guard slots and $\text{protect}_j \cdot E_{\text{transit}, j}$ available energy after admitting $i$:
     $$
     \text{slots\_left}_j - \text{forward\_slot\_holds}_j - 1 \ge \text{protect}_j, \quad
     \text{available}(j) - r_j - (E_{\text{rx}} + E_{\text{fwd}}) \ge \text{protect}_j \cdot E_{\text{transit}, j}.
     $$
     Upstream CHs ($i \in \mathcal{C}$) can directly use this protected transit capacity.
  2. **Uncovered Staleness Tie-Breaking (`M-A`, addressing P):**
     In `choose_packet(i)`, `gain = p.birth - max(previous, cutoff - 1)` clips `previous` at `cutoff - 1`, causing all uncovered packets born in the same round to tie on `(uncovered, gain, p.birth)` and fall through to `-p.sequence` (biasing service toward low node indices `0, 1, 2...` while starving higher-indexed peripheral sources). Ranking by
     $$
     (\text{uncovered}, \text{gain}, -\text{previous}, p.\text{birth}, -p.\text{sequence})
     $$
     breaks same-round uncovered ties in favor of the longest-unupdated source (`-previous`, where `previous = local_forwarded_birth[i, p.source]`) while preserving remaining-lifetime `gain` priority in benign conditions.
  3. **Cluster-Head Period Demand Recognition (addressing P/C at period boundary):**
     Because `install_plan()` executes at the start of round $t$ ($t \bmod 4 = 0$) *before* round-$t$ sensing and *before* member receptions across rounds $t \dots t+3$, any active CH $i \in \mathcal{C}$ has structural cluster/relay demand during the 4-round period (`demand[i] = (i in chset) or _uncovered_fresh(i, cutoff)`).
- Diagnostic sub-switches `"A"` (priority tie-break + CH demand only) and `"C"` (CH recovery allowance) are also supported for isolated unit testing.

## 3. Stage C Development Screening Gate ($n = 4$: `140101, 140202, 140303, 140404`)

All thresholds must hold simultaneously before proceeding to Stage D:
1. `WINTER_G20 1.0` Mean AoI penalty vs `PADC-AGE` $\le +5\%$ (achieved: **`-0.55%`**, `-26.0 min` better than `PADC-AGE`, and `-408.9 min` better than `HYB60`).
2. `WINTER_G20 1.0` Source P5 $\ge \text{HYB60}$ and $\ge \text{PADC-AGE} - 1\text{ pp}$ (achieved: **`+0.553 pp`** vs `HYB60`, **`-0.172 pp`** vs `PADC-AGE`).
3. Coverage across all 8 cells: $\ge \text{HYB60} - 0.5\text{ pp}$ and $\ge \text{PADC-AGE} - 1.0\text{ pp}$ (achieved: beats `HYB60` in **8/8 cells**).
4. Night-off across all 8 cells: $\le \text{HYB60} + 1.0\text{ pp}$ (achieved: max increase `+0.495 pp`, strictly lower night-off than `PADC-AGE` in all 4 winter cells).
5. Winter/T3 coverage improvement vs `JLC-R-SA` remains positive in all 4 cells.
6. All unit tests, physical safety invariants, and $10^{-8}\text{ J}$ energy ledgers pass with zero violations.
