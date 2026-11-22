# Locating biological concepts in protein language models

Code that reproduces every figure and table of *Curated annotations locate biological concepts in protein language
models from layers to neurons* ([bioRxiv](https://doi.org/10.64898/2026.11.19.767884)). The study reads three ESM
Cambrian models (ESMC-300, ESMC-600, and ESMC-6B) against curated annotation at three scales. Linear and MLP probes read
every hidden state of every block on 22 concept tasks, communities of feed-forward neurons are found from the model's
own masked-token predictions, and single feed-forward neurons, each read as a positive and a negative pole, are scored
against Swiss-Prot residue annotations beside random rotations of the same activations, the residual stream's
dimensions, and sparse autoencoders (SAEs). A last section uses the map to choose the state a protein-protein
interaction probe reads.

Every model, dataset, and result the paper uses is in the Gleghorn Lab collection
[Exhaustive hidden-state probing](https://huggingface.co/collections/GleghornLab/exhaustive-hidden-state-probing-6ad254122b677c479591339c)
on Hugging Face, under the paper's working title. The figures are drawn from three result archives, each read at a
pinned revision.

| Archive | Revision | What it holds |
|---|---|---|
| [`GleghornLab/esmc_tap_probing_results`](https://huggingface.co/datasets/GleghornLab/esmc_tap_probing_results) | `0e526f4b` | the survey of every state: score tables, training records, selections, bootstrap intervals, analysis tables, and the tuned pair probes |
| [`GleghornLab/esmc_tap_probing_pooling_results`](https://huggingface.co/datasets/GleghornLab/esmc_tap_probing_pooling_results) | `73883ced` | linear against MLP probes at three seeds under both poolings, the survey on the pooled mean, ESMC-600's probe variants, state geometry, lenses, write ablations, and erasure, and the familiarity analysis |
| [`GleghornLab/esmc_native_units_results`](https://huggingface.co/datasets/GleghornLab/esmc_native_units_results) | `c6db19f6` | the neuron study: the tests fixed in advance, the atlas sample, per-unit scores, and evaluation tables |

The code pins the first two (`plm_interpretability/archive.py`, whose `REVISION` is `a1ca0961`, an ancestor of `0e526f4b`
that lacks only the tuned pair probes, and `plm_interpretability/published.py`, which reads those at `0e526f4b`). Fig. 4,
Fig. 5E, and three supplementary readings read the neuron study's later folders (`communities/`,
`communities_activation/`, `concept_groups/`, `erasure_levels/`, `sparsify/`, `write_sums/`, `e15/`, and
`exemplar_concepts/`), which `scripts/units_release.py` lists and the third archive's next revision adds. Probe
weights, pooled stores, and the neuron study's activation maxima are not archived, since every probe retrains and
every pass reruns from the pinned models and datasets.

## The paper's words and the code's

The paper was edited after the code was written, and the code keeps its identifiers.

| Paper | Code |
|---|---|
| state type (the 17 tapped kinds of state, such as the attention keys or the feed-forward gate) | site (`site`, named in figures by `figure_style.SITE_PARTS`); a probe's state is `site:layer` |
| structure stream | the site `structural`, probed in the roots `<root>_struct` |
| best state inside a block | `inside`, intra-block |
| stream, residual stream | `embedding`, `resid_post`, and `final_norm` |
| masked token, masked-token loss | masked residue, masked loss |
| a prediction of a masked token (communities) | prompt |
| fixed in advance | preregistered (`preregistration.yaml`, hypotheses H0 to H7) |
| readings added after the tests fixed in advance | experiments E0 to E16 of `scripts/units_atlas.py` and the launch record; E15 holds the communities, concept groups, sparsity, write sums, and erasure levels |
| neuron read as two poles, each active only when the gate is open | a SwiGLU unit's gate-tagged poles: the basis `native` (`plm_interpretability/units/bases.py`) and the residue-level arm `mlp_native`; `sign`, `mlp_poles`, and `mlp_positive` read the product's sign alone, and `gate` the gate alone |
| SAE on the stream, SAE on the feed-forward write | `layer<k>_k64_<size>` and `mlp_k64_131072` |
| 2024 gold standard | the task `ppi` (`Synthyra/bernett_gold_ppi`) |
| ESM2 | `esm2_8m`, `esm2_650m` |

The archives and the code also hold probes of Bernett and colleagues' 2026 gold standard (task `ppi2`), which the
paper does not report; nothing here draws them in a paper figure.

## Install

The survey's drawing code is Protify's `interpretability` package, pinned as the submodule `protify/` at `ca7bbd2` on
Protify's `tap-probing` branch. Fetch that submodule alone, since a recursive clone also descends into Protify's own
submodules, which nothing here uses and one of which is not public.

```bash
git clone https://github.com/Gleghorn-Lab/plm_interpretability
cd plm_interpretability
git submodule update --init protify
pip install -r protify/requirements.txt -r requirements.txt
```

Protify and the neuron study each carry packages named `foundry` and `fastplms`, at different versions, so each side
runs on its own import path. The survey's modules (`plm_interpretability/*.py`) run with `PYTHONPATH=protify`. The neuron
study (`plm_interpretability/units/`, `scripts/units_atlas.py`) runs with `PYTHONPATH=.:vendored:vendored/annotation_vocabulary/src`,
whose `vendored/` holds the lab packages it imports at the versions it ran with. On Windows, enable long paths or
download into a folder at the drive's root, since the archives' paths pass 260 characters under a long one.

No figure needs a GPU, since every one is drawn from the archives' tables.

## Download the archives

`plm_interpretability.reproduce` downloads the first two archives' tables into `reproduced/archive` and
`reproduced/pooling_archive` (several thousand small files; at the Hub's rate limit it pauses and resumes, and a
token in `HF_TOKEN` raises that limit), checks each model's rebuilt probe summary against the one written when the
figures were first drawn, and redraws the survey's figures and tables with Protify's own code. Fig. 6 also reads two
tables of the tuned pair probes, and the neuron study's archive is downloaded whole.

```bash
PYTHONPATH=protify python -m plm_interpretability.reproduce --out reproduced
hf download GleghornLab/esmc_tap_probing_results analyses/last_hidden_controls/summary.parquet \
    analyses/last_hidden_controls/differences.parquet --repo-type dataset --revision 0e526f4b --local-dir reproduced/archive
hf download GleghornLab/esmc_native_units_results --repo-type dataset --revision c6db19f6 --local-dir units
```

## Reproduce each figure and table

`SURVEY=reproduced/archive`, `POOLING=reproduced/pooling_archive`, and `UNITS=units` below. Each module also takes
`--help`.

| Paper item | Module | Command |
|---|---|---|
| Fig. 1 | none; a schematic drawn in the manuscript | |
| Fig. 2, where concepts become readable along depth | `plm_interpretability/global_figure.py` | `PYTHONPATH=protify python -m plm_interpretability.global_figure --survey $SURVEY --pooling $POOLING --out fig2_global.png --pdf fig2_global.pdf` |
| Fig. 3, states inside a block against the stream | `plm_interpretability/state_figure.py` | `PYTHONPATH=protify python -m plm_interpretability.state_figure --survey $SURVEY --pooling $POOLING --out fig3_states.png --pdf fig3_states.pdf` |
| Fig. 4, communities of neurons and concept groups | `plm_interpretability/units/community_figure.py` | `python -m plm_interpretability.units.community_figure --root $UNITS --out fig4_communities.png` |
| Fig. 5, single neurons against rotations, the stream, and SAEs | `plm_interpretability/units/local_figure.py` | `python -m plm_interpretability.units.local_figure --root $UNITS --tracks $UNITS/exemplar_concepts/tracks.parquet --main fig5_neurons.png --supplement supp_units.png` |
| Fig. 6, choosing the state an interaction probe reads | `plm_interpretability/interaction_figure.py` | `PYTHONPATH=protify python -m plm_interpretability.interaction_figure --survey $SURVEY --pooling $POOLING --out fig6_interaction.png --values fig6_values.csv` |
| Supplementary Fig. 1, pretraining against the controls | `plm_interpretability/reproduce.py` (Protify's `trends`) | `reproduced/trends/controls_summary.png` |
| Supplementary Fig. 2, principal components of pooled states | `plm_interpretability/reproduce.py` (Protify's `figures`) | `reproduced/raw/pca_interpro_family_resid_post.png` |
| Supplementary Fig. 3, lenses and write ablations of ESMC-600 | `plm_interpretability/causal_figures.py` | `reproduced/causal/lens_ablation.png` |
| Supplementary Fig. 4, phosphomimetic scanning in ESMC-300 | `plm_interpretability/reproduce.py` (Protify's `figures`) | `reproduced/raw/phospho.png` |
| Supplementary Fig. 5, further readings of the units | `plm_interpretability/units/local_figure.py` | `supp_units.png`, written beside Fig. 5 |
| Supplementary Fig. 6, how much ESMC-600 uses what labeled poles read | `scripts/units_atlas.py figures` | `$UNITS/figures/figure_5.png` |
| Supplementary Table 1, familiarity | `plm_interpretability/familiarity.py` | `reproduced/familiarity/familiarity_correlations.csv` |
| Supplementary Table 2, converged solvers | `plm_interpretability/solver_table.py` | `reproduced/cross_model/solver_table.tex` |
| Supplementary Table 4, the decisions fixed in advance | `scripts/units_atlas.py tables` | `$UNITS/tables/decisions.tex` |

The neuron study's stages run with its own import path:

```bash
export PYTHONPATH=.:vendored:vendored/annotation_vocabulary/src
python scripts/units_atlas.py tables --root units --preregistration units/preregistration.yaml
python scripts/units_atlas.py figures --root units --preregistration units/preregistration.yaml
```

Supplementary Tables 3 and 5 to 7 (the tapped state types, the training settings, the controls, and the datasets) are
written in the manuscript from `docs/runs.md`, Protify's tap points, and the concept datasets' card. Every table a
figure's numbers come from is written beside it as CSV.

Three modules hold the readings that the Supplement added during review, none of them among the tests fixed in
advance.

| Reading | Module | Command |
|---|---|---|
| Onsets under a running mean and under three depths in a row, and the stream against attention's queries and keys at residues and under pooling | `plm_interpretability/survey_checks.py` | `PYTHONPATH=protify python -m plm_interpretability.survey_checks --survey $SURVEY --out survey_checks` |
| The neurons against each rotation, paired by concept (Wilcoxon signed-rank, Holm's correction) | `plm_interpretability/units/paired_rotations.py` | `python -m plm_interpretability.units.paired_rotations --root $UNITS --out paired_rotations.csv` |
| Curated terms at the predictions a community explains, within its residue (Fisher's exact test, Benjamini-Hochberg) | `plm_interpretability/units/community_terms.py` | `python -m plm_interpretability.units.community_terms --root $UNITS --out community_terms.csv` |

`reproduce` also writes figures of the earlier, longer manuscripts that this paper does not show: each model's state
maps, heads, controls and settings sweep (`main`, `raw`, `esmc600`, `esmc6b`), the survey on the pooled mean
(`trends_mean`, `cross_model_mean`), the pooling study (`pooling`, `probe_gap`), and raw against unit-norm states
(`compare`).

## Rerun the studies

`docs/runs.md` lists the Protify commands of every survey run, from the pooled stores and settings sweeps to the pair
tasks, the pooling and MLP study, ESMC-600's interventions, and the familiarity analysis. They ran in Docker on NVIDIA
GH200 GPUs, the familiarity analysis and the tuned pair probes on NVIDIA H100s. Each stage of the neuron study is a
subcommand of `scripts/units_atlas.py` that takes the same `--root` and `--preregistration`; the passes ran on one
GH200 (96 GB) and write about a terabyte of activation maxima. `scripts/units_queue.sh` holds the order they ran in,
and `Dockerfile` and `scripts/in_container.sh` the image and its entry. Its inputs are the models and datasets the
preregistration pins, among them the annotation compendium `Synthyra/annotation_compendium_v1`.

## Layout

| Path | What it holds |
|---|---|
| `protify/` | Protify at `ca7bbd2`, whose `interpretability` package trained, scored, and drew the survey |
| `plm_interpretability/` | the survey's figures and tables, each module named above; `archive.py` restores Protify's run layout from the archives, and `figure_style.py` holds the paper's names of state types |
| `plm_interpretability/units/` | the neuron study: poles and bases, the passes, InterPLM's residue-level evaluation on ESM2 and ESMC, the dictionary test, ablations, communities, and their figures and tables |
| `scripts/units_atlas.py` | one command per stage of the neuron study, from its inputs to its figures |
| `scripts/units_release.py` | how the third archive is cut from the neuron study's run, and what it leaves out |
| `scripts/publish_collection.py` | how the datasets and the first archive were filed in the collection |
| `docs/runs.md` | the Protify commands of every survey run |
| `vendored/` | the lab packages the neuron study imports: `foundry`, `fastplms`, `annotation_vocabulary`, and `annotation_transformer` |
| `tests/` | unit tests on synthetic tensors and a synthetic archive |

## Tests

The tests run on a CPU in about a minute. They import both Protify and the vendored packages, the vendored copies
first.

```bash
PYTHONPATH=vendored:vendored/annotation_vocabulary/src:protify python -m pytest tests -q
```

## Citation and licence

The code is under the Apache 2.0 licence. Please cite the paper, *Curated annotations locate biological concepts in
protein language models from layers to neurons* (Hallee and Gleghorn, bioRxiv, 2026,
[doi:10.64898/2026.11.19.767884](https://doi.org/10.64898/2026.11.19.767884)), and Protify (Rafailidis and colleagues,
2026, [doi:10.64898/2026.11.04.764373](https://doi.org/10.64898/2026.11.04.764373)). The concept datasets, splits, and
controls follow Whitfield and colleagues (bioRxiv, 2026), the interaction gold standard is Bernett and colleagues'
(Briefings in Bioinformatics 25:bbae076, 2024), and the residue-level evaluation is InterPLM's (Simon and Zou, 2025),
run with its own code.
