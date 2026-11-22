# Appendix: Full Sweeps, Op Lowerings & Precision Diagnostics

This appendix provides the complete sequence-length/batch scaling tables, TorchTPU operator-gap resolutions, precision findings, and `vllm-torchtpu` / `sglang-torchtpu` registry audit behind [`README.md`](https://github.com/ankdeshm/torchtpu-bio-protein-serving/blob/HEAD/README.md).

## Full Scaling Tables (Single TPU v7x Core)

### 1. `facebook/esm2_t36_3B_UR50D` (3B, `bf16`, `torch.compile(backend="tpu")`)

Load time from RAM-disk cache: `2.90 s`. Embedding dimension: `2560`. Quality check: ubiquitin vs single-point mutant cosine `0.9964` vs unrelated lysozyme `0.8941`.

| Sequence Length | Batch Size | Cold Compile (ms) | Warm p50 (ms) | Warm p95 (ms) | Proteins/s | Residues/s |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 256 | 1 | 11,326.66 | 5.83 | 5.88 | 171.61 | 43,932.2 |
| 256 | 8 | 15,605.06 | 41.43 | 41.72 | 193.10 | 49,433.0 |
| 256 | 32 | 15,409.97 | 154.88 | 155.05 | **206.61** | 52,891.2 |
| 512 | 1 | 12,213.75 | 9.90 | 10.05 | 101.06 | 51,742.9 |
| 512 | 8 | 15,145.69 | 75.32 | 75.55 | 106.21 | 54,377.7 |
| 512 | 32 | 17,048.57 | 290.04 | 290.26 | **110.33** | **56,488.3** |
| 1024 | 1 | 13,256.12 | 20.36 | 20.99 | **49.12** | 50,299.8 |
| 1024 | 8 | 1,260.78 | 195.99 | 197.56 | 40.82 | 41,797.8 |
| 1024 | 32 | 1,777.38 | 749.16 | 749.38 | 42.71 | 43,739.6 |

### 2. `facebook/esm2_t48_15B_UR50D` (15B, `bf16`, `torch.compile(backend="tpu")`)

Load time from RAM-disk cache: `7.61 s` onto a single TPU v7x core (`tpu:0`). Embedding dimension: `5120`. Quality check: ubiquitin vs point mutant cosine `0.9911` vs unrelated lysozyme `0.4923`.

| Sequence Length | Batch Size | Cold Compile (ms) | Warm p50 (ms) | Warm p95 (ms) | Proteins/s | Residues/s |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 256 | 1 | 15,046.90 | 18.72 | 19.18 | 53.43 | 13,677.8 |
| 256 | 4 | 16,263.13 | 58.66 | 58.78 | **68.20** | 17,458.0 |
| 256 | 16 | 18,908.60 | 238.61 | 238.77 | 67.06 | 17,166.4 |
| 512 | 1 | 15,814.21 | 31.28 | 31.67 | 31.97 | 16,368.2 |
| 512 | 4 | 19,698.02 | 114.30 | 114.61 | 34.99 | 17,917.0 |
| 512 | 16 | 19,885.64 | 454.86 | 455.15 | **35.18** | **18,009.8** |
| 1024 | 1 | 16,156.47 | 59.60 | 59.91 | **16.78** | 17,182.0 |
| 1024 | 4 | 1,501.83 | 360.75 | 360.98 | 11.09 | 11,354.3 |

### 3. `facebook/esmfold_v1` (3D Protein Folding, Mixed `bf16` ESM + `fp32` Folding Trunk)

Load time: `4.38 s`. Requires the algebraic 3D cross-product shim documented below.

| Protein Target | Length | Cold (ms) | Warm p50 (ms) | Warm p95 (ms) | Folds/min | Mean pLDDT | Gate (`>= 70`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| Human Ubiquitin | 76 aa | 4,962.12 | 1,133.73 | 1,145.21 | **52.92** | **77.65** | **PASS** |
| Hen Egg-White Lysozyme | 129 aa | 5,753.21 | 2,448.62 | 2,522.71 | **24.50** | **83.80** | **PASS** |
| Green Fluorescent Protein (GFP) | 238 aa | 8,436.22 | 5,041.08 | 5,041.62 | 11.90 | 40.07 | Low pLDDT* |

*Note on GFP (`238 aa`): All predicted atom coordinates and pLDDT values are finite, and throughput scales cleanly (`5.04 s/fold`), but single-sequence `esmfold_v1` with `bf16` ESM-2 embeddings produced lower confidence (`mean pLDDT = 40.07`) on this 238-residue beta-barrel target compared to ubiquitin (`77.65`) and lysozyme (`83.80`). Full `fp32` precision for `model.esm` or standard recycling schedules may be required for sensitive long beta-barrel proteins.

### 4. `boltz-community/boltz-2` (64-Block `PairformerModule`, `fp32`, `torch.compile(backend="tpu")`)

Load time from `boltz2_conf.ckpt` (`weights_only=False`): `13.75 s`. Loaded all `3,392` pretrained trunk tensors (`196.5M` Pairformer parameters out of `521.0M` total checkpoint parameters, `missing=0`).

| Token Count (`N`) | Pair Tensor (`N×N`) | Cold Compile (ms) | Warm p50 (ms) | Warm p95 (ms) | Passes/min | Output Std (`s` / `z`) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 64 | `64×64` | 81,420.51 | **12.43** | 13.41 | **4,825.63** | `100.96 / 138.32` |
| 128 | `128×128` | 84,529.27 | **28.08** | 28.27 | **2,136.46** | `102.85 / 69.71` |
| 256 | `256×256` | 91,126.97 | **114.73** | 114.75 | **522.97** | `105.43 / 40.33` |
| 384 | `384×384` | 96,674.26 | **283.06** | 283.16 | **211.97** | `99.94 / 28.53` |

Warm latency scales sub-cubically between `64 -> 128` (`2.26×`) and follows expected $O(N^3)$ Triangle Multiplication / Triangle Attention scaling between `128 -> 256` (`4.09×`) and `256 -> 384` (`2.47×`, vs $(384/256)^3 = 3.38\times$).

## TorchTPU Bring-Up Engineering Notes

### 1. Lowering `aten::linalg_cross.out` for `ESMFold`

Stock `transformers` `EsmForProteinFolding` calls `b.cross(c, dim=-1)` inside `modeling_esmfold.py` (`Rigid.from_3_points`), which dispatches to `aten::linalg_cross.out` and raises:

```text
RuntimeError: operator 'aten::linalg_cross.out' is not implemented for TPU.
```

Patching `torch.linalg.cross`, `torch.cross`, and `torch.Tensor.cross` with the 3-component algebraic formula lowers cleanly to TPU elementwise multiply/subtract ops with zero host-device fallback:

```python
def _tpu_cross(a, b, dim=-1, *, out=None):
    if dim < 0:
        dim = a.ndim + dim
    am, bm = a.movedim(dim, -1), b.movedim(dim, -1)
    res = torch.stack([
        am[..., 1] * bm[..., 2] - am[..., 2] * bm[..., 1],
        am[..., 2] * bm[..., 0] - am[..., 0] * bm[..., 2],
        am[..., 0] * bm[..., 1] - am[..., 1] * bm[..., 0],
    ], dim=-1).movedim(-1, dim)
    if out is not None:
        out.copy_(res)
        return out
    return res
```

### 2. `Boltz-2` Checkpoint & Precision Bring-Up

1. **Checkpoint instantiation:** Constructing the full `Boltz2` Lightning wrapper directly from `boltz2_conf.ckpt` hit a version mismatch in `AtomDiffusion.__init__` (`unexpected keyword argument 'mse_rotational_alignment'`). Instantiating `PairformerModule(token_s=384, token_z=128, v2=True, use_trifast=False, activation_checkpointing=False, **pairformer_args)` directly loads all 3,392 pretrained `pairformer_module.*` weights with zero missing keys (`missing=0`).
2. **Required `v2=True` flag:** Without `v2=True`, `PairformerLayer` constructs Boltz-1 `AttentionPairBias` (which expects `norm_s` weights and lacks the `k_in` keyword argument used in Boltz-2's forward pass).
3. **Why `fp32` is required for `PairformerModule`:** `boltz/model/layers/triangular_mult.py` explicitly casts activations to `float32` (`a, b = torch.chunk(x.float(), 2, dim=-1)`) before `torch.einsum` and then calls `self.p_out(self.norm_out(x))`. Casting module weights to `bf16` without autocast raises `RuntimeError: mm(): expected the two arguments to have the same dtype, got float32 vs bfloat16`. Keeping `PairformerModule` in `fp32` compiles and executes cleanly in a single TPU graph.

## Dual-Engine Serving Audit (`vllm-torchtpu` & `sglang-torchtpu`)

Live container `ModelRegistry` checks inside `vllm-torchtpu v0.33.0` and `sglang-torchtpu v0.2.0` confirmed:

| Architecture | `vllm-torchtpu v0.33.0` | `sglang-torchtpu v0.2.0` |
| :--- | :---: | :---: |
| `EsmModel` / `EsmForMaskedLM` | Not registered | Not registered |
| `EsmForProteinFolding` | Not registered | Not registered |
| `Boltz2` / `PairformerModule` | Not registered | Not registered |
