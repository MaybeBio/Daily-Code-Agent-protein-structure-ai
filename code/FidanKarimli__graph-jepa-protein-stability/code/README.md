# Does it matter what you predict?

**Latent vs masked-residue pretraining for protein stability.**

A graph network can learn about proteins without any lab measurements, by hiding part of a
structure and guessing what was there. I wanted to know whether it matters what that guess
is:

- **the letter**, meaning which of the 20 amino acids was hidden, or
- **the vector**, meaning the embedding a slowly updated copy of the network would give
  that position (a JEPA objective), or
- **both.**

Everything else is held fixed: the same graph, encoder, corpus, masking rate, optimiser and
seeds. Any difference comes from the pretraining target alone. Each pretrained model is then
used to predict how much a single mutation destabilises a protein (ΔΔG).

**Author:** Fidan Karimli. This started in August 2026 as a project with Pau Martínez at the
Petnica Summer Institute. We finished that one with two results we could not explain, and
they kept bothering me. This repository is where I went back and worked them out.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Results

Three seeds per arm, two pretraining corpora, MegaScale for the task, all on one A100. Arms
B, C and D fine-tune a **frozen** encoder. Arm A has nothing to freeze, so it trains
everything. Effective rank is measured on a fixed 80,000 held-out pretraining residues.

**SCOPe, 11,566 experimentally determined domains**

| Arm | Pretraining target | Pooled Spearman | Per-protein median | RMSE | Effective rank |
|---|---|---|---|---|---|
| A | none | 0.605 ± 0.008 | 0.643 ± 0.011 | 0.802 ± 0.011 | n/a |
| B | vector | **0.506 ± 0.023** | 0.539 ± 0.018 | 0.903 ± 0.015 | **74.2 ± 2.3** |
| C | letter | 0.640 ± 0.005 | 0.688 ± 0.005 | 0.767 ± 0.006 | 61.9 ± 0.5 |
| D | letter + 0.45 × vector | **0.643 ± 0.008** | **0.692 ± 0.010** | 0.768 ± 0.005 | 62.6 ± 0.3 |

**AlphaFold, 26,057 predicted structures, 2.25 times larger**

| Arm | Pooled Spearman | Per-protein median | RMSE | Effective rank | Letter accuracy |
|---|---|---|---|---|---|
| B | 0.543 ± 0.012 | 0.563 ± 0.029 | 0.894 ± 0.021 | **108.2 ± 2.4** | n/a |
| C | 0.639 ± 0.003 | 0.698 ± 0.004 | 0.784 ± 0.025 | 64.6 ± 0.8 | 0.353 ± 0.003 |
| D | 0.636 ± 0.002 | 0.705 ± 0.005 | 0.781 ± 0.012 | 65.3 ± 0.6 | 0.350 ± 0.003 |

A difference under 0.012 pooled, or 0.016 per-protein, is a tie. That threshold is two
standard deviations of arm A across seeds, and I fixed it **before** running any pretrained
arm, so I could not move it later to suit a result.

### What I found

**1. Pretraining helps, but only with the right target.** Letter pretraining beats the
baseline by 0.035, using a *frozen* encoder that never saw a single stability measurement.
The baseline it beats trained its whole network on 215,000 labelled mutations.

**2. The wrong target hurts.** Vector-only pretraining scores 0.099 below random
initialisation. I also ran it unfrozen, under the same protocol as the baseline, and it was
still below. So the encoder is a worse starting point than no pretraining at all, and
fine-tuning only partly undoes that.

**3. The standard diagnostic points the wrong way.** Effective rank is the RankMe quantity,
widely used as a label-free proxy for how good a representation is. Here it ranks the arms
in exactly the reverse of how they transfer. Arm B spreads across 74 of 128 dimensions and
performs worst. Arm C uses 62 and performs best. On the larger corpus the reversal gets
starker: arm B reaches 108 dimensions and loses to arms using 65.

