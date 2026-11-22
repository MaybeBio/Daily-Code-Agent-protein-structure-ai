# results/

Raw, unedited output from the design runs. **One commit per batch**, so that every
number in the paper can be traced back to the run that produced it.

What goes here:

- `all_designs_metrics.csv` as written by BoltzGen
  (`<output_dir>/final_ranked_designs/all_designs_metrics.csv`), renamed to identify
  the batch, e.g. `bnp_n60_2026-11-20.csv`, `noise_a_n20_2026-11-16.csv`.
- A short note in the commit message: target, number of designs, protocol, flags,
  GPU, date.

What does **not** go here:

- Model weights or anything else large and re-downloadable.
- Edited, filtered or hand-picked rows. Selection happens in `analysis/`, from the
  raw file, so that it stays reversible.
- Any wet-lab data.

Nothing in this folder has been experimentally validated; the columns are structural
confidence metrics, not affinities. See the root README.
