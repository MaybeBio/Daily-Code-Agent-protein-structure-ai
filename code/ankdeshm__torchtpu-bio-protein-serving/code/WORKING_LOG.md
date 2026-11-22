# Working Log: Bio & Protein AI Bring-Up on TPU v7x

Chronological engineering log of license verification, model loading, operator shims, precision fixes, and measurements on Google Cloud TPU v7x.

## 1. License Audit & Local Weight Staging

- Confirmed MIT licenses for every selected model before downloading weights:
  - `facebook/esm2_t36_3B_UR50D` (MIT)
  - `facebook/esm2_t48_15B_UR50D` (MIT)
  - `facebook/esmfold_v1` (MIT)
  - `boltz-community/boltz-2` (MIT)
- Downloaded weights into local RAM-disk storage (`/dev/shm/bio_models`), enabling `2.90 s` (`ESM-2 3B`), `4.38 s` (`ESMFold`), `7.61 s` (`ESM-2 15B`), and `13.75 s` (`Boltz-2`) load times onto `tpu:0`.

## 2. Protein Language Models (`ESM-2 3B` & `ESM-2 15B`)

- Both `ESM-2 3B` and `ESM-2 15B` compiled and executed on a single TPU v7x core in `bf16` via `torch.compile(backend="tpu")` on the first pass.
- `ESM-2 15B` (`30 GB` in `bf16`) fit comfortably inside one core's 96 GB HBM without model sharding, reaching `18.72 ms` (`B=1`, `seq=256`) and `18,010 residues/s` (`B=16`, `seq=512`).
- Biological sanity gates passed for both models (`ESM-2 3B`: `0.9964` homolog vs `0.8941` unrelated; `ESM-2 15B`: `0.9911` homolog vs `0.4923` unrelated).

## 3. 3D Protein Folding (`ESMFold`) Bring-Up

- **Failure 1:** Stock `EsmForProteinFolding` failed immediately on TPU with `RuntimeError: operator 'aten::linalg_cross.out' is not implemented for TPU`.
- **Attempt 1:** Monkey-patching `torch.linalg.cross` and `torch.cross` still hit the same error because `transformers/models/esm/modeling_esmfold.py` calls the tensor method `b.cross(c, dim=-1)`.
- **Resolution:** Added an algebraic 3D cross-product implementation onto `torch.Tensor.cross` alongside `torch.linalg.cross` and `torch.cross`. Full 3D folding then succeeded on `tpu:0`:
  - `ubiquitin_76aa`: `1,133.73 ms` (`52.92 folds/min`, `mean_plddt = 77.65`, `PASS`)
  - `lysozyme_129aa`: `2,448.62 ms` (`24.50 folds/min`, `mean_plddt = 83.80`, `PASS`)
  - `gfp_238aa`: `5,041.08 ms` (`11.90 folds/min`, finite, `mean_plddt = 40.07` under `bf16` ESM backbone)

## 4. `Boltz-2` 64-Block Pairformer Bring-Up

- **Issue 1 (Dependencies):** Installed pure-Python runtime requirements (`lightning-utilities`, `torchmetrics`, `einx`) with `--no-deps` so the container's PyTorch/TorchTPU wheels stayed untouched.
- **Issue 2 (Checkpoint schema):** `torch.load(..., weights_only=False)` loaded `boltz2_conf.ckpt`, but constructing the full `Boltz2` class raised `TypeError: AtomDiffusion.__init__() got an unexpected keyword argument 'mse_rotational_alignment'`. Extracted `pairformer_module.*` directly (`3,392` tensors, `196.5M` params) into `PairformerModule`.
- **Issue 3 (Precision mismatch):** Initial `bf16` run hit `RuntimeError: mm(): expected the two arguments to have the same dtype, got float32 vs bfloat16` inside `triangular_mult.py:122` because `triangular_mult.py` explicitly upcasts `einsum` inputs with `x.float()`. Switched `PairformerModule` to `fp32`.
- **Issue 4 (Boltz-1 vs Boltz-2 attention signature):** Next run hit `TypeError: AttentionPairBias.forward() got an unexpected keyword argument 'k_in'` because `PairformerModule` defaults to `v2=False`.
- **Resolution:** Instantiated `PairformerModule(384, 128, v2=True, use_trifast=False, activation_checkpointing=False, ...)` in `fp32`. All `3,392` checkpoint weights loaded cleanly (`missing=0`), and compiled TPU v7x benchmarks succeeded across `64`, `128`, `256`, and `384` tokens (`12.43 ms` to `283.06 ms`, all finite and non-degenerate).

## 5. Dual-Engine Container Audit

- Verified inside both `vllm-torchtpu v0.33.0` and `sglang-torchtpu v0.2.0` that none of `EsmModel`, `EsmForMaskedLM`, `EsmForProteinFolding`, or `Boltz2` are registered in either serving engine's `ModelRegistry`.
