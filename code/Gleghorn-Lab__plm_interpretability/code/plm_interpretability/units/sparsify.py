"""E15b, exploratory: how few units a residue needs, in the units' own basis against other bases.

After Tigges and colleagues (Goodfire, November 2026), who kept each token's 320 units of largest absolute activation
in every layer of a language model, 7.8% of them, at little cost in loss, where random and weakest units of smaller
number cost far more. Here every residue keeps, in each edited block, the `kept` coordinates of largest absolute
value of the SwiGLU's output z and the rest are set to zero, in one of four choices:

- `native`: the units themselves.
- `rotation`: the coordinates of z in a Haar rotation of the units (`rotations.haar_rotation`), one rotation a block
  and seed; z is rotated, cut, and rotated back. A rotation keeps z's norm, so the two bases cut the same vector.
- `random`: `kept` units drawn afresh for each residue.
- `weakest`: the `kept` units of smallest absolute value.

The cut applies in every block at once (`all`) or in one block, and is read by the masked-token loss and accuracy and
by the KL divergence from the intact model's distribution at masked residues. `kept = 0` removes the feed-forward
write of the edited blocks, the reference for the share of a block's effect that a cut keeps.

Symbols: b proteins; l token columns; f units; s masked residues; v tokens of the vocabulary.
"""

from __future__ import annotations

import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from torch import Tensor, nn
from torch.nn import functional

from .ablation import column_mask, readout_positions
from .atlas import encode_batch, length_batches
from .capture import DOWN_PROJECTION_INDEX
from .causal import SWIGLU_INDEX, transformer_blocks
from .rotations import haar_rotation


BASES = ("native", "rotation", "random", "weakest")
KEPT = (0, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)
ROTATION_SEEDS = (0, 1)
SEED = 24895


def cut(product: Tensor, kept: int, basis: str, rotation: Tensor | None = None, generator: torch.Generator | None = None) -> Tensor:
    """z with all but `kept` coordinates of each residue set to zero, in one basis."""
    # product: (..., f); rotation: (f, f)
    if kept <= 0:
        return torch.zeros_like(product)  # (..., f)
    if kept >= product.shape[-1]:
        return product  # (..., f)
    if basis == "rotation":
        if rotation is None:
            raise ValueError("The rotation basis needs its rotation.")
        turned = product.float() @ rotation  # (..., f), the coordinates in the rotated basis
        chosen = turned.abs().topk(kept, dim=-1).indices  # (..., kept)
        sparse = torch.zeros_like(turned).scatter_(-1, chosen, turned.gather(-1, chosen))  # (..., f)
        return (sparse @ rotation.T).to(product.dtype)  # (..., f)
    magnitude = product.abs().float()  # (..., f)
    if basis == "native":
        chosen = magnitude.topk(kept, dim=-1).indices  # (..., kept)
    elif basis == "weakest":
        chosen = magnitude.topk(kept, dim=-1, largest=False).indices  # (..., kept)
    elif basis == "random":
        noise = torch.rand(magnitude.shape, generator=generator, device=magnitude.device)  # (..., f)
        chosen = noise.topk(kept, dim=-1).indices  # (..., kept)
    else:
        raise ValueError(f"A basis is one of {BASES}, not {basis!r}.")
    return torch.zeros_like(product).scatter_(-1, chosen, product.gather(-1, chosen))  # (..., f)


@contextmanager
def keep_top(model: nn.Module, kept: int, basis: str, blocks: Sequence[int], *,
             rotations: Mapping[int, Tensor] | None = None, seed: int = SEED) -> Iterator[None]:
    """Cut every residue's z in the listed blocks while the context is open."""
    # rotations: (f, f) for each block
    layers = transformer_blocks(model)
    handles = []

    def hook_for(block: int) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], Tensor]:
        generator = None
        if basis == "random":
            generator = torch.Generator(device=next(model.parameters()).device).manual_seed(seed + block)

        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> Tensor:
            # args: ((b, l, 2f),), the gate and up halves; output: (b, l, f)
            return cut(output, kept, basis, None if rotations is None else rotations[block], generator)  # (b, l, f)
        return hook  # replaces the SwiGLU's (b, l, f) output

    try:
        for block in blocks:
            handles.append(layers[block].ffn[SWIGLU_INDEX].register_forward_hook(hook_for(block)))
        yield
    finally:
        for handle in handles:
            handle.remove()


