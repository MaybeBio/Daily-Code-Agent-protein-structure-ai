# GRACE: GRaph Autoregressive Complex gEneration

**Version 1.1.0 (2026-11-15)** — adds the revision analyses: node-embedding ablation, seed-conditional held-out evaluation with per-group seeds, pretraining-corpus versus held-out overlap quantification, and removal of held-out leakage from the pretraining corpus (`03_corpus_construction/Filter_Heldout_Contiguous.py`).

GRACE reformulates protein complex prediction from protein-protein interaction (PPI) networks as a **graph-conditioned autoregressive generation** problem. It fuses ESM-2 sequence semantics with PPI topology via a graph-structure embedding module, and decodes complex-member sequences under functional calibration provided by a topology-aware similarity bias.

On the human PPI network, GRACE outperforms nine representative methods across Precision, Recall, F-measure, Global MMR, and Mean MMR.

---

## Repository Structure

The codebase is organized following the Methods sections of the manuscript:

| Directory                   | Corresponding manuscript section      | Contents                                                                                                               |
| --------------------------- | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `01_data_preparation/`      | Data sources and network construction | Base subgraph generation (`main/`: pipeline version; `legacy/`: early version), train/test splitting, PPI data loading |
| `02_graph_embedding/`       | Graph-structure embedding             | GAT, attention pooling, contrastive training (`Train-Cosine.py`), tokenizer                                            |
| `03_corpus_construction/`   | Training corpus construction          | BFS-serialized pretraining and SFT corpus builders (`GraphTransform_BFS_Pretrain.py`, `GraphTransform_BFS_SFT-1.py`), held-out leakage filter (`Filter_Heldout_Contiguous.py`) |
| `04_pretraining/`           | Autoregressive pre-training           | `Pretrain_Cosine.py`, LM backbone (`ModelLM.py`), dataset loader                                                       |
| `05_fine_tuning/`           | Supervised fine-tuning                | `SFT_Cosine.py`, `SFT_None.py`                                                                                         |
| `06_functional_annotation/` | Functional annotation integration     | Label propagation (`Annotation.py`), similarity matrix construction                                                    |
| `07_inference_evaluation/`  | Inference and evaluation              | `Eval_Model-100.py` (main inference), `Eval.py`, `Eval-Score.py` (Precision/Recall/F/MMR)                              |
| `08_enrichment/`            | Functional enrichment                 | Enrichment analysis scripts (GO/KEGG, etc.)                                                                            |
| `09_heldout_evaluation/`    | Held-out evaluation                   | Independent held-out pipeline (its own data split under `dataset/`)                                                    |
| `10_revision_analyses/`     | Revision analyses, organised by manuscript section | `10.1_protein_representation_learning/`, `10.2_heldout_generalization/`, `10.3_corpus_construction_audit/` |
| `data/`                     | —                                     | Inference/evaluation input files: PPI graph, complex gold standard, token mapping, held-out splits (see below)         |
| `artifacts/`                | —                                     | Pre-trained node embeddings and functional similarity matrices (see below)                                             |



---

## Requirements

- Python 3.10
- PyTorch ≥ 2.0 (CUDA 11.8+)
- transformers ≥ 4.35
- numpy, pandas, scipy, scikit-learn, networkx, tqdm, matplotlib

Optional (used by feature modules): `dgl`, `cuml`, `cupy`, `numba`, `wandb`, `gseapy`/`gprofiler` (enrichment).

See `requirements.txt`.

---

## Data

External data are **not** redistributed in this repository (licensing constraints). They can be downloaded from the original sources:

