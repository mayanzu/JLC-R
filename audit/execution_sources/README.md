# JLC-R current implementation

The only public algorithm is `jlc_r.JLCR`. The frozen implementation is
`v63_model.py:RelayRepairHYB`. Eighteen unchanged kernel modules are required by
its inheritance/import graph. Version-shaped filenames in this graph are
dependency identifiers, not separate supported releases. Removing them breaks
the current implementation.

The sole public runner is `run_jlc_r.py`. It selects only the frozen
`relay_repair` mechanism and accepts no alternative algorithm flag. Run
`python -B code/simulation/run_jlc_r.py --help` from the project root.

`current_design.json` preserves the supplied physical condition overlays.
`config.json` is the unchanged common base. V63 specification files preserve
the original scientific design and identifiers. `v63_observer.py` is support
for the current safety tests and retained mechanism evidence.

Old standalone runners, matrices and unrelated tests are archived under the
project's ignored temp directory. Frozen executed sources inside research
evidence directories remain immutable and are not active release entry points.
