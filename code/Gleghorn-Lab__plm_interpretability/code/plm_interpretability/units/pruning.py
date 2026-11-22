"""E16, exploratory: ESMC-600 with a fixed set of units in every block, at the size of ESMC-300.

E15b cut every residue to its own largest activations, a different set of units at each residue. A model is smaller
only when the same units go everywhere: unit j of a block is removed by deleting row j of the gate half and of the up
half of the block's first projection and column j of its down projection, which is exact. This module measures on
calibration proteins which units a block can give up, builds the resized model and reads it.

Moments (`collect_moments`), over every token of calibration proteins with 15% of their residues masked: each block's
Gram matrix of the SwiGLU output z, each unit's count of tokens at which it is among the block's `TOP` largest by
absolute value, and its count of tokens with the gate open.

Three orders in which a block gives up its units (`removal_orders`):

- `top_share`: the units least often among a token's largest first.
- `energy`: the units of smallest mean squared write first, the mean of z_j squared times the squared norm of the
  unit's write vector.
- `obs`: optimal brain surgeon. With G the Gram matrix, C the (f, d) coefficients that rebuild the block's write from z
  (the write vectors at the start) and H the inverse of G over the units still kept, removing unit j and refitting the
  others raises the squared error of the write by |C_j|^2 / H_jj. The unit of smallest rise goes, then
  C <- C - H[:, j] C_j / H_jj and H <- H - H[:, j] H[j, :] / H_jj.

`refit_writes` is the least-squares repair of any kept set S: the write vectors B, (d, k), that minimize
|z_S B^T - z W^T|^2 over the calibration tokens, B^T = (G_SS + ridge)^-1 G_S W^T.

Those three read the intact model's activations and cut every block at once, so what one block's cut changes reaches
the next block unanswered. `sequential_set` cuts block by block instead, each on what the blocks already cut send it,
with the intact model's stream as its target.

Symbols: n blocks; t tokens; f units; k kept units; d model width; p proteins; s masked residues; v tokens of the
vocabulary.
"""

from __future__ import annotations

import copy
import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from torch import Tensor, nn

from .ablation import column_mask, readout_positions
from .atlas import encode_batch, length_batches
from .capture import DOWN_PROJECTION_INDEX
from .causal import SWIGLU_INDEX, transformer_blocks
from .sparsify import masked_distributions, readout


PROJECTION_INDEX = 1  # position of the gate-and-up projection inside a block's `ffn`
TOP = 1_024  # a token's largest activations of a block, a third of ESMC-600's 3,072 units
ORDERS = ("top_share", "energy", "obs")
REPAIRS = ("none", "refit")
RIDGE = 1e-4  # of the mean diagonal of a block's Gram matrix
WIDTHS = (768, 1_536, 2_048)
CALIBRATION_PROTEINS = 2_000
READOUT_PROTEINS = 1_000
SEED = 24895


@dataclass(frozen=True)
class Moments:
    """What the intact model's units did over the calibration tokens."""

    gram: Tensor  # (n, f, f) float64, the sum over tokens of z z^T
    top: Tensor  # (n, f) float64, tokens at which the unit is among the block's largest by absolute value
    open: Tensor  # (n, f) float64, tokens at which the unit's gate is positive
    tokens: int


@dataclass(frozen=True)
class Variant:
    """One fixed set of units: what every block keeps, and the kept units' refitted write vectors if it has them."""

    order: str
    repair: str
    width: int
    kept: Tensor  # (n, k) int64, ascending in each block
    writes: Tensor | None  # (n, d, k) float32


@dataclass(frozen=True)
class StaticRun:
    table: pd.DataFrame  # one row per model, order, repair, width and split
    residues: dict[str, pd.DataFrame]  # split -> protein, truth and each model's loss at every masked residue
    units: pd.DataFrame  # block, unit, top_share, open_rate, energy and the step at which each order gives the unit up
    variants: list[Variant]  # those of the matched width
    matched_width: int
    tokens: int


