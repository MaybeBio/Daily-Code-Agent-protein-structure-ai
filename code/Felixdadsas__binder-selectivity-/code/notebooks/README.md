# Notebooks

## `bnp_anp_design_v3.ipynb` — current version

Runs the whole pipeline on Colab: hardware check → install → mount Drive and restore
the weight cache → write the three target YAMLs → `boltzgen check` → noise-floor
batch → full batch → results → back the weight cache up.

Run the sections in order. **Section 6b (noise floor) decides whether section 7 is
worth running at all.** Section 7 is ~180 designs and takes hours.

Comments and markdown in the notebook are in Chinese; the repository's prose is in
English.

## Pitfalls, measured rather than guessed

- **`--use_kernels false` is required.** `pip install boltzgen` pulls
  `cuequivariance-ops-torch-cu12`, but Colab ships CUDA 13. Without the flag the run
  dies at step 1/6 with
  `ImportError: Error importing triangle_multiplicative_update from cuequivariance_ops_torch`.
  (Untested alternative: install `cuequivariance-ops-torch-cu13` instead.)
- **Use an A100 40 GB.** Peak VRAM observed is ≈3.3 GB, so the 80 GB card is wasted
  money, but a 16 GB T4 is *not* a verified substitute — it is compute capability 7.5,
  so kernels are off there anyway, and the configuration has never been run.
  The BoltzGen repo publishes no VRAM figure; any number quoted elsewhere is a guess.
- **`pip install` prints red dependency conflicts** (jax / tifffile / dm-tree /
  stumpy / ml-dtypes all want `numpy>=2.1`). Harmless — boltzgen pins
  `numpy 2.0.2` + `numba 0.61.0` deliberately, per its own dependency docs.
- **"Could not find cuda drivers … GPU will not be used"** in the log is TensorFlow's
  stub talking, not PyTorch. Ignore it.
- **Put `HF_HOME` on `/content`, never on the Drive mount.** Weight I/O through the
  mount is slow and flaky.
- **`/content` is wiped with the runtime.** The ~6 GB weight cache is tarred to Drive
  by the last section; restore it at the start of the next session.
- **`--reuse` resumes** an interrupted run instead of starting over.
- **Few designs passing `filter_rmsd` at small n is normal**, not an error: 1 of 4
  survived in the first real run. Filtering alone re-runs in ~20 s with
  `--steps filtering`.

## Measured cost (A100 40 GB, kernels off)

| | |
| --- | --- |
| Per design | ≈2.0 min |
| Colab units | 6.73 / hour |
| 200-unit month | ≈700 designs, ≈25 h of GPU |