@torch.inference_mode()
def masked_distributions(model: nn.Module, sequences: Sequence[str], chosen: Sequence[np.ndarray], device: torch.device, *,
                         token_budget: int) -> tuple[Tensor, Tensor]:
    """The log probabilities over the vocabulary at every masked residue of `sequences`, and the true tokens, with
    each protein's `chosen` residues masked, in protein order."""
    # chosen: (s_protein,) 0-based residues for each of n proteins
    tokenizer = model.tokenizer
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (n,)
    log_probs, truth = [], []
    for batch in length_batches(lengths, token_budget):
        input_ids, attention_mask, _ = encode_batch(tokenizer, sequences[batch], device)  # (b, l) each
        positions = column_mask(chosen[batch], tuple(input_ids.shape)).to(device)  # (b, l)
        logits = model(input_ids=input_ids.masked_fill(positions, tokenizer.mask_token_id), attention_mask=attention_mask).logits
        log_probs.append(functional.log_softmax(logits[positions].float(), dim=-1).cpu())  # (s_batch, v)
        truth.append(input_ids[positions].cpu())
    return torch.cat(log_probs), torch.cat(truth)  # (s, v), (s,)


def readout(log_probs: Tensor, truth: Tensor, clean: Tensor) -> dict[str, float]:
    """Masked-token loss and accuracy, and the mean and median KL divergence from the intact model."""
    # log_probs, clean: (s, v); truth: (s,)
    true = log_probs.gather(1, truth.unsqueeze(1)).squeeze(1).double()  # (s,)
    divergence = (clean.exp().double() * (clean.double() - log_probs.double())).sum(dim=1)  # (s,)
    return {"loss": float(-true.mean()), "accuracy": float((log_probs.argmax(dim=1) == truth).double().mean()),
            "kl": float(divergence.mean()), "kl_median": float(divergence.median())}


def run_sparsify(model: nn.Module, sequences: Sequence[str], device: torch.device, *, single_block: int,
                 kept: Sequence[int] = KEPT, rotation_seeds: Sequence[int] = ROTATION_SEEDS, token_budget: int,
                 limit: int | None = None, log: Callable[[str], None] = print) -> pd.DataFrame:
    """Every cut of `kept` in every basis, in all blocks at once and in `single_block` alone, read on the masked
    residues of `sequences`. `limit` stops after that many conditions, for a pilot."""
    blocks = list(range(len(transformer_blocks(model))))
    units = transformer_blocks(model)[0].ffn[DOWN_PROJECTION_INDEX].in_features
    lengths = np.array([len(sequence) for sequence in sequences], dtype=np.int64)  # (n,)
    chosen = readout_positions(lengths)
    clean, truth = masked_distributions(model, sequences, chosen, device, token_budget=token_budget)  # (s, v), (s,)
    rows = [{"scope": "none", "basis": "intact", "seed": -1, "kept": units, "seconds": 0.0, **readout(clean, truth, clean)}]
    scopes = {"all": blocks, f"block{single_block}": [single_block]}
    conditions = [(scope, basis, seed, count) for scope in scopes for count in kept
                  for basis, seeds in (("native", (-1,)), ("rotation", tuple(rotation_seeds)), ("random", (-1,)), ("weakest", (-1,)))
                  for seed in seeds if count > 0 or basis == "native"]
    rotations: dict[int, dict[int, Tensor]] = {}
    for scope, basis, seed, count in conditions[:limit]:
        started = time.perf_counter()
        turned = None
        if basis == "rotation":
            if seed not in rotations:
                # One rotation a block, its seed the listed seed times 1,000 plus the block, drawn once and kept.
                rotations[seed] = {block: haar_rotation(units, seed * 1_000 + block, device=device) for block in blocks}
            turned = rotations[seed]
        with keep_top(model, count, basis, scopes[scope], rotations=turned):
            log_probs, _ = masked_distributions(model, sequences, chosen, device, token_budget=token_budget)
        rows.append({"scope": scope, "basis": basis if count > 0 else "removed", "seed": seed, "kept": count,
                     "seconds": time.perf_counter() - started, **readout(log_probs, truth, clean)})
        log(f"sparsify {scope} {rows[-1]['basis']} seed {seed} kept {count}: loss {rows[-1]['loss']:.4f}, "
            f"KL {rows[-1]['kl']:.4f}")
    return pd.DataFrame(rows).assign(masked=len(truth), proteins=len(sequences))
