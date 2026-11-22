---
id: foundry.controls
kind: library_module
status: active
aliases: [foundry.controls]
---
# foundry.controls

Every control of [the rubric](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/docs/conventions/rubrics.md#controls-kept-cheap) on one canonical property
release, one command, one table. A model's score on a release means little until the same split and metric have
been scored on features that carry no information about the protein's function; this command writes that
comparison once per release revision, and every model on that revision links it.

```bash
python -m foundry.controls --release path/to/release --store-revision <commit of Synthyra/esmc_embeddings>
```

`--release` is the directory `production_suite` exports: `dataset.json` beside the `train`, `validation`,
`calibration` and `test` Parquet files. The command reads the first three, checks each file's SHA-256 against the
manifest, and writes `controls.json` and a draft result record into `--result` (default
`results/serving/production_suite/<date>_controls_<dataset_id>/`). It needs no GPU and no embedding pass: the
synthetic controls are generated from the sequences, the backbone rows are read by byte range from the public store,
and the heads run on CPU.

| Control | Features | Head |
|---|---|---|
| `label_prior` | none: the training split's mean, positive rate or class frequencies | constant |
| `random_features` | `SyntheticControlView(RANDOM_VECTOR)` pooled rows, 1,920 columns, seeded by each protein's SHA-256 | ridge or logistic |
| `one_hot_sequence` | `SyntheticControlView(ONE_HOT)` pooled rows, 56 columns: residue composition and its variance | ridge or logistic |
| `random_backbone` | the random-weight ESMC-300's `final_mean_var` rows from `Synthyra/esmc_embeddings` at `esmc_300_random/pooled`, read through `foundry.embedding.hub.read_rows` at `--store-revision` | ridge or logistic |
| `metadata_only` | no sequence: log length and its square, one-hot columns of the training split's source namespace, organism, genus and first EC number at four depths (levels with two or more training rows, the 500 most frequent per field), sparse | ridge or logistic |

| Task | Head | Chosen on validation by | Test report |
|---|---|---|---|
| regression | ridge from the normal equations, alpha in {0.1, 1, 10, 100, 1000}, intercept unpenalized | Spearman | Spearman, Pearson, RMSE, MAE |
| binary | scikit-learn logistic regression, C in {0.01, 0.1, 1, 10} | average precision | PR AUC (average precision and trapezoidal), ROC AUC, balanced MCC at the validation threshold |
| multiclass | multinomial logistic regression, same grid | macro F1 | macro F1, accuracy, MCC |
| multilabel | multi-output ridge, unobserved entries trained as negatives | micro average precision over observed entries | micro PR AUC and ROC AUC, macro PR AUC over columns with both classes, micro balanced MCC |

The headline (Spearman, PR AUC, macro F1 or micro PR AUC) carries a 95 percent interval from resampling whole finest
clusters (`cluster_id`) of the test split, 1,000 replicates under seed 42, scored through row weights so a replicate
never sorts; a multilabel release uses 200 replicates because each passes every observed entry. Features are
standardized with the training split's statistics (scaled only, when sparse).

A control whose features cannot be made, such as the backbone when the store is unreachable or a sequence has no
row, is written as `not measured` with the reason; a control that would start after `--time-budget` (30 minutes by
default) is written as `dropped`. The table always names every control.

| Name | Does |
|---|---|
| `run_controls(release_directory, result_directory, *, controls, store_revision, replicates, time_budget_seconds, reader, experiment, command)` | The whole run; `reader` replaces the Hub for the backbone rows, as a test with a local store does |
| `read_release(directory)` | The `Release`: dataset id, task, vocabulary, manifest digest and a `Split` per read split with dense labels, the observed mask, cluster, source, organism and EC |
| `decode_labels(labels, masks, *, task_type, width)` | Dense labels and mask from scalar, list or compact `{width, indices, values}` rows |
| `fit_head(features, release)`, `prior_fit(release)` | The task's head on a control's `Features`; the label prior |
| `task_scores(task_type, labels, observed, prediction, classes, threshold)` | The task's metrics on one split |
| `cluster_bootstrap(statistic, cluster, *, replicates, seed)` | The headline's percentile interval over cluster replicates, `statistic` taking row weights |
| `write_table(result_directory, *, release, rows, ...)`, `read_table(path)` | `controls.json` (`controls_table_v1`) and the result record; read one back |

`controls.json` holds, per control, its status and reason, head and hyperparameter, the feature identity (the
`SyntheticControlView.identity`, the store's repository, folder, stream and revision, or the metadata fields and their
level counts), the validation and test scores, the headline's interval and the seconds it took, beside the release's
`dataset.json` digest and the store revision. The record's `metrics` block carries each measured control's test
headline as `control_<name>`, so `index/metrics.md` lists them with the models on the same release.

Decided in [the controls table record](https://github.com/Gleghorn-Lab/plm_interpretability/blob/HEAD/vendored/docs/decisions/foundry/controls/2026-10-31_controls_table.md). The
tier-0 test (`tests/tier0_smoke/test_controls.py`) covers the NumPy parts, heads, metrics, bootstrap and the table,
on arrays; the tier-1 test (`tests/tier1_unit/test_controls_run.py`) runs the command end to end on a fixture
release under the research interpreter. NumPy is imported at import time; pyarrow, scikit-learn, scipy and torch load
inside the functions that use them, and `foundry.embedding` supplies the controls and the store reader.
