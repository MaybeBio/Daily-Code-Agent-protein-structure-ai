# RNA 3D: Template Retrieval, Selection and Candidate Validation

Final Year Project work on RNA 3D structure prediction (Stanford RNA 3D Folding task). The repo has two parts that plug into the same pipeline around [RNAPro](https://github.com/NVIDIA-BioNeMo/RNAPro):

```
RNA sequence
  -> template retrieval + learned selector        (template-finder/)
  -> 3D structure prediction (RNAPro, frozen)
  -> N candidate 3D structures
  -> candidate scoring, ranking, top-5 + confidence (validation_engine/)
  -> web app 3D viewer
```

| Part | What it does |
|---|---|
| `template-finder/` | Ten template-search methods, a LambdaRank selector that merges them, and RNAPro runs to test whether better templates improve final structures. |
| `validation_engine/` | Scores any folder of candidate 3D structures with gRNAde (teacher-forced perplexity), ranks them, and returns the top 5 with a confidence label. |

## Headline results

All numbers are in [`template-finder/RESULTS_FOR_REPORT.md`](https://github.com/ansamubasher/rna-3d/blob/HEAD/template-finder/RESULTS_FOR_REPORT.md) and [`validation_engine/results/summary.md`](https://github.com/ansamubasher/rna-3d/blob/HEAD/validation_engine/results/summary.md). A date filter (a chain may only use templates released before it) is applied unless stated otherwise.

**Template selector (176 test chains, scored once).** The learned selector picks better templates than the first-place Kaggle search.

| | best TM@1 | best TM@5 | hit@1 | hit@5 |
|---|---|---|---|---|
| First-place Kaggle search | 0.351 | 0.398 | 0.686 | 0.757 |
| Learned selector | 0.395 | 0.425 | 0.743 | 0.814 |
| Difference | +0.043 [+0.031, +0.056] | +0.026 [+0.017, +0.036] | | |

**RNAPro with those templates.** The better templates do not carry through to the final structures: on test (141 chains with a usable MSA) RNAPro prediction 1 is 0.719 with the selector vs 0.724 with the first-place search (−0.005, interval spans zero). RNAPro only gains clearly from near-perfect templates (+0.14 TM when given the true structure as template).

**Validation engine (CASP15, 13 targets).** gRNAde-normalised ranking gets mean top-1 TM of 0.464 vs 0.279 for a random pick and 0.552 for the oracle. Only about a dozen targets, so treat this as indicative. Confidence thresholds are rough (leave-one-target-out accuracy 0.538).

## Repository layout

```
chain_list.tsv          chains and metadata (sequence, length, release date, resolved fraction)
splits.tsv              family-based train / val / test split (plus excluded chains)
qc_log.tsv              per-chain quality-control status
residue_map.tsv         per-residue map between sequence, CIF residues and tokens
dataset.jsonl           final dataset: 1,884 chains (1,549 train / 159 val / 176 test)
template_db.tsv         template library (chain, release date, structure path, tokens)
dataprepDemo.ipynb      data preparation demo
splits-generation.ipynb how the family splits were generated

template-finder/
  PROGRESS_LOG.md       step-by-step log of everything done (Steps 0-33)
  RESULTS_FOR_REPORT.md the real numbers for the report
  details.txt           original methodology and stop-rule plan
  data/                 labels and inputs: US-align labels, features, MSA depth, label checks, timing
  methods/              the ten search methods (two-tower, MMseqs2, 3-mer, john, Rfam, ViennaRNA,
                        embeddings, RiboSeek, ...) as score-matrix scripts
  selector/             selector_v1 ... v6, method_results, selector_test
  rnapro/               RNAPro input building, runs, scoring, and chain scripts

validation_engine/
  README.md             detailed docs for the engine
  environment.md        exact Windows install steps, versions, commits, checkpoint
  config.yaml           all paths, thresholds, seeds
  validate.py           public entry point
  src/                  prepare, score_grnade, rank, label_usalign, score_lociparse, evaluate, ...
  tests/                unit tests (mapping, metrics, normalisation)
  results/              metrics, per-target scores, plots, summary.md
```

## Data

- 1,884 RNA chains from the PDB, split by sequence family: 1,549 train, 159 validation, 176 test. Validation and test queries are always searched against the 1,549 train structures.
- Structural similarity labels come from US-align on every chain pair (1,773,786 pairs). A TM-score of 0.45 or more counts as "similar". 3.2% of pairs are similar, and 92% of similar train pairs are across different sequence families.
- Only 58% of validation queries have any similar template in the library, so that bounds what any retriever can achieve.
- `splits.tsv` also lists chains that were excluded; `qc_log.tsv` records chains dropped for map or length mismatches.

## Template finder

1. **Search methods.** Each method in `template-finder/methods/` produces a query-by-template score matrix. They are the learned two-tower retriever (sequence Transformer + GVP-style geometric tower, trained from scratch), MMseqs2, 3-mer similarity, the first-place Kaggle search, Rfam/Infernal families, ViennaRNA secondary structure, RibonanzaNet2 embeddings, a RiboSeek re-implementation, and others.
2. **Pool.** The top 10 of every method are pooled (about 50 candidates per chain). All ten methods are kept because several find good templates no other method finds, beating a random-method baseline.
3. **Selector.** A LightGBM LambdaRank model (`selector/`) ranks the pool. Training tweaks and ensembles changed results by at most 0.003 TM, so the plain model is kept.
4. **RNAPro.** The released `RNAPro-Private-Best-500M` checkpoint is run unchanged with the top 5 templates, mapped by sequence alignment only (`rnapro/`).

The scripts are Kaggle kernels. Each folder has a `kernel-metadata.json` and the scripts depend on each other through `kernel_sources` (for example `dataprep` -> `build-features` -> method scores -> selector). They are meant to run on Kaggle under the owner's account; paths such as `/kaggle/input` are hard-coded. The `rnapro/run_rnapro_*_chain.sh` scripts push and wait on those kernels with the Kaggle CLI.

Recommended reading order: `PROGRESS_LOG.md` for the story, then `RESULTS_FOR_REPORT.md` for the numbers.

## Validation engine

Given one RNA sequence and a folder of candidate structures from any predictor:

```powershell
conda activate rna
python validate.py --sequence query.fasta --candidates path\to\predicted_models --top_k 5 --out results.json
```

The engine computes gRNAde teacher-forced perplexity of the sequence on each candidate backbone (zero-shot, pretrained checkpoint), z-scores it within the target, and ranks candidates. Output includes the ranked list, the top-k, a `high` / `medium` / `low` confidence label, and per-nucleotide probabilities for colouring in the 3D viewer. See [`validation_engine/README.md`](https://github.com/ansamubasher/rna-3d/blob/HEAD/validation_engine/README.md) for the full pipeline, CASP15 reproduction steps and metrics, and [`validation_engine/environment.md`](https://github.com/ansamubasher/rna-3d/blob/HEAD/validation_engine/environment.md) for setup (Windows, PowerShell, two conda envs, US-align built with MinGW-w64).

Run the tests:

```powershell
python -m pytest validation_engine/tests -q
```

Note that within one target, z-scoring preserves the order of perplexities, so raw and normalised gRNAde give identical per-target picks. Normalisation matters for pooled comparisons, confidence calibration and combining with lociPARSE.

## Known limitations

- The RNA3DB / family-held-out benchmark, template-poor chains reported separately, C1′ RMSD and per-target Z-scores are not done.
- The validation engine evaluation uses 13 CASP15 targets, and some may overlap gRNAde's training data (R1107, R1108, R1116, R1117, R1189, R1190). Results are reported with and without them.
- The data and method scripts assume Kaggle paths and kernels, so they will not run locally without edits.

## References

1. RNAPro (2025). Template-based RNA structure prediction advanced through a blind code competition. bioRxiv.
2. Joshi et al. (2025). gRNAde: Geometric Deep Learning for 3D RNA Inverse Design. ICLR 2025.
3. Jing et al. (2021). Learning from Protein Structure with Geometric Vector Perceptrons. ICLR.
4. Hamamsy et al. (2024). Protein remote homology detection and structural alignment using deep learning. Nature Biotechnology 42, 975-985.
5. Zhang et al. (2022). US-align. Nature Methods 19, 1109-1115.
6. Tarafder & Bhattacharya (2024). lociPARSE. J. Chem. Inf. Model. 64(22), 8655-8664.
7. Das et al. (2023). Assessment of three-dimensional RNA structure prediction in CASP15. Proteins 91(12), 1747-1770.