@torch.inference_mode()
def collect_moments(model: nn.Module, sequences: Sequence[str], device: torch.device, *, token_budget: int,
                    top: int = TOP) -> Moments:
    """The moments of z in every block over every token of `sequences`, each protein read with a seeded 15% of its
    residues masked, as the readout masks them."""
    layers = transformer_blocks(model)
    units = layers[0].ffn[DOWN_PROJECTION_INDEX].in_features
    gram = torch.zeros(len(layers), units, units, dtype=torch.float64, device=device)  # (n, f, f)
    top_count = torch.zeros(len(layers), units, dtype=torch.float64, device=device)  # (n, f)
    open_count = torch.zeros(len(layers), units, dtype=torch.float64, device=device)  # (n, f)
    current: dict[str, Tensor] = {}

    def hook_for(block: int) -> Callable[[nn.Module, tuple[Tensor, ...], Tensor], None]:
        def hook(module: nn.Module, args: tuple[Tensor, ...], output: Tensor) -> None:
            # args: ((b, l, 2f),), the gate then the up projection; output: (b, l, f)
            real = current["tokens"]  # (b, l)
            product = output[real].float()  # (t_batch, f)
            gram[block] += (product.T @ product).double()
            largest = product.abs().topk(min(top, units), dim=-1).indices  # (t_batch, top)
            top_count[block] += torch.bincount(largest.flatten(), minlength=units).double()
            open_count[block] += (args[0][real][:, :units] > 0).sum(dim=0).double()
        return hook  # reads the SwiGLU's (b, l, f) output

    ordered = sorted(sequences, key=len)
    lengths = np.array([len(sequence) for sequence in ordered], dtype=np.int64)  # (p,)
    chosen = readout_positions(lengths)
    handles = [layer.ffn[SWIGLU_INDEX].register_forward_hook(hook_for(block)) for block, layer in enumerate(layers)]
    tokens = 0
    try:
        for batch in length_batches(lengths, token_budget):
            input_ids, attention_mask, _ = encode_batch(model.tokenizer, ordered[batch], device)  # (b, l) each
            positions = column_mask(chosen[batch], tuple(input_ids.shape)).to(device)  # (b, l)
            current["tokens"] = attention_mask.bool()
            tokens += int(attention_mask.sum())
            model(input_ids=input_ids.masked_fill(positions, model.tokenizer.mask_token_id), attention_mask=attention_mask)
    finally:
        for handle in handles:
            handle.remove()
    return Moments(gram, top_count, open_count, tokens)


def write_vectors(model: nn.Module) -> list[Tensor]:
    """Each block's down projection, one unit's write vector a column."""
    return [layer.ffn[DOWN_PROJECTION_INDEX].weight.detach() for layer in transformer_blocks(model)]  # (d, f) each


def _damped(gram: Tensor, reference: Tensor, ridge: float) -> Tensor:
    # gram: (k, k), a principal block of `reference`; reference: (f, f)
    return gram + ridge * reference.diagonal().mean() * torch.eye(len(gram), dtype=gram.dtype, device=gram.device)  # (k, k)


def obs_order(gram: Tensor, coefficients: Tensor, *, stop: int, ridge: float = RIDGE) -> Tensor:
    """The units of one block in the order optimal brain surgeon removes them, until `stop` are left. `coefficients`
    are the least-squares coefficients of the block's target on all its units: the write vectors, one a row, when the
    target is the block's own write."""
    # gram: (f, f); coefficients: (f, d)
    units = len(gram)
    inverse = torch.linalg.inv(_damped(gram, gram, ridge))  # (f, f), H
    coefficients = coefficients.to(gram.dtype).clone()  # (f, d), C
    alive = torch.ones(units, dtype=torch.bool, device=gram.device)  # (f,)
    removed = []
    for _ in range(units - stop):
        rise = coefficients.pow(2).sum(dim=1) / inverse.diagonal()  # (f,)
        unit = int(rise.masked_fill(~alive, torch.inf).argmin())
        column = inverse[:, unit] / inverse[unit, unit]  # (f,)
        coefficients -= torch.outer(column, coefficients[unit])
        inverse -= torch.outer(column, inverse[unit])
        alive[unit] = False
        removed.append(unit)
    return torch.tensor(removed, dtype=torch.long)  # (f - stop,)