![Effective rank through pretraining](https://github.com/FidanKarimli/graph-jepa-protein-stability/raw/HEAD/results/figures/effective_rank_scope.png)

Arm B's curve explains something the earlier Petnica project recorded but could not account
for, which is that its JEPA loss rose during training. At epoch 1 the model collapses. Every
residue maps to almost the same vector, the rank drops to 7.7, and the loss falls to 0.007
because predicting a constant is easy. Then the EMA teacher makes that constant unstable,
the representation spreads out again, and the task gets harder. **The loss rises because the
model is escaping collapse.** With a moving target, a falling loss does not mean progress.

And escaping collapse is not the same as learning something useful.

**4. A harmful objective becomes harmless in company.** Alone, the vector loss costs 0.099.
Added alongside the letter loss at λ = 0.45 it costs nothing, arm D ties arm C, and it
prevents the collapse entirely. At epoch 1 arm D's rank was 47.3, not 7.7.

**5. The vector arm is also unstable.** Its seed spread is ±0.023 against arm C's ±0.005.

![Test score by arm](https://github.com/FidanKarimli/graph-jepa-protein-stability/raw/HEAD/results/figures/arm_comparison_scope.png)

**6. More data changed nothing.** This is the result I found most interesting. On a corpus
2.25 times larger, arms C and D moved by 0.001 and 0.007. Both are inside the tie threshold.
Arm B gained 0.037 and is still 0.062 below using no pretraining at all. The usual defence
of latent methods, that they just need more data, does not hold at this scale.

Meanwhile arm C's **letter accuracy rose from 0.267 to 0.353**, a 32% relative improvement
at the task it was trained on, while its ΔΔG score went from 0.640 to 0.639. So the model
got much better at the task it was trained on, and no better at the task I actually care
about.

Put that next to finding 3 and **neither of the two things you would normally measure
without labels, pretext-task performance and embedding rank, predicted what I cared about.**

Reference points, not targets: ThermoMPNN reports 0.725 on this test set with far heavier
pretraining, and 0.642 from scratch.

---

## How it works

**The task.** MegaScale (Tsuboyama et al. 2023) measured the stability of every
single-residue mutant of hundreds of small protein domains: 271,231 measurements across 298
proteins. The splits are made **by protein** at 25% sequence identity, so no test protein
resembles anything seen in training.

**The graph.** One node per residue at its Cα atom, joined to its 16 nearest neighbours in
3D. 62.5% of edges join residues more than 4 apart in the chain, which are contacts created
by folding and invisible to a sequence model. Node features are backbone torsions, edge
features are distances and sequence separation.

**The leak rule.** No input feature may reveal which amino acid a residue is, or the letter
arm could read the answer instead of predicting it. Only backbone atoms are used, never side
chains. [tests/test_graph.py](https://github.com/FidanKarimli/graph-jepa-protein-stability/blob/HEAD/tests/test_graph.py) enforces this by relabelling a residue
and requiring every geometric feature to come out bit-identical.

**The encoder.** Four GINEConv layers, 128 dimensions. Residue identity and backbone
geometry are embedded separately and added, so masking replaces only the identity and the
geometry stays visible.

**Pretraining.** 20% of residues are replaced by a learned mask token. Arm C predicts their
letters, arm B predicts an EMA teacher's embedding of them from the unmasked graph, arm D
does both.

**Fine-tuning.** One batch item is one protein carrying all of its mutations, so 215,000
training examples cost 239 encoder passes per epoch.

---

## Reproducing it

```bash
python -m venv .venv && source .venv/bin/activate

# torch first, separately: the right wheel depends on your CUDA driver, and a mismatch
# only shows up at import time. On macOS or cpu, plain `pip install torch`.
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
pip install -e .

bash scripts/download_megascale.sh      # 90 MB, labels and splits
bash scripts/download_structures.sh     # 13 MB, wild-type structures
bash scripts/download_scope.sh          # 1 GB, pretraining corpus

pytest tests/ -q                        # 45 tests: data alignment, leak rule, EMA, metrics

bash scripts/run_grid.sh                # 4 arms x 3 seeds, ~2 h on an A100
python scripts/make_report.py --corpus-key scope --corpus "SCOPe, 11,566 domains"
```

For the second corpus, budget about 5 hours of downloading at the rate AlphaFold DB
tolerates, then about 4 hours of training:

```bash
python scripts/download_alphafold.py --n 25000 --workers 4 --rate 3
python scripts/pin_alphafold_corpus.py            # records exactly what was collected
CORPUS=alphafold ARMS="b c d" bash scripts/run_grid.sh
python scripts/make_report.py --corpus-key alphafold --corpus "AlphaFold, 26,057 structures"
```

`data/processed/pretrain_ids.txt` and `alphafold_ids.txt` list exactly which structures each
corpus contains, so both are reproducible without re-running the similarity filter.
Rebuilding the SCOPe list needs MMseqs2 and `scripts/build_pretrain_set.py`.

Individual runs:

```bash
python -m pobj.train.pretrain --config configs/arm_c.yaml --seed 0
python -m pobj.train.finetune --config configs/arm_c.yaml --seed 0
```

### Layout

```
src/pobj/
  data/            megascale.py  graph.py  features.py  masking.py
                   pretrain_set.py  dataset.py
  models/          encoder.py  heads.py  ema.py
  eval/            metrics.py  rank.py
  train/           pretrain.py  finetune.py
  losses.py  utils.py
configs/           base.yaml + one file per arm
scripts/           downloads, the grid runner, the report
tests/             45 tests
results/           runs.csv, per-epoch logs, reports, figures
docs/progress.md   method, results, decisions and limitations in full
petnica_project/   the earlier work from the Petnica course, kept as it was
```

---

## Leakage, and why I was strict about it

Any pretraining structure that resembles a MegaScale protein could let the model meet a test
protein before evaluation. So I searched every pretraining sequence against the 298 MegaScale
proteins with MMseqs2 at its most sensitive setting, and threw out **every** hit at
e-value ≤ 1e-3. Not just the ones above 30% identity, because remote homologues can share a
fold without sharing much sequence.

That removed 225 of 11,791 SCOPe domains. 218 of them were already above 30% identity, so
being strict cost me 7 extra domains. Cheap insurance. The removed list is kept in
`data/processed/removed_similar.txt`.

## Limits

- **28 test proteins.** That is not many, and a median over 28 proteins is noisier than I
  would like.
- One encoder, one stability dataset, two pretraining corpora, three seeds. This is a
  controlled small experiment, not a ranking of methods in general.
- The two corpora differ in **four ways at once**: size, kind (predicted vs experimental),
  protein length (median 157 vs 126) and, because epochs were held at 100, the number of
  optimiser steps. So the claim is "the ordering held on a second corpus". This is not a
  scaling curve, which would need one corpus at two sizes.
- Effective rank is measured on held-out **pretraining** residues, so it describes the space
  the model trained in rather than the one it transfers to.
- Pretraining domains have a median of 126 residues against MegaScale's 48.
- Not yet tried: a λ sweep, label-efficiency curves, a frozen random encoder, longer
  pretraining (arm B's rank was still rising at epoch 99), and linear probes to say *what*
  the letter arm learned that the vector arm did not.

## Credits

This grew out of a project at the Petnica Summer Institute course on Scientific Machine
Learning, done with Pau Martínez and kept in [`petnica_project/`](https://github.com/FidanKarimli/graph-jepa-protein-stability/blob/HEAD/petnica_project) as it
was. The two share no code. Thanks to my mentor and the Petnica team. That course is where I
learned to ask this kind of question in the first place.
Course repo: <https://github.com/zenwor/sciml26_gjepa>. Our team repo from the course:
<https://github.com/paumartinez160/sciml26_gjepa>.

The two loose ends were embeddings collapsing to an effective rank of 5 to 8, and a JEPA
loss that rose during training instead of falling. Both are answered here, and it turned out
they were the same thing seen from different angles.

Building on: Tsuboyama et al. 2023 (MegaScale), Dieckhaus et al. 2024 (ThermoMPNN),
Ofer et al. 2026 (ProteinJEPA), Jamasb et al. 2024 (ProteinWorkshop), Garrido et al. 2023
(RankMe), Assran et al. 2023 (I-JEPA), Hu et al. 2020 (GINE).

## License

MIT, see [LICENSE](https://github.com/FidanKarimli/graph-jepa-protein-stability/blob/HEAD/LICENSE).
