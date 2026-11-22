# OrchFold models

On-device protein structure prediction weights used by the OrchFold app (iPadOS and macOS, Apple silicon) by
Orchestr Aerospace. Download links are under [Releases](../../releases).

## What these files are

ESMFold v1 (Lin, Akin, Rao et al., *Evolutionary-scale prediction of atomic-level protein structure with a language
model*, Science 379, 2023), converted from the Hugging Face checkpoint
[`facebook/esmfold_v1`](https://huggingface.co/facebook/esmfold_v1) to [MLX](https://github.com/ml-explore/mlx)
safetensors and quantized with MLX affine quantization (group size 64). Weight names are unchanged.

| File | Contents |
|---|---|
| `esm2_3b_q4.safetensors` | ESM-2 3B language model, Linear weights 4-bit (Standard model) |
| `esmfold_trunk_q8.safetensors` | folding trunk, structure module, confidence heads at 8-bit, residue-constant tables |
| `esm2_3b_q8.safetensors` | ESM-2 3B language model, 8-bit (High Accuracy model) |
| `esmfold_trunk_q16.safetensors` | folding trunk etc. at fp16 (High Accuracy model) |

## Licence and attribution

The ESMFold and ESM-2 weights and code are released by Meta Platforms, Inc. under the MIT licence; this conversion is
distributed under the same licence (see `LICENSE`). The residue-constant tables come from AlphaFold 2 (DeepMind) via
OpenFold and Hugging Face Transformers, Apache License 2.0.

Predictions are machine-learning output, not experimental structures.

Contact: john@orchestrsim.com