def unit_energy(moments: Moments, writes: Sequence[Tensor]) -> Tensor:
    """Each unit's mean squared write over the calibration tokens."""
    # writes: (d, f) for each of n blocks
    norms = torch.stack([write.double().pow(2).sum(dim=0) for write in writes])  # (n, f)
    return moments.gram.diagonal(dim1=1, dim2=2) * norms / moments.tokens  # (n, f)


def removal_orders(moments: Moments, writes: Sequence[Tensor], *, stop: int, ridge: float = RIDGE) -> dict[str, Tensor]:
    """For each way of choosing, every block's units in the order the block gives them up: all of them for
    `top_share` and `energy`, and all but `stop` for `obs`."""
    # writes: (d, f) for each of n blocks
    orders = {"top_share": moments.top.argsort(dim=1, stable=True).cpu(),  # (n, f)
              "energy": unit_energy(moments, writes).argsort(dim=1, stable=True).cpu()}  # (n, f)
    orders["obs"] = torch.stack([obs_order(moments.gram[block], writes[block].T, stop=stop, ridge=ridge)
                                 for block in range(len(writes))])  # (n, f - stop)
    return orders  # (n, f), (n, f) and (n, f - stop)


def kept_units(order: Tensor, units: int, width: int) -> Tensor:
    """The units a block keeps at `width`, ascending, when it gives its units up in `order`."""
    # order: (m,), m at least f - width
    if units - width > len(order):
        raise ValueError(f"The order names {len(order)} units to give up, fewer than the {units - width} that width {width} needs.")
    keep = torch.ones(units, dtype=torch.bool)  # (f,)
    keep[order[:units - width]] = False
    return keep.nonzero().squeeze(1)  # (k,)


def refit_writes(gram: Tensor, write: Tensor, kept: Tensor, *, ridge: float = RIDGE) -> Tensor:
    """The kept units' write vectors that rebuild the block's whole write with the least squared error over the
    calibration tokens."""
    # gram: (f, f); write: (d, f); kept: (k,)
    kept = kept.to(gram.device)
    target = gram[kept] @ write.T.to(gram.dtype)  # (k, d)
    return torch.linalg.solve(_damped(gram[kept][:, kept], gram, ridge), target).T  # (d, k)


def write_error(gram: Tensor, write: Tensor, kept: Tensor, kept_writes: Tensor) -> float:
    """The summed squared error over the calibration tokens of a block's write rebuilt from its kept units."""
    # gram: (f, f); write: (d, f); kept: (k,); kept_writes: (d, k)
    difference = write.to(gram.dtype).clone()  # (d, f)
    difference[:, kept.to(gram.device)] -= kept_writes.to(gram.dtype)
    return float(torch.einsum("df,fg,dg->", difference, gram, difference))


def resized(model: nn.Module, kept: Sequence[Tensor], writes: Sequence[Tensor] | None = None) -> nn.Module:
    """A copy of `model` whose blocks hold only their `kept` units, with `writes` for the kept units' write vectors
    when given."""
    # kept: (k,) for each block; writes: (d, k) for each block
    smaller = copy.deepcopy(model)
    for block, layer in enumerate(transformer_blocks(smaller)):
        resize_block(layer, kept[block], None if writes is None else writes[block])
    return smaller


