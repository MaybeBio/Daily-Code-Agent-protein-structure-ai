# Petnica project (August 2026)

Our original work from the Petnica Summer Institute course on Scientific Machine Learning,
kept here as it was. The experiment in the parent directory grew out of it, but shares no
code with it.

**Authors:** Fidan Karimli and Pau Martínez.
[Slides](https://canva.link/7dgujdjexcuhrbe) ·
[course repo](https://github.com/zenwor/sciml26_gjepa) ·
[our team repo](https://github.com/paumartinez160/sciml26_gjepa)

## What it did

Pretrain a graph network on unlabelled protein structures with Graph-JEPA, then fine-tune
it to predict how much a mutation changes stability (ΔΔG).

| Model | RMSE | Spearman | Spearman per protein |
|---|---|---|---|
| from scratch | 0.708 ± 0.014 | 0.548 ± 0.014 | 0.595 ± 0.013 |
| pretrained | 0.680 ± 0.012 | 0.600 ± 0.004 | 0.631 ± 0.010 |

Pretraining helped on every metric. Two things we could not explain at the time:

- The embeddings looked partly collapsed, with an effective rank of about 5–8 out of 128.
- The JEPA loss went **up** during training rather than down.

Both are answered in the follow-up experiment: the collapse is real and happens in the
first epoch, and the rising loss is the signature of the model climbing back out of it.
See `../docs/progress.md`.

## Layout

```
gjepa/        the course library: patching, the JEPA model, protein data loaders
  protein/    residue graphs, ddG fine-tuning, a node-level JEPA variant we added
notebooks/    the course notebook, blank and completed, plus its jupytext pair
materials/    our introduction to proteins, written for the course
figures/      diagrams used by the notebook and the original README
tests/        correctness checks for the protein code
requirements.txt, setup.sh
```

## Running it

Everything here expects to be run from this directory, since the notebooks load figures by
relative path:

```bash
cd petnica_project
bash setup.sh
pytest tests/
```

`setup.sh` installs torch separately from the rest, because Colab already ships a working
CUDA build and installing another on top of it breaks the runtime.

The data downloads itself on first use.

## License

MIT, same as the parent repository. The course library keeps its own terms.
