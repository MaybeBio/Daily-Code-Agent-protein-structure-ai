# inverse-folding-benchmark

**How much of a protein's native sequence can a graph neural network recover from its backbone alone, once homologous structures are kept out of the test set?**

Trains a ProteinMPNN-style model on real X-ray crystal structures from the RCSB PDB and measures native sequence recovery on held-out backbones, against a random baseline, an amino-acid frequency baseline, an untrained network, and the published pretrained weights scored on the same residues.

> **History.** This began as `protein-binder-design`, a de novo binder project whose reported
> results were not real measurements (see section 3). It is now a benchmark. The design code in
> `src/` still assembles scaffolds and decodes sequences for a target, but nothing here validates
> that a design folds or binds. Old links to `protein-binder-design` still resolve, since GitHub
> redirects renamed repositories.

---

## 1. Training and Benchmarking on Real Structures

This repository trains and benchmarks **ProteinMPNN** on high-resolution X-ray crystal structures queried directly from the **RCSB Protein Data Bank (PDB)**.

### Dataset Curation & Query
Structures were queried programmatically via the RCSB Search API (`src/query_pdb.py`):
* **Method:** X-ray crystallography
* **Resolution:** $\le 2.0\text{ \AA}$
* **Entity Count:** Single protein chain, 0 nucleic acids
* **Length:** 80 to 200 amino acids
* **Filtering:** Cleaned for continuous, fully resolved coordinates without unmodeled loop gaps (`-`), yielding 36 pristine crystal structures (4,937 total amino acid residues).

The structures are split deterministically (`seed=42`) into:
* **Training set:** 29 structures (4,087 residues)
* **Held-out test set:** 7 structures (850 residues) — `2AZ8`, `2EHG`, `1LJN`, `5DL9`, `6MAA`, `4D3R`, `6CKS`.

### Architecture & Training Regimen
* **Model:** ProteinMPNN graph transformer (3 encoder layers, 3 decoder layers, $d_{\text{model}} = 128$, $k = 24$ nearest neighbors with local $N, C\alpha, C, O$ orientation frames).
* **Objective:** Autoregressive masked cross-entropy loss ($\text{NLL}$) conditioned on 3D backbone coordinates.
* **Optimization:** AdamW ($\text{lr} = 10^{-3}$, weight decay $= 10^{-4}$) with cosine annealing over 40 epochs.

---

## 2. Benchmark Results on Held-out Crystal Backbones

352 structures passed quality filtering, split **by sequence-similarity cluster** into 231 training,
61 validation and 60 test. The test set is scored once, after training, with the checkpoint chosen
on validation. Every figure averages 10 decoding orders per structure, and intervals resample
structures rather than residues.

| Model / Baseline | Recovery | 95% CI over structures | Perplexity |
|---|---|---|---|
| Untrained ProteinMPNN | 4.91% | — | 38.10 |
| Random guessing | 5.00% | — | 20.00 |
| Frequency baseline (always Leu) | 9.37% | — | — |
| **Trained here (231 structures)** | **31.72%** | **[28.3%, 35.5%]** | 34.23 |
| Pretrained, full PDB (Dauparas et al. 2022) | 55.74% | [54.3%, 57.1%] | 4.00 |

### The split is the result

An earlier version of this benchmark split structures at random and reported **64.80%** recovery,
which beat the published full-PDB model. That should have been the clue. It was leakage.

The PDB is highly redundant: the same protein recurs as mutants, as different ligand complexes, and
at improved resolution. Under a random split:

- **30 of 52** test structures shared more than half their 5-mers with a training structure
- **13 shared all of them** — the same sequence on both sides
- one lysozyme entry, `6A4P`, was the nearest training match to four separate test structures

So most of that 64.80% was recall. Splitting by cluster instead (5-mer Jaccard ≥ 0.3, single
linkage; 352 structures fall into 213 clusters, the largest holding 35 near-identical entries) and
assigning whole clusters to one side gives **0 of 60** test structures above the same threshold, and
recovery drops to **31.72%**. `train_mpnn.py` re-checks and prints this leakage count on every run.

The ordering is now the one you would expect: a model trained on 231 structures sits well below a
model trained on the whole PDB, and well above every baseline.

**The pretrained row is still not a held-out comparison.** Those weights were trained on the PDB up
to roughly mid-2021, and these test structures predate that, so they were almost certainly in its
training set. It is a ceiling reference, not a fair baseline.

