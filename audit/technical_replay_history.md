# Package rerun validation

During initial validation of the portable replay wrapper on case 0, the latest-delivery and battery arrays and all computed metrics matched the formal record, whereas the saved sample-status array left 278 end-of-horizon outstanding samples coded as zero because the array was exported before the model's final `metrics()` step.

The portable wrapper was updated to invoke `metrics()` before exporting the array so that every offered sample receives its terminal status. Replaying with the same seed and configuration reproduced the original arrays and all saved metrics exactly, with byte-for-byte agreement across the node-ledger, cadence-plan, and intentional-sleep CSVs.

Additional 14-day replay checks were also executed for the internal controls using their original seeds. In each case, the exported arrays (latest delivery, battery, and terminal sample status), saved metrics, and node-ledger CSVs matched the recorded results exactly, and the three exported arrays are sufficient to recompute all source-level coverage and gap summaries.
