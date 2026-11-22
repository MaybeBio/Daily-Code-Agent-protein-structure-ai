# ESMFold2 on RTX 50-series GPUs

This overlay runs full ESMFold2 with ESMC-6B on one CUDA device. Blackwell mode uses the kit's shared Triton triangle-multiplication kernels. It keeps two BF16 projection planes and computes the contraction and output in 128-row blocks. Both the accelerated and tiled reference routes use ESMFold2 chunk size 32 and move ESMC to the CPU after embedding. If a fused module runs out of memory, it stays on the 64-row PyTorch fallback for the remainder of that run. Unsupported tensor layouts also use the tiled path; the run records both kinds of calls.

The overlay loads through the launcher; it does not edit the `esm` installation or replace its checkpoint. Tested stack: `esm==3.4.0` (upstream revision `827ec128e4cdaf80f7d6f95fb367a08980b34918`), `torch==2.8.0+cu128`, Triton `3.4.0`, and one RTX 5090 (SM120). Use the [upstream ESM project](https://github.com/Biohub/esm) to obtain the Python environment and authorized local copies of the full ESMFold2 and ESMC-6B checkpoints. These files are not distributed here. `ESMFOLD2_PYTHON` optionally selects an existing environment's interpreter.

## Check the kernels and run an example

Activate your ESMFold2 environment and make only the allocated GPU visible as usual. From the repository root:

```bash
bash scripts/check.sh esmfold2                  # synthetic test; no checkpoints
export ESMFOLD2_WEIGHTS=/path/to/ESMFold2
export ESMFOLD2_ESMC=/path/to/ESMC-6B
bash scripts/esmfold2_50.sh examples/esmfold2 outputs/esmfold2-bw
```

On a scheduler, use the device assigned by the scheduler. The launcher does not change device visibility. The default Triton cache is `.jit/esmfold2`; set `TRITON_CACHE_DIR` to override it. The first run may compile kernels.

The input directory contains one JSON file per prediction, and the model loads once for the entire directory. A JSON file has a `proteins` list; each entry has a `sequence` and a `chains` list of unique chain IDs. An entry may have `msa`, an unpaired A3M path relative to that JSON file. The A3M query must match the sequence. Multiple chain IDs in an entry repeat that protein and its MSA. Omit `msa` for query-only features on that entry. This runner uses no templates. Defaults are seed 42, 20 loops, 200 sampling steps, and one sample, with MSA depth capped at 1,024 per loop. Use only matching inputs and sampling settings when comparing modes.

Outputs are flat by type: one CIF in `structures/` and one full PAE/pLDDT/chain-pair ipTM NPZ in `confidences/` for each completed prediction. `summary.json` reports timing, peak PyTorch allocated and reserved memory, and fallback counts or modules; `ranking.csv` and `index.json` index the predictions. A fold OOM is recorded and the next input is attempted. The launcher returns a nonzero status if any input failed.

## Compare with the reference

```bash
bash scripts/esmfold2_50.sh examples/esmfold2 outputs/esmfold2-tiled --mode tiled
"${ESMFOLD2_PYTHON:-python}" kits/esmfold2/compare.py outputs/esmfold2-tiled outputs/esmfold2-bw
```

`--mode tiled` preserves CPU offload and row tiling while turning off kernel fusion. `--mode stock` applies neither overlay. The comparator checks input fingerprints, run settings and output chain mappings; it reports timing, peak memory, global and per-chain-pair ipTM deltas, and mean absolute PAE difference.

### RTX 5090 qualification

A single 1,469-residue, three-chain complex using the same 14,245-row source MSA, full checkpoints and sampling settings was benchmarked against the tiled reference. GPU inference took 1,756.622 s with tiled PyTorch and 134.192 s with Blackwell (**13.09×**). These timings exclude model load and output writing. Peak PyTorch allocated memory fell from 28.25 to 25.11 GiB; peak reserved memory was 30.17 and 30.06 GiB. There were 2,364 fused calls and no fallbacks. This run used the original experiment harness; the timings are for this input and reference configuration only.

| Metric | Tiled | Blackwell |
|---|---:|---:|
| Global ipTM | 0.67236 | 0.67218 |
| Interface A–C ipTM | 0.33877 | 0.33965 |
| Interface B–C ipTM | 0.44705 | 0.44939 |

Mean absolute PAE difference across those two interfaces was 0.0561 Å. The synthetic kernel checks cover both triangle directions, FP32/BF16 inputs, a mask, and a partial row block; relative RMS errors in the initial run were about 0.65%. BF16 fusion can change rounding, and equivalence for other inputs and performance on other RTX 50-series GPUs have not been established. Peak reserved memory changed little on this large input, so the result does not show that it fits on lower-memory cards.

The overlay uses the `fpf_trimul_v4` shared runtime and was informed by [Anthropic's ESMFold2 `big` route](https://github.com/anthropics/uplifting-biomolecular-modeling/blob/f4f62fa6592ae4938d49b1757bea0cfeff9f468e/esmfold2/CHANGES.md#big--lowest-peak-gpu-memory). It uses standard PyTorch batched matmul for the tiled contraction; the surrounding projections and output use Triton. It does not use CUDA Graphs or Anthropic's `x4` layer streaming.