def resize_block(layer: nn.Module, kept: Tensor, write: Tensor | None = None) -> None:
    """Cut one block, in place, to its `kept` units, with `write` for their write vectors when given."""
    # kept: (k,); write: (d, k)
    projection, down = layer.ffn[PROJECTION_INDEX], layer.ffn[DOWN_PROJECTION_INDEX]
    assert projection.bias is None and down.bias is None and projection.out_features == 2 * down.in_features
    weight = down.weight  # (d, f)
    chosen = kept.to(weight.device)  # (k,)
    rows = torch.cat([chosen, down.in_features + chosen])  # (2k,), the gate rows then the up rows
    new_projection = nn.Linear(projection.in_features, len(rows), bias=False, device=weight.device, dtype=weight.dtype)
    new_down = nn.Linear(len(chosen), down.out_features, bias=False, device=weight.device, dtype=weight.dtype)
    with torch.no_grad():
        new_projection.weight.copy_(projection.weight[rows])
        new_down.weight.copy_(weight[:, chosen] if write is None else write.to(weight))
    new_projection.weight.requires_grad_(projection.weight.requires_grad)
    new_down.weight.requires_grad_(weight.requires_grad)
    layer.ffn[PROJECTION_INDEX], layer.ffn[DOWN_PROJECTION_INDEX] = new_projection, new_down


class _Reached(Exception):
    """Raised by a hook to end a forward pass once the block it reads has run."""


def _first(output: object) -> Tensor:
    return output[0] if isinstance(output, tuple) else output  # (b, l, d) or (b, l, f), the module's tensor output