| Data                     | Source                                                        | Use                                                   |
| ------------------------ | ------------------------------------------------------------- | ----------------------------------------------------- |
| Human PPI network        | STRING v12.0 (<https://string-db.org>)                        | Network construction                                  |
| Complex annotations      | CORUM v4.0 (<https://mips.helmholtz-muenchen.de/corum>)       | Training/held-out complexes, evaluation gold standard |
| Gene Ontology            | GO (<https://geneontology.org>)                               | Functional annotation                                 |
| KEGG pathways            | KEGG (<https://www.kegg.jp>)                                  | Functional annotation                                 |
| Subcellular localization | UniProt (<https://www.uniprot.org>)                           | Functional annotation                                 |
| ESM-2 features           | ESM-2 (<https://huggingface.co/facebook/esm2_t33_650M_UR50D>) | Sequence embeddings                                   |

Pre-trained node embeddings and functional similarity matrices used for inference are provided in `artifacts/`:

- `node_embeddings_Cosine.pt` — graph-structure node embeddings (GE module output)
- `integrated_similarity_All.pt` — topology-aware functional similarity matrix B (full)
- `integrated_similarity_complex.pt` — complex-level similarity matrix

Input files required to run inference and evaluation are provided in `data/`:

- `graph.pkl` — global PPI graph (loaded by `Eval_Model-100.py`)
- `complex_graphs.pkl` — known complexes (evaluation gold standard, loaded by `Eval.py` / `Eval-Score.py`)
- `token_id_gene.pkl` — token ↔ gene mapping (loaded by evaluation scripts)
- `gene_names.pt` — vocabulary
- `hub_nodes_ids.pkl` — hub node ids used as inference seeds
- `gold_complex.csv` — the 3,837 CORUM reference complexes used as the evaluation gold standard

Two partitions are provided, each self-contained:

| Directory | Partition | Contents | Used by |
| --------- | --------- | -------- | ------- |
| `data/split_8-2/` | 3,069 training / 768 held-out | `Complex_Train.pkl`, `Complex_Test.pkl` | main benchmark (Fig. 2, Fig. 3; Tables S3-S5) |
| `data/split_7-3/` | 2,685 training / 1,152 held-out | `Complex_Train.pkl`, `Complex_Test.pkl`, `Test_has_overlap.pkl` (606), `Test_truly_unseen.pkl` (546) | held-out evaluation (Fig. 4A-D; Table S12) |

The two partitions answer different questions. The 8:2 split underpins the reconstruction
benchmark, in which every reference complex was represented in the training corpora. The 7:3
split is a family-level partition whose training corpora were filtered against the held-out
complexes, and is used for the generalization analysis. File names are identical in the two
directories, so always address them through the directory name.

Model checkpoints are archived separately (see the Zenodo record for the released weights and the two ablation arms); training corpora are regenerable via `03_corpus_construction/`.

---

## Pipeline

```bash
# 0. Prepare base subgraphs and splits (01_data_preparation/main/)
python 1.GraphModule.py
python 2.ALL_Complex_Generate_multi.py        # ~20M noisy subgraphs
python 3.Complex_Generate_multi.py

# 1. Build BFS corpus (03_corpus_construction/)
python GraphTransform_BFS_Pretrain.py         # -> pretrain corpus
python GraphTransform_BFS_SFT-1.py            # -> SFT corpus

# 1b. Remove held-out leakage from the pretraining corpus (held-out partition only)
python Filter_Heldout_Contiguous.py --corpus ../pretrain_combined.json \
    --heldout ../data/split_7-3/Complex_Test.pkl --token-map ../data/token_id_gene.pkl \
    --min-subunits 3 --out ../pretrain_combined_filtered.json --report ../filter_report.json
# -> 18,979,562 sequences scanned, 9,262 dropped (0.0488%), 18,970,300 kept

# 2. Pre-training (04_pretraining/)
python Pretrain_Cosine.py --epochs 10 --batch_size 64 --accumulation_steps 8 --learning_rate 5e-4 \
    --max_seq_len 256 --hidden_size 512 --num_hidden_layers 16 \
    --use_external_embedding True --external_embedding_path ../artifacts/node_embeddings_Cosine.pt \
    --data_path ../pretrain_combined.json --out_dir ../out_pretrain
# -> SFT starts from out_pretrain/pretrain_512_4.pth

# 3. Supervised fine-tuning (05_fine_tuning/)
python SFT_Cosine.py --epochs 2 --batch_size 64 --learning_rate 5e-6 \
    --max_seq_len 128 --data_path ../sft_0.json --out_dir ../out_sft

# 4. Inference and evaluation (07_inference_evaluation/)
python Eval_Model-100.py --output_file generation_results.pkl
python Eval.py
python Eval-Score.py                            # Precision / Recall / F-measure / Global MMR / Mean MMR

# 5. (Optional) Held-out zero-shot evaluation (09_heldout_evaluation/)
python Eval_Model.py && python Eval.py
```

---

## License

MIT License. See `LICENSE`.

If you use GRACE in your work, please cite:

> *(Citation placeholder — to be updated upon publication.)*


---

## Revision analyses (v1.1.0)

`10_revision_analyses/` is organised by the manuscript sections it supports; every table is
`utf-8-sig` CSV and every prediction file can be re-scored with `score.py`.

| Manuscript section | Directory | Contents |
| ------------------ | --------- | -------- |
| Methods · Protein representation learning; Results · Inference calibration and dissection of module contributions | `10.1_protein_representation_learning/` | Two control arms (graph attention without the contrastive objective; ESM-2 embeddings only, with and without annotation calibration), their drivers, prediction files and the four-row table |
| Methods · Benchmarking and evaluation; Results · Generalization to held-out complexes | `10.2_heldout_generalization/` | Three evaluation subsets, seed-conditional per-group protocol, size/degree strata, ten-method comparison, sequence-length histograms |
| Methods · Training corpus construction; Methods · Data sources and network construction | `10.3_corpus_construction_audit/` | Overlap between pretraining BFS sequences and held-out complexes |

The revision corpora were built by `build_corpus_73_v2.py` and `build_sft_73.py` (10.3), which
apply the held-out Jaccard filter.

### 10.1 Protein representation learning

All four configurations start from `pretrain_512_4.pth`.

| Configuration | F1 | Precision | Recall | Global MMR | Mean MMR |
| ------------- | -- | --------- | ------ | ---------- | -------- |
| GE+BA (released) | 0.5322 | 0.4330 | 0.6904 | 0.2235 | 0.4325 |
| Graph attention without the contrastive objective | 0.4357 | 0.3290 | 0.6448 | 0.1919 | 0.4116 |
| ESM-2 embeddings only, with calibration | 0.4269 | 0.3223 | 0.6317 | 0.1881 | 0.4072 |
| ESM-2 embeddings only, without calibration | 0.3673 | 0.2727 | 0.5627 | 0.1777 | 0.4240 |

```bash
cd 10_revision_analyses/10.1_protein_representation_learning/scripts
bash run_align_a.sh          # contrastive-free arm: retrain to epoch 5, SFT, generate, score
bash run_align_b_4090.sh     # ESM-2 arm: SFT from the epoch-5 checkpoint, generate, score
```

### 10.2 Held-out generalization

The seed-conditional protocol takes, for a group *G*, the union of its member proteins as the
seed set, generates one complex per seed (beta = 2.0, temperature 0.85, top-p 0.85, top-k 10,
seed 20030201), discards predictions with fewer than two proteins, and scores the remainder
against *G*. Because the sampler seeds each prompt with `args.seed + idx`, the nine groups are
generated separately rather than filtered from a single run.

```bash
cd 10_revision_analyses/10.2_heldout_generalization/scripts
python make_group_seeds.py                     # 3 subsets + 3 size bins + 3 degree bins
python Eval_Model_73_seedset.py --prompt_pkl ../results/predictions/fig4/seeds/<group>.pkl \
       --output_file ../results/predictions/fig4/<group>.pkl \
       --bias_alpha 2.0 --temperature 0.85 --top_p 0.85 --top_k 10 --seed 20030201
python make_fig4_table.py                      # scores the nine groups
python grid10.py                               # ten methods x three subsets
```

Re-score any prediction file:

```bash
python 10_revision_analyses/score.py 10_revision_analyses/10.2_heldout_generalization/results/gen_73.pkl
```

### Panel-to-file mapping for Fig. 4

| Panel | File in `10.2_heldout_generalization/results/` | Protocol |
| ----- | ---------------------------------------------- | -------- |
| 4A | `fig4ab_seed_conditional_subsets.csv` (rows `fig4a_*`) | per-group seeds, scored against that group |
| 4B, 4C | `heldout_seed_conditional_10methods.csv` | one prediction pool per method over the whole held-out set; GRACE regenerated from 2,369 held-out proteins |
| 4D | `stratified_heldout_73.csv` | the 5,185-prediction pool scored against size and degree strata (3 x 3 cells; 6+/low n = 17 not interpreted) |
| 4E | `corpus_overlap_73_summary.txt` | pretraining BFS sequences versus the 1,152 held-out complexes |

Fig. 4A values (per-group seeds):

| Subset | n | Recall | Global MMR | Mean MMR |
| ------ | - | ------ | ---------- | -------- |
| Training complexes | 2,685 | 0.7318 | 0.2584 | 0.4919 |
| Subunit-sharing held-out | 606 | 0.3317 | 0.1504 | 0.3398 |
| Unseen compositions | 546 | 0.4212 | 0.2064 | 0.4263 |

`fig4ab_seed_conditional_subsets.csv` also carries the six marginal strata under per-group
seeds (rows `fig4b_*`). They are a consistency check only; panel 4D is drawn from the single
held-out prediction pool (the 5,185-prediction protocol), which is why only that file contains
the 6+/low-degree cell.

### 10.3 Corpus construction audit

Against the 1,152 held-out complexes of the 7:3 partition, 71.5% of the protein-overlap subset
and 90.7% of the truly-unseen subset are contained as a superset in at least one pretraining BFS
sequence, while exact-sequence hits occur for only 0.2% and 1.5%. The two corpus fractions are
reported as a disclosure of what "held out" means at the corpus level: superset containment is
not removed by the filter, only verbatim reuse is.

The removal itself is implemented in `03_corpus_construction/Filter_Heldout_Contiguous.py`. A
pretraining sequence is dropped when some window of L adjacent tokens has a token set exactly
equal to the members of a held-out complex with L >= 3 subunits, i.e. the complex is reproducible
as one contiguous block. Scanning 18,979,562 sequences of the 7:3 revision corpus flags 9,262
(0.0488%) and leaves 18,970,300. Two coarser filters act upstream of this one: base subgraphs
reaching Jaccard >= 0.30 with any held-out complex are discarded together with all their noisy
copies (1,176 of 25,353), and noise-injected fine-tuning variants are screened at Jaccard >= 0.50
(7,152 of 497,816).

```bash
cd 10_revision_analyses/10.3_corpus_construction_audit/scripts
python fast_overlap_73.py
```

```bash
# sequence-level scan + removal (03_corpus_construction/)
python Filter_Heldout_Contiguous.py --corpus pretrain_combined_73_20m.json \
    --heldout split73/Complex_Test.pkl --token-map token_id_gene.pkl \
    --min-subunits 3 --dry-run          # add --out to write the filtered corpus
```
