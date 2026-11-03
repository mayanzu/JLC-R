# V6.3 Stage A — Multi-Hop Relay-Loss Attribution Specification

## 1. Purpose and Scope

This specification freezes the read-only hop-fate attribution design (Stage A) prior to implementing any V6.3 control modification. It instruments the exact `HYB60` (`HYBSimulator`) and `PADC-AGE` (`DiagnosticPADCAge`) trajectories on the 4-seed development set across all 8 weather–supply cells without modifying any RNG call, queue order, battery state, or control decision.

- **Development Seeds ($n = 4$):** `140101, 140202, 140303, 140404`
- **Conditions (8 cells, 64 runs total):** `SYNTHETIC_G20`, `WINTER_G20`, `T2_G20`, `T3_G20` at supplies `1.0` and `0.7` under `S200/G20`
- **Primary Attribution Domain:** Far-source packets ($\text{distance}(\text{source}, \text{sink}) \ge 200\text{ m}$) at relay hops ($\text{holder} \ne \text{source}$) in the four winter/T3 cells (`WINTER_G20` and `T3_G20` at supplies `1.0` and `0.7`).

## 2. Mutually Exclusive Hop-Fate Categories

Every relay hop loss or relay packet expiration for a far source is classified into one of six mutually exclusive, exhaustive categories:

| Code | Category | Operational Definition |
|---|---|---|
| **S** | Physical Energy / Off Shortage | Sender or receiver is in night-off (`off == True`) or lacks physical battery above `reserve_j + forward_holds` when attempting or granting the relay hop. |
| **L** | Link Loss Exhaustion | Grant succeeds, but the relay transmission fails all `max_link_attempts` channel realizations in the round (`why == "link_loss"`). |
| **C** | Transit Capacity Crowded Out by 1-Hop Members | Receiver CH is awake (`not off[j]`) and has physical battery, but lacks free guard slots (`slots_left[j] - forward_slot_holds[j]`) or available credit (`available(j)`) because 1-hop cluster members (`i not in chset`) consumed slots/energy on `j` earlier in the same round (`pre_slots_j + pre_mem_slots_j >= need_slots` or `pre_avail_j + pre_mem_e_j >= need_j`). |
| **Q** | Prefix Quota Constraint | Sender or receiver has sufficient physical free energy (`battery - reserve_j - forward_holds >= need`), was not crowded out by 1-hop members, and is blocked solely because the prefix communication quota `quota < free_energy`. |
| **P** | Relay Queue Priority Starvation | Packet reaches a relay CH (`holder != packet.source`) and expires (`status == "expired"`) without ever being attempted at that relay (`(packet.sequence, holder) not in _attempted_at_holder`), while that relay actively transmitted or attempted other packets during the packet's residence window $[t_{\text{entry}}, t_{\text{expire}}]$. |
| **O** | Other / Residual | Any relay loss or expiration not matching **S**, **L**, **C**, **Q**, or **P** (e.g., idle relay expiration with zero activity). |

## 3. Pre-Registered Mechanism Selection Gate

Let $\Delta_k = N_k(\text{HYB60}) - N_k(\text{PADC-AGE})$ denote the differential relay-loss count in category $k \in \{\text{S}, \text{L}, \text{C}, \text{Q}, \text{P}, \text{O}\}$ summed across the 4 winter/T3 cells on the 4 development seeds, and let
$$
\text{Share}_k = \frac{\max(\Delta_k, 0)}{\sum_{m \in \{\text{S,L,C,Q,P,O}\}} \max(\Delta_m, 0)}.
$$

- **P (Relay Queue Starvation)** maps to **M-A** (Uncovered Staleness Tie-Breaking in `choose_packet` + CH Period Demand Recognition in `_select`).
- **C (Transit Capacity Crowded Out by 1-Hop Members)** maps to **M-B** (Transit Protection Admission in `request_grant`).
- **Q (Prefix Quota Constraint)** maps to **M-C** (Relay Recovery Allowance in `install_plan`).
- When **P** and **C** jointly account for $> 95\%$ of positive differential relay losses ($\text{Share}_{\text{P}} + \text{Share}_{\text{C}} = 99.01\%$, with $\text{Share}_{\text{P}} = 71.91\%$ and $\text{Share}_{\text{C}} = 27.10\%$), the coupled parameter-free relay-repair mechanism (`v63_mechanism="relay_repair"`) addressing the relay admission-and-service bottleneck is frozen for Stage C development screening.
