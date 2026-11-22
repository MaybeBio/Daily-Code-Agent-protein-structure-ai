# Agent guide

The reproduction repository of *Curated annotations locate biological concepts in protein language models from layers
to neurons* (its working title was *Exhaustive hidden-state probing*). `README.md` maps every module to the paper's
figures and tables and the paper's words to the code's, which keeps its identifiers (a state type is a `site`, a
masked token a masked residue, a community's prediction a `prompt`); this file holds what a change here must keep.

## Two import paths

Protify and the neuron study both import packages named `foundry` and `fastplms`, at different versions, so each side
runs on its own path.

| Code | Path |
|---|---|
| The survey's figures and tables (`plm_interpretability/*.py`) | `PYTHONPATH=protify` |
| The neuron study (`plm_interpretability/units/`, `scripts/units_atlas.py`) | `PYTHONPATH=.:vendored:vendored/annotation_vocabulary/src` |
| The tests, which import both | `PYTHONPATH=vendored:vendored/annotation_vocabulary/src:protify`, vendored copies first |

A module of the survey never imports from `plm_interpretability.units`, and the neuron code never imports Protify.

## Invariants

- Results are pinned. `plm_interpretability/archive.py` (`REVISION`, `POOLING_REVISION`) and `plm_interpretability/published.py`
  (`SUMMARY_REVISION`) name the archive revisions, and `protify/` is a submodule at `ca7bbd2`. Move a pin only with a
  redraw that reproduces the paper's figures.
- `plm_interpretability.reproduce` checks each model's rebuilt probe summary against the archive's before it draws. Keep the
  check.
- Every name of a probed state in a figure or table comes from `plm_interpretability/figure_style.py`, and `figure_style.install`
  refuses an old name when a figure is saved.
- The neuron study follows `preregistration.yaml` of the third archive. Its thresholds, seeds and decision rules do not
  change after the fact; a new analysis is added as its own stage of `scripts/units_atlas.py`.
- `vendored/` holds copies of lab packages. Do not edit them here.
- No probe weight, pooled store or other large or generated file enters the repository. Results go to the archives.

## Commands

```bash
PYTHONPATH=vendored:vendored/annotation_vocabulary/src:protify python -m pytest tests -q
PYTHONPATH=protify python -m plm_interpretability.reproduce --out reproduced
PYTHONPATH=protify python -m plm_interpretability.published --out published
PYTHONPATH=.:vendored:vendored/annotation_vocabulary/src python scripts/units_atlas.py --help
```

## Code

- A module docstring first, then `from __future__ import annotations`, direct imports, from-imports, and the
  repository's own imports last.
- Typed functions with one narrow job, domain names, and a shape comment on every array or tensor binding.
- Assertions for invariants and no silent fallback. A test is never skipped or marked as an expected failure.
- Figures are PNG at 300 dpi with lettered panels and no title inside the image.
