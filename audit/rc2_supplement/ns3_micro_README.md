# ns-3 LR-WPAN three-node component check

This directory contains the deterministic three-node IEEE 802.15.4 (LR-WPAN) component check in ns-3 3.41 (`execution_sources/ns3_lrwpan_micro.cc`).

The setup places one receiver and two senders at 2.4 GHz (each sender 100 m from the receiver and 200 m apart, with a 120 m communication range) on the same PAN with MAC acknowledgments enabled, zero MAC retries, fixed backoff, and a deterministic test stream.

| Case | Outcome |
|---|---|
| Single sender, 100-byte payload | 1 frame received, 1 MAC ACK success |
| Two senders staggered by 100 ms | 2 frames received, 2 MAC ACK successes |
| Two hidden senders transmitting simultaneously | 1 frame received, 1 missing ACK, 1 receiver PHY drop |
| Single 500-byte unfragmented frame | 0 frames received, MAC reports `FRAME_TOO_LONG` (device MTU = 114 bytes) |

The precomputed receipt and source SHA-256 are stored in `ns3_micro_results.json` and verified by `scripts/verify.py`. The five-fragment (5 × 104-byte) multi-run experiment is located in `evidence/ns3_fragment/`.
