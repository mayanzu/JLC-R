# ns-3 fragmented logical-packet component study

This directory contains the three-node IEEE 802.15.4 fragmentation component experiment in ns-3 3.41 (`fragment_micro.cc`), complementing the unfragmented LR-WPAN microcheck. The experimental design is specified in `fragment_protocol.json`, and source and package digests are recorded in `fragment_lock.json`.

Each sender maps a 500-byte logical sample into five 104-byte MAC payloads (100 sample bytes plus four fragment-identification bytes) with 16-bit addressing, MAC acknowledgments, and up to three retries (device MTU = 114 bytes). Receiver completion requires all five distinct fragments to arrive. Four scenarios (single sender, two staggered senders, mutually audible contending senders, and hidden-terminal senders) are evaluated across 128 runs each.

`summarize_fragment.py` verifies record counts, statuses, and fragment identifiers from `fragment_trials_128.csv` and regenerates `fragment_summary.csv` and `fragment_summary_receipt.json` without running ns-3. To recompile and execute the C++ study directly, compile `fragment_micro.cc` against ns-3 3.41 (`ns3-core`, `ns3-network`, `ns3-mobility`, `ns3-propagation`, `ns3-spectrum`, `ns3-lr-wpan`, `ns3-antenna`) and run with `--trials=128`.
