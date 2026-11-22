# TorchTPU Bio & Protein AI Benchmarks on Google Cloud TPU v7x

Running protein language models and 3D biomolecular structure models on a single **Google Cloud TPU v7x** core via TorchTPU reaches **`56,488 residues/s`** (`206.61 proteins/s` at `seq=256`) on `ESM-2 3B`, fits and serves **`ESM-2 15B`** (`30 GB` in `bf16`) on one core at **`18.72 ms`** (`68.20 proteins/s` at `B=4`), folds 3D protein coordinates end-to-end with **`ESMFold`** at **`52.92 folds/min`** (`ubiquitin`, `pLDDT=77.65`) and **`24.50 folds/min`** (`lysozyme`, `pLDDT=83.80`), and executes the full 64-block **`Boltz-2`** Triangle Attention Pairformer trunk in **`12.43–283.06 ms`** across `64–384` tokens.

## Models, Framework & Hardware

| Model | Task | Parameters | Precision | Serving Path | License |
| :--- | :--- | :---: | :---: | :--- | :--- |
| [`facebook/esm2_t36_3B_UR50D`](https://huggingface.co/facebook/esm2_t36_3B_UR50D) | Protein Language Model (Embeddings) | 3B | `bf16` | `torch.compile(backend="tpu")` | MIT |
| [`facebook/esm2_t48_15B_UR50D`](https://huggingface.co/facebook/esm2_t48_15B_UR50D) | Frontier Protein Language Model | 15B | `bf16` | `torch.compile(backend="tpu")` | MIT |
| [`facebook/esmfold_v1`](https://huggingface.co/facebook/esmfold_v1) | Single-Sequence 3D Protein Folding | 3B (ESM-2 + Evoformer + Structure) | Mixed (`bf16` ESM + `fp32` trunk/structure) | TorchTPU + algebraic 3D cross shim | MIT |
| [`boltz-community/boltz-2`](https://huggingface.co/boltz-community/boltz-2) | Biomolecular Structure Prediction (64-block Pairformer trunk) | 196.5M trunk (`521.0M` total) | `fp32` | `torch.compile(backend="tpu")` | MIT |

- **Hardware:** Single **Google Cloud TPU v7x** core (`tpu:0`, 96 GB HBM per core / 192 GB HBM per dual-core chip).
- **Software Stack:** PyTorch + `torch_tpu` (`libtpu 0.0.50`), `transformers`, `boltz`, `torch.compile(backend="tpu")`.
- **Dual-Engine Serving Audit (`vllm-torchtpu` & `sglang-torchtpu`):** Live container `ModelRegistry` checks confirmed that `EsmModel`, `EsmForMaskedLM`, `EsmForProteinFolding`, and `Boltz2` are not registered in either `vllm-torchtpu v0.33.0` or `sglang-torchtpu v0.2.0`; native TorchTPU compilation is the serving path.

## Main Results (Single TPU v7x Core)

All numbers below are steady-state warm measurements backed directly by [`results/v7x_bio_protein_models.jsonl`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/results/v7x_bio_protein_models.jsonl).

### Protein Language Models (`ESM-2 3B` & `ESM-2 15B`)

| Model | Sequence Length | Batch = 1 Latency (p50) | Peak Throughput (Batch) | Peak Residues/s | Biological Quality Gate |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **`facebook/esm2_t36_3B_UR50D`** | `256 aa` | **`5.83 ms`** | **`206.61 proteins/s`** (`B=32`) | `52,891 res/s` | Homolog cosine `0.9964` vs unrelated `0.8941` (`PASS`) |
| **`facebook/esm2_t36_3B_UR50D`** | `512 aa` | `9.90 ms` | **`110.33 proteins/s`** (`B=32`) | **`56,488 res/s`** | Homolog cosine `0.9964` vs unrelated `0.8941` (`PASS`) |
| **`facebook/esm2_t36_3B_UR50D`** | `1024 aa` | `20.36 ms` | `49.12 proteins/s` (`B=1`) | `50,300 res/s` | Homolog cosine `0.9964` vs unrelated `0.8941` (`PASS`) |
| **`facebook/esm2_t48_15B_UR50D`** | `256 aa` | **`18.72 ms`** | **`68.20 proteins/s`** (`B=4`) | `17,458 res/s` | Homolog cosine `0.9911` vs unrelated `0.4923` (`PASS`) |
| **`facebook/esm2_t48_15B_UR50D`** | `512 aa` | `31.28 ms` | `35.18 proteins/s` (`B=16`) | **`18,010 res/s`** | Homolog cosine `0.9911` vs unrelated `0.4923` (`PASS`) |
| **`facebook/esm2_t48_15B_UR50D`** | `1024 aa` | `59.60 ms` | `16.78 proteins/s` (`B=1`) | `17,182 res/s` | Homolog cosine `0.9911` vs unrelated `0.4923` (`PASS`) |

### 3D Protein Folding (`ESMFold`) & Biomolecular Structure Trunk (`Boltz-2`)

| Model | Workload / Target | Latency (p50) | Throughput | Quality / Verification |
| :--- | :--- | :---: | :---: | :--- |
| **`facebook/esmfold_v1`** | Human Ubiquitin (`76 aa`, full 3D coords) | **`1,133.73 ms`** | **`52.92 folds/min`** | Mean `pLDDT = 77.65`, finite (`PASS`) |
| **`facebook/esmfold_v1`** | Hen Lysozyme (`129 aa`, full 3D coords) | **`2,448.62 ms`** | **`24.50 folds/min`** | Mean `pLDDT = 83.80`, finite (`PASS`) |
| **`facebook/esmfold_v1`** | Green Fluorescent Protein (`238 aa`, full 3D coords) | `5,041.08 ms` | `11.90 folds/min` | Mean `pLDDT = 40.07`, finite (see [`APPENDIX.md`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/APPENDIX.md)) |
| **`boltz-community/boltz-2`** | 64-block Pairformer trunk (`64 tokens`, `fp32`) | **`12.43 ms`** | **`4,825.63 passes/min`** | Non-degenerate `s/z` outputs, finite (`PASS`) |
| **`boltz-community/boltz-2`** | 64-block Pairformer trunk (`128 tokens`, `fp32`) | **`28.08 ms`** | **`2,136.46 passes/min`** | Non-degenerate `s/z` outputs, finite (`PASS`) |
| **`boltz-community/boltz-2`** | 64-block Pairformer trunk (`256 tokens`, `fp32`) | **`114.73 ms`** | **`522.97 passes/min`** | Non-degenerate `s/z` outputs, finite (`PASS`) |
| **`boltz-community/boltz-2`** | 64-block Pairformer trunk (`384 tokens`, `fp32`) | **`283.06 ms`** | **`211.97 passes/min`** | Non-degenerate `s/z` outputs, finite (`PASS`) |

### Key Takeaways

- **Single-core 15B protein inference without tensor parallelism:** Because each TPU v7x core provides 96 GB of HBM, `ESM-2 15B` (`30 GB` weights in `bf16`) loads onto a single core in `7.61 s` and serves single-protein embeddings in `18.72 ms` (`seq=256`) with strong evolutionary separation (`0.9911` homolog vs `0.4923` unrelated).
- **TorchTPU op-gap lowering for 3D folding (`aten::linalg_cross.out`):** Stock `ESMFold` fails on TPU when `Rigid.from_3_points` calls `b.cross(c, dim=-1)`. Replacing `torch.linalg.cross`, `torch.cross`, and `torch.Tensor.cross` with a 3-line algebraic cross product unblocks full 3D coordinate generation on TPU v7x.
- **Boltz-2 Triangle Attention on TPU without CUDA Triton kernels:** Setting `use_trifast=False`, `activation_checkpointing=False`, and `v2=True` on `PairformerModule` loads 100% of pretrained trunk weights (`missing=0`) and compiles the 64-block Triangle Multiplication + Triangle Attention stack cleanly on TPU v7x.

## How to Reproduce

Run the standalone benchmark script inside a TorchTPU container with access to a TPU v7x core:

```bash
python3 scripts/benchmark_bio_protein.py \
  --model-cache /dev/shm/bio_models \
  --output results/v7x_bio_protein_models.jsonl
```

To run an individual model:

```bash
python3 scripts/benchmark_bio_protein.py --only boltz2
# Options: esm2_3b, esm2_15b, esmfold, boltz2
```

## Detailed Analysis & Raw Artifacts

- [`APPENDIX.md`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/APPENDIX.md) — Full sequence-length and batch sweeps, TorchTPU `aten::linalg_cross.out` shim details, `Boltz-2` Triangle Multiplication `fp32` precision note, `ESMFold` GFP `pLDDT` caveat, and dual-engine registry audit.
- [`WORKING_LOG.md`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/WORKING_LOG.md) — Chronological bring-up log of dependency fixes, shims, and measurements.
- [`results/v7x_bio_protein_models.jsonl`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/results/v7x_bio_protein_models.jsonl) — Complete raw benchmark outputs.
