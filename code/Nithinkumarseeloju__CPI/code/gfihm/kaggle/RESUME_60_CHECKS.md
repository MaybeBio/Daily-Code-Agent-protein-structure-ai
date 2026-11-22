# Local verification: CPI 60-epoch continuation

Verified 18 November 2026. These are local code and checkpoint checks, not the results of a new 60-epoch experiment.

- **20 checkpoint/resume tests passed**, including actual archive restoration, exact saved-state roundtrip, matching best-model weights, data-hash rejection, damaged-file recovery after setup, interruption handling, incomplete timing logs, validation parsing, and protection against replacing a newer backup with older progress.
- **CPU training and resume passed:** an isolated Davis smoke run trained one epoch and resumed to two total epochs. Iterations advanced 128 to 256. Optimizer/learning-rate/sampler states restored. The best first-epoch checkpoint was retained when the second epoch was worse.
- **All three real trained models passed strict loading and finite-prediction checks.** Repeating the same single-pair input produced the same output. Tests used small samples, not an accuracy benchmark.
- **Notebook checks passed:** seven Python code cells parse; IDs are unique; output cells are clean; the embedded helper exactly matches the tested source. The optional nbformat schema validator was unavailable locally.
- Original input ZIPs and trained model files were preserved. New artifacts are separate.

Detailed evidence is in [resume60_validation_report.json](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/resume60_validation_report.json). The actual original validation results are in [validation_before_resume.json](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/validation_before_resume.json) and [the plot](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/validation_before_resume.png).

## Remaining limits

A complete Kaggle T4 x2 run and Kaggle dependency installation have not been run here. Full training may expose hardware, package or data issues not covered by the local checks. RDKit deprecation warnings appeared during CPU tests; they did not stop execution.

No model can be promised perfect predictions. Keeping the best validation checkpoint prevents a worse validation epoch from replacing it, but does not guarantee lower error on unseen inputs. Compare validation before considering further epochs. The original trainer also computes test results at stage completion; do not use those to tune training.

The original learning-rate scheduler is not advanced by the training loop. This continuation preserves that behavior so it remains comparable to the existing run. A scheduling change needs a separately measured experiment.

The separate 3D structure pipeline has recorded ESMFold download timeouts and an inference IndexError. This score-model notebook does not resolve those failures.

## Known original model limitation

The original model averages padded neighbor slots, so batch composition can slightly change a score. A verified Davis example changed from 5.933935642 to 5.936890125 when companion molecules changed padding. The site already uses deterministic single-pair inference. Keep the same training batch size and validation settings for continuation; changing aggregation requires a separate retraining and validation experiment.