![Benchmark Comparison](https://github.com/Aditya-galaxy/protein-binder-design/raw/HEAD/results/benchmark_comparison.png)

### Recovery and calibration come apart

By the selected epoch the model reaches 89.1% recovery on training structures against 31.7% on test,
and held-out perplexity is **34.23** — barely better than the untrained network's 38.10, despite
recovery rising six-fold. The argmax is often right while the distribution behind it is badly
overconfident. Checkpoint selection used validation *recovery*; selecting on loss would choose a much
earlier epoch. Reporting recovery alone would hide this entirely.

Per class, recovery is highest where backbone geometry constrains the answer most: conformational
pivots (G, P) **60.7%**, disulfides (C) **40.9%**, hydrophobic core **30.7%**, polar surface **23.6%**.
These come from one training run and are observations, not established facts.

![Training Curves](https://github.com/Aditya-galaxy/protein-binder-design/raw/HEAD/results/mpnn_training_curves.png)
![Biochemical Class Recovery](https://github.com/Aditya-galaxy/protein-binder-design/raw/HEAD/results/biochemical_class_recovery.png)

---

## 3. What this does not do

The trained model designs sequences for a backbone. It does **not** predict whether those sequences fold, or whether they bind anything.

Validating a designed binder needs structure prediction (AlphaFold2, ESMFold) and ultimately wet-lab binding assays. None of that is run here, so no folding confidence, interface score or binding claim is reported.

`src/geometry.py` measures the interface and nothing more: the closest C-alpha pair, how many residues fall within 8 Å of the target, how many named hotspots are engaged, and how many C-alpha pairs are too close to be physical. Every value is a count or a distance taken straight from the coordinates. Candidates are ordered for inspection, not scored, and the descriptors are deliberately left separate rather than combined into one number that would invite being read as quality.

**What was removed.** An earlier `src/validation.py` reported pLDDT, ipTM, buried surface area and shape complementarity for designed PD-L1 binders, and the README presented them as campaign results. None were computed: pLDDT and ipTM came from hand-written formulas with no structure predictor behind them, buried area was a residue count times a constant, and shape complementarity was a fitted guess. The exported PDB files also carried the invented pLDDT in the B-factor column, where a viewer colouring by B-factor would read it as genuine confidence. The module, the numbers and the B-factor are gone, and `tests/test_pipeline.py` now fails if any of them returns.

## 4. Repository Structure

```
inverse-folding-benchmark/
├── data/
│   ├── 4ZQK.pdb                # Human PD-1 / PD-L1 crystal complex
│   ├── 4Z18.pdb                # Apo Human PD-L1 crystal structure
│   └── structures/             # Downloaded PDB crystal structures (X-ray ≤ 2.0 Å)
│       ├── selection.json      # RCSB search query and metadata
│       └── splits.json         # Train / test split identifiers
├── src/
│   ├── query_pdb.py            # Automated RCSB PDB structure query & download
│   ├── train_mpnn.py           # Real ProteinMPNN training & benchmark pipeline
│   ├── evaluate.py             # Held-out scoring with intervals over structures
│   ├── target.py               # Target PDB parsing & epitope detection
│   ├── backbone.py             # 3D mini-protein scaffold generation & SE(3) docking
│   ├── mpnn.py                 # Sequence design & inverse folding
│   ├── geometry.py             # Measured interface descriptors only (see section 3)
│   └── pipeline.py             # Campaign orchestration & PDB export
├── vendor/
│   └── ProteinMPNN-main/       # Dauparas et al. ProteinMPNN architecture
├── results/
│   ├── mpnn_training_curves.png       # Loss & recovery across 40 epochs
│   ├── benchmark_comparison.png       # Baselines vs Trained vs Pretrained
│   ├── biochemical_class_recovery.png # Recovery by microenvironment
│   ├── training_summary.json          # Machine-readable benchmark report
│   ├── evaluation.json                # Per-structure recovery, intervals, deposition years
│   ├── mpnn_trained_weights.pt        # Trained PyTorch model weights
│   └── designs/                       # Candidate sequences (not validated, see section 3)
├── tests/
│   └── test_pipeline.py        # Automated unit and integration tests
├── requirements.txt
└── README.md
```

---

## 5. Quickstart & Reproducibility

### 1. Installation
```bash
git clone https://github.com/Aditya-galaxy/inverse-folding-benchmark.git
cd inverse-folding-benchmark
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Re-run Real Training & Benchmarking
```bash
# Trains ProteinMPNN on parsed crystal backbones and benchmarks held-out recovery:
python src/train_mpnn.py
```

### 3. Design sequences for a target backbone
```bash
python scripts/run_design.py --num-backbones 15 --seqs-per-backbone 2
```
This emits candidate sequences and geometric descriptors. It does not validate them: see section 3.

---

## Citations & References
* **ProteinMPNN:** Dauparas et al., "Robust deep learning–based protein sequence design using ProteinMPNN", *Science* 378, 49–56 (2022).
* **Human PD-1 / PD-L1 Interface:** Zak et al., "Structure of the Complex of Human Programmed Death 1, PD-1, and Its Ligand, PD-L1", *Structure* 23, 2341–2348 (2015).
