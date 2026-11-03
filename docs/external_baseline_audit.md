# External baseline adaptation notes

Both methods below are decision-strategy reimplementations in the common transaction simulator. They share the common deployment, energy inputs, propagation and task, and pay the modeled sensing, synchronization, listening, control, data, failure and retry costs.

## EADCM: energy management

M. Gerndt, M. Ispir, I. Nunez and S. Benedict, “Energy-Aware Duty Cycle Management for Solar-Powered IoT Devices,” *Sensors* 25(14), 4500 (2025), https://doi.org/10.3390/s25144500.

`code/simulation/eadcm_policy.py` retains the multi-day checkpoints, backward daily search, storage and terminal-charge constraints; `eadcm_host.py` implements daily updates and charged activity/sleep. The single-device duty decision is paired with the reference FIFO multihop transport. One causal day forecast is repeated over the five-day horizon illustrated in the original paper (with a 20% terminal target fraction), and application activity is quantized to 1/2/3/4 macro-rounds. Previous completed work estimates application energy, with an initial analytic common-load estimate used before observations exist.

## LANTERN: energy-aware multihop routing

Hossein Taghizadeh, Bardia Safaei, Amir Mahdi Hosseini Monazzah, Elyas Oustad, Sahar Rezagholi Lalani and Alireza Ejlali, “LANTERN: Learning-Based Routing Policy for Reliable Energy-Harvesting IoT Networks,” *IEEE Transactions on Network and Service Management* 21(6), 6542–6554 (2024), https://doi.org/10.1109/TNSM.2024.3450011.

`lantern_policy.py` implements the energy metric, Q updates and power hysteresis; `rpl_upward.py` implements parent choice, epsilon exploration and upward RPL state; `rpl_trickle.py`, `causal_meter.py` and `router_mac.py` implement the corresponding timers, causal rate measurements and charged logical MAC. Dynamic parent selection is retained. The 10-second energy input is adapted to rates estimated from the preceding completed 900-second round. The evaluation uses upward RPL/MOP0, explicit logical DIO/DIS/RPI sizes and the shared serialized transaction ledger.

In the original formulation, the remaining-energy reward uses the negative reserve term in the equation and Algorithm 2 line 24. Because MaximumReward is left unspecified in the original paper, a grid calibration over nine configurations (rewards C, 2C, 4C and 8C; Trickle redundancy 1, 3 and 10) on development data selected root reward 32, redundancy 1 and 0.56-second listening by coverage, Source P5, age and control cost.

## Two internal ablation controls

`v6_model.py:HYBSimulator` (JLC-Base) is the base prefix/reactive hybrid control with forwarding holds. `v63_model.py:RelayRepairHYB` (JLC-Core) adds the static transit margin, local-age tie-break and CH demand gate. The full JLC-R controller adds member activity cadence, demand-triggered Guard protection and bounded recovery.
