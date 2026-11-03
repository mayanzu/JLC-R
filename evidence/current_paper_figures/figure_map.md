# Main-text figure map

Every item is provided as both a PDF for compilation and an editable SVG.

| Manuscript item | Figure stem | Provenance and display |
|---|---|---|
| Figure 1 | `fig1_system` | Author-supplied system scene; illustrative seed 1101, phase 0, outside both the historical and 24-seed follow-up sets. |
| Figure 2 | `fig2_algorithm` | Original planning and charged relay flow, adapted to label cadence, demand Guard and eligible recovery; internal equation references match Eqs. (19) and (20). |
| Figure 3 | `fig3_aggregate` | All 24 paired candidate-seed contrasts and nominal intervals, equally averaging eight cells; filled/open means use the separate secondary Holm-8 family. |
| Figure 4 | `fig4_external` | Twenty-four-seed heatmap for the two external controls; the 16 displayed coverage cells are part of a post hoc exploratory Holm-64 family that also contains Source P5 and the two internal controls. |
| Figure 5 | `fig5_factorial` | Historical twelve-seed factorial contrasts for the three added mechanisms; the existing Holm-14 decisions are retained. |
| Figure 6 | `fig6_boundaries` | Historical twelve-seed JLC-R monitoring gaps and paired Jain differences against LANTERN; the existing Holm-72 decisions are retained for panel b. |

`scripts/visualize_24seed_comparisons.py` and `scripts/visualize_24seed_heatmap.py` regenerate Figures 3 and 4 from the completed 24-seed compact run data and saved analysis under `../temp/current_research/stageB_20261030/`; both require `--source`, `--compact`, `--internal`, and a new `--output` directory. They independently recompute the plotted intervals and Holm families. `scripts/visualize_results.py` regenerates the historical experiment figures, and its Figures 5–6 match the current paper. Vertical jitter is solely a visual offset. `figure_input_manifest.json` records input and output hashes; render, collision and visual reviews are retained in the project work archive.