@torch.inference_mode()
def sequential_set(model: nn.Module, sequences: Sequence[str], device: torch.device, *, width: int, token_budget: int,
                   ridge: float = RIDGE, limit: int | None = None, log: Callable[[str], None] = print) -> tuple[Variant, list[float]]:
    """A fixed set built block by block from the first, and the seconds each block took.

    The model resized so far reads the calibration proteins up to the block. The block's target is the write that would
    make the stream leaving it the intact model's, which is its own write plus what the earlier blocks' cuts changed:
    T = write + c (X_intact - X_resized), c the block's residual scale. Optimal brain surgeon chooses the units on the
    block's own activations against that target, and the kept units' write vectors are its least-squares fit.
    `limit` stops after that many blocks, for a pilot."""
    student = copy.deepcopy(model)
    intact, layers = transformer_blocks(model), transformer_blocks(student)
    units = layers[0].ffn[DOWN_PROJECTION_INDEX].in_features
    ordered = sorted(sequences, key=len)
    lengths = np.array([len(sequence) for sequence in ordered], dtype=np.int64)  # (p,)
    chosen = readout_positions(lengths)
    batches = []
    for batch in length_batches(lengths, token_budget):
        input_ids, attention_mask, _ = encode_batch(model.tokenizer, ordered[batch], device)  # (b, l) each
        positions = column_mask(chosen[batch], tuple(input_ids.shape)).to(device)  # (b, l)
        batches.append((input_ids.masked_fill(positions, model.tokenizer.mask_token_id), attention_mask))
    kept, writes, seconds = [], [], []
    for block in range(len(layers) if limit is None else limit):
        started = time.perf_counter()
        seen: dict[str, Tensor] = {}

        def keep(name: str, stop: bool = False) -> Callable[[nn.Module, tuple[object, ...], object], None]:
            def hook(module: nn.Module, args: tuple[object, ...], output: object) -> None:
                seen[name] = _first(output)
                if stop:
                    raise _Reached
            return hook

        handles = [intact[block].register_forward_hook(keep("intact", stop=True)),
                   layers[block].ffn[SWIGLU_INDEX].register_forward_hook(keep("product")),
                   layers[block].ffn[DOWN_PROJECTION_INDEX].register_forward_hook(keep("write")),
                   layers[block].register_forward_hook(keep("resized", stop=True))]
        gram = torch.zeros(units, units, dtype=torch.float64, device=device)  # (f, f)
        cross = torch.zeros(units, layers[block].ffn[DOWN_PROJECTION_INDEX].out_features, dtype=torch.float64, device=device)  # (f, d)
        try:
            for masked, attention_mask in batches:
                for reader in (model, student):
                    with suppress(_Reached):  # the hook ends the pass once the block it reads has run
                        reader(input_ids=masked, attention_mask=attention_mask)
                real = attention_mask.bool()  # (b, l)
                product = seen["product"][real].float()  # (t_batch, f)
                change = seen["intact"][real].float() - seen["resized"][real].float()  # (t_batch, d)
                target = seen["write"][real].float() + float(layers[block].scaling_factor) * change  # (t_batch, d)
                gram += (product.T @ product).double()
                cross += (product.T @ target).double()
        finally:
            for handle in handles:
                handle.remove()
        order = obs_order(gram, torch.linalg.solve(_damped(gram, gram, ridge), cross), stop=width, ridge=ridge)
        units_kept = kept_units(order, units, width)  # (k,)
        index = units_kept.to(device)
        write = torch.linalg.solve(_damped(gram[index][:, index], gram, ridge), cross[index]).T  # (d, k)
        resize_block(layers[block], units_kept, write)
        kept.append(units_kept)
        writes.append(write.float().cpu())
        seconds.append(time.perf_counter() - started)
        log(f"prune-sequential block {block}: {width} of {units} units in {seconds[-1]:.1f} s")
    return Variant("obs_sequential", "refit", width, torch.stack(kept), torch.stack(writes)), seconds


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def matched_width(model: nn.Module, budget: int) -> int:
    """The largest width, the same in every block, at which the resized model holds at most `budget` parameters."""
    layers = transformer_blocks(model)
    down = layers[0].ffn[DOWN_PROJECTION_INDEX]
    a_unit = 3 * down.out_features * len(layers)  # the parameters one unit of width holds across the blocks
    excess = parameter_count(model) - budget
    return down.in_features - max(0, -(-excess // a_unit))


def residue_owners(chosen: Sequence[np.ndarray]) -> np.ndarray:
    """The protein of every masked residue, in the order `masked_distributions` returns them."""
    # chosen: (s_protein,) 0-based residues for each protein
    return np.concatenate([np.full(len(residues), protein, dtype=np.int64) for protein, residues in enumerate(chosen)])  # (s,)


def residue_losses(log_probs: Tensor, truth: Tensor) -> np.ndarray:
    """The loss at every masked residue."""
    # log_probs: (s, v); truth: (s,)
    return (-log_probs.gather(1, truth.unsqueeze(1)).squeeze(1)).float().numpy()  # (s,)


def read_model(model: nn.Module, sequences: Sequence[str], chosen: Sequence[np.ndarray], clean: Tensor, truth: Tensor,
               device: torch.device, *, token_budget: int) -> tuple[dict[str, float], np.ndarray]:
    """A model's loss, accuracy and KL from `clean` at the chosen residues, and its loss at each of them."""
    # chosen: (s_protein,) 0-based residues for each protein; clean: (s, v); truth: (s,)
    log_probs, _ = masked_distributions(model, list(sequences), chosen, device, token_budget=token_budget)  # (s, v)
    return readout(log_probs, truth, clean), residue_losses(log_probs, truth)  # metrics, (s,)


def unit_table(moments: Moments, writes: Sequence[Tensor], orders: Mapping[str, Tensor]) -> pd.DataFrame:
    """Every unit's calibration statistics and the step at which each order gives it up, -1 when it never does."""
    # writes: (d, f) for each of n blocks; orders: (n, f) or (n, f - stop) for each order
    blocks, units = moments.top.shape
    columns = {"block": np.repeat(np.arange(blocks), units), "unit": np.tile(np.arange(units), blocks),
               "top_share": (moments.top / moments.tokens).cpu().numpy().ravel(),
               "open_rate": (moments.open / moments.tokens).cpu().numpy().ravel(),
               "energy": unit_energy(moments, writes).cpu().numpy().ravel()}
    for name, order in orders.items():
        step = torch.full((blocks, units), -1, dtype=torch.long)  # (n, f)
        step.scatter_(1, order, torch.arange(order.shape[1]).expand(blocks, -1))
        columns[f"step_{name}"] = step.numpy().ravel()
    return pd.DataFrame(columns)


def run_static(model: nn.Module, reference: nn.Module, calibration: Sequence[str], readouts: Mapping[str, Sequence[str]],
               device: torch.device, *, widths: Sequence[int] = WIDTHS, token_budget: int, limit: int | None = None,
               log: Callable[[str], None] = print) -> StaticRun:
    """Every fixed set of units (order, repair and width, with the width matched to `reference`'s parameters) read on
    the masked residues of each split of `readouts`, beside the intact `model` and `reference`. `limit` stops after
    that many fixed sets, for a pilot."""
    layers = transformer_blocks(model)
    units = layers[0].ffn[DOWN_PROJECTION_INDEX].in_features
    matched = matched_width(model, parameter_count(reference))
    widths = sorted({width for width in widths if width < units} | {matched})
    chosen = {split: readout_positions(np.array([len(sequence) for sequence in sequences], dtype=np.int64))
              for split, sequences in readouts.items()}
    clean, truth, rows = {}, {}, []
    residues = {split: {"protein": residue_owners(positions)} for split, positions in chosen.items()}

    def read(name: str, subject: nn.Module, facts: dict[str, object], started: float, keep: bool) -> None:
        for split, sequences in readouts.items():
            scores, losses = read_model(subject, sequences, chosen[split], clean[split], truth[split], device, token_budget=token_budget)
            rows.append({"model": name, **facts, "split": split, "parameters": parameter_count(subject),
                         "seconds": time.perf_counter() - started, **scores})
            if keep:
                residues[split][name] = losses
        log(f"prune-static {name} {facts}: " + ", ".join(f"{row['split']} loss {row['loss']:.4f}" for row in rows[-len(readouts):]))

    for split, sequences in readouts.items():
        clean[split], truth[split] = masked_distributions(model, list(sequences), chosen[split], device, token_budget=token_budget)
        residues[split]["truth"] = truth[split].numpy()
    whole = {"order": "none", "repair": "none"}
    read("esmc_600", model, {**whole, "width": units}, time.perf_counter(), True)
    read("esmc_300", reference, {**whole, "width": transformer_blocks(reference)[0].ffn[DOWN_PROJECTION_INDEX].in_features},
         time.perf_counter(), True)

    started = time.perf_counter()
    moments = collect_moments(model, calibration, device, token_budget=token_budget)
    log(f"prune-static moments: {moments.tokens} tokens of {len(calibration)} proteins in {time.perf_counter() - started:.0f} s")
    started = time.perf_counter()
    writes = write_vectors(model)
    orders = removal_orders(moments, writes, stop=min(widths))
    log(f"prune-static orders in {time.perf_counter() - started:.0f} s")
    conditions = [(width, order, repair) for width in widths for order in ORDERS for repair in REPAIRS
                  if not (order == "obs" and repair == "none")]
    # The matched width is read first, so that a run cut short still holds what E16b starts from.
    conditions.sort(key=lambda condition: condition[0] != matched)
    variants = []
    for width, order, repair in conditions[:limit]:
        started = time.perf_counter()
        kept = [kept_units(orders[order][block], units, width) for block in range(len(layers))]  # n of (k,)
        new_writes = None
        if repair == "refit":
            new_writes = [refit_writes(moments.gram[block], writes[block], kept[block]) for block in range(len(layers))]  # n of (d, k)
        smaller = resized(model, kept, new_writes)
        read(f"{order}_{repair}_{width}", smaller, {"order": order, "repair": repair, "width": width}, started, width == matched)
        del smaller
        if width == matched:
            variants.append(Variant(order, repair, width, torch.stack(kept),
                                    None if new_writes is None else torch.stack(new_writes).float().cpu()))
    return StaticRun(pd.DataFrame(rows), {split: pd.DataFrame(columns) for split, columns in residues.items()},
                     unit_table(moments, writes, orders), variants, matched, moments.tokens)
