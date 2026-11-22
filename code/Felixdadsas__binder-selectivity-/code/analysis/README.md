# analysis/

Scripts that turn the raw CSVs in `results/` into the figures and tables of the paper.
Each script reads from `results/` and writes nothing back into it.

Planned, in the order they become useful:

| Script | Does |
| --- | --- |
| `noise_floor.py` | Compares two independent batches on the *same* target. Establishes the pipeline's run-to-run spread, which every later Δ must clear to count. |
| `cross_score_matrix.py` | Builds the binder × target score table: BNP-designed binders scored on ANP and vice versa, plus the scrambled control. |
| `delta_distribution.py` | The Δ (own-target minus cross-target score) distribution, against the noise floor from `noise_floor.py`. Distributions, not best-of-n. |
| `ipsae.py` | Recomputes ipSAE from the PAE output the pipeline already produces, as a second, independent metric. Disagreement with iPTM is itself a result. |

## Before writing any of these

**The column names are not known yet.** They come from BoltzGen's own
`all_designs_metrics.csv`, and must be read off a real file rather than assumed.
`scores.py --columns <csv>` prints them. Nothing here should hard-code a column name
that has not been seen in an actual results file.

## Scoring caveat

Every column these scripts touch is a **structural confidence metric** (pTM / pAE /
iPTM / RMSD and interface terms), not a predicted affinity: Boltz-2's affinity module
is protein–small-molecule only and does not apply to a 32-residue peptide target.
There is no experimental ground truth in this project, so conclusions are limited to
whether the pipeline's own scores discriminate — never to whether the designs really
are selective.
