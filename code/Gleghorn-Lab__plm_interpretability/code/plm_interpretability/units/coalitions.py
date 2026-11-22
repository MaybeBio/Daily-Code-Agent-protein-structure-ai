"""E14c: are the dictionary latents that copy no single pole small groups of poles that fire together?

Tigges and colleagues (Goodfire, 2026), after Shabalin and Piotrowski, report that the features of a language model's
transcoders that do not copy one neuron are mostly sparse sums of 2 to 64 neurons that fire with the feature. The
dictionary test (`dictionary`) measures the copies at ESMC's two sites; this module measures the groups, from activity
alone. Each latent of the SAE on a block's feed-forward write is fit with 1, 2, 4, up to 64 of the block's native poles
by greedy forward selection (orthogonal matching pursuit on the poles' correlations) over half of the residues, and the
fit's correlation with the latent is read on the other half, whole proteins apart. A fit of one pole is the dictionary
test's copy. The same fits on the poles of a Haar rotation of the units give the chance level: the rotated poles span
the same activity, so whatever the native poles add comes from the basis.

Every fit and reading works from sums over residues (`dictionary.CorrelationAccumulator`): the latents' covariances with
the poles and the poles' with one another, one set per half, so no activation is stored.

Symbols: r residues; m latents; p poles; b latents fit at once; k poles in a fit; s fit sizes; f units.
"""

from __future__ import annotations

import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Sequence
from torch import Tensor, nn

from foundry.embedding import encode_topk
from foundry.pilot import Pilot
from .atlas import encode_batch, length_batches, transformer_units
from .atlas_set import SUBSET_SEED, residue_budget_proteins
from .capture import BlockReader, BlockStates
from .dictionary import CorrelationAccumulator, copy_report
from .passes import CONTROL_SEED, DICTIONARY_RESIDUES, DICTIONARY_TOKEN_BUDGET, PassInputs
from .poles import sign_poles, swiglu_poles
from .rotations import haar_rotation, rotate


SIZES = (1, 2, 4, 8, 16, 32, 64)
THRESHOLDS = (0.5, 0.7, 0.9)  # the dictionary test's
RIDGE = 1e-8  # added to the chosen poles' correlation matrix, so two poles that always fire together do not stop a fit
BASES = ("native", "rotation")
HALVES = ("fit", "held_out")  # batches alternate between them, so a protein's residues fall in one
FIT_CHUNK = 256  # latents fit at once: their rows of the poles' correlations take 64 * p * 8 bytes each


def greedy_poles(correlation: Tensor, gram: Tensor, valid: Tensor, steps: int, ridge: float = RIDGE) -> tuple[Tensor, Tensor]:
    """Forward selection of `steps` poles for each latent: at each step the pole most correlated with what the poles
    chosen so far leave unexplained joins them, and the latent is fit again by least squares on all of them. Returns
    the poles in the order chosen and, in row t, the standardized coefficients of the fit on the first t + 1."""
    # correlation: (b, p), each latent with each pole; gram: (p, p), the poles with one another; valid: (p,) bool
    latents, poles = correlation.shape
    if steps > int(valid.sum()):
        raise ValueError(f"{steps} poles cannot be chosen from {int(valid.sum())} that vary.")
    chosen = torch.zeros((latents, steps), dtype=torch.int64, device=correlation.device)  # (b, k)
    coefficients = torch.zeros((latents, steps, steps), dtype=correlation.dtype, device=correlation.device)  # (b, k, k)
    rows = torch.zeros((latents, steps, poles), dtype=correlation.dtype, device=correlation.device)  # (b, k, p)
    available = valid[None].repeat(latents, 1)  # (b, p)
    identity = torch.eye(steps, dtype=correlation.dtype, device=correlation.device)  # (k, k)
    for step in range(steps):
        fitted = torch.einsum("bt,btp->bp", coefficients[:, step - 1, :step], rows[:, :step]) if step else 0.0  # (b, p)
        unexplained = torch.where(available, (correlation - fitted).abs(), torch.full_like(correlation, -1.0))  # (b, p)
        pole = unexplained.argmax(dim=1)  # (b,)
        chosen[:, step] = pole
        available.scatter_(1, pole[:, None], False)
        rows[:, step] = gram[pole]
        picked = chosen[:, :step + 1]  # (b, t)
        among = rows[:, :step + 1].gather(2, picked[:, None, :].expand(-1, step + 1, -1))  # (b, t, t)
        target = correlation.gather(1, picked)  # (b, t)
        coefficients[:, step, :step + 1] = torch.linalg.solve(among + ridge * identity[:step + 1, :step + 1], target)
    return chosen, coefficients  # (b, k), (b, k, k)


def fit_correlations(correlation: Tensor, chosen: Tensor, coefficients: Tensor, sizes: Sequence[int] = SIZES) -> Tensor:
    """Each fit's multiple correlation with its latent on the residues it was fit on, at each size."""
    # correlation: (b, p); chosen: (b, k); coefficients: (b, k, k)
    explained = [(coefficients[:, size - 1, :size] * correlation.gather(1, chosen[:, :size])).sum(dim=1) for size in sizes]
    return torch.stack(explained, dim=1).clamp(min=0).sqrt()  # (b, s)


def held_out_correlations(chosen: Tensor, coefficients: Tensor, fit_deviation: Tensor, covariance: Tensor,
                          pole_covariance: Tensor, latent_deviation: Tensor, sizes: Sequence[int] = SIZES) -> Tensor:
    """Each fit's correlation with its latent on residues it was not fit on, at each size: the fitted sum of poles,
    with the coefficients the fit half gave, against the latent, from the other half's covariances. Zero where the
    latent or the sum never varies there."""
    # chosen: (b, k); coefficients: (b, k, k), standardized on the fit half; fit_deviation: (p,), the poles' there;
    # covariance: (b, p), latents with poles on the held-out half; pole_covariance: (p, p) and latent_deviation: (b,) there
    readings = []
    for size in sizes:
        picked = chosen[:, :size]  # (b, t)
        weights = coefficients[:, size - 1, :size] / fit_deviation[picked]  # (b, t), per unit of raw activation
        shared = (weights * covariance.gather(1, picked)).sum(dim=1)  # (b,)
        among = pole_covariance[picked[:, :, None], picked[:, None, :]]  # (b, t, t)
        spread = torch.einsum("bi,bij,bj->b", weights, among, weights).clamp(min=0).sqrt()  # (b,)
        scale = latent_deviation * spread  # (b,)
        readings.append(torch.where(scale > 0, shared / scale.clamp(min=1e-300), torch.zeros_like(shared)))
    return torch.stack(readings, dim=1)  # (b, s)


def smallest_sizes(correlations: np.ndarray, threshold: float, sizes: Sequence[int] = SIZES) -> np.ndarray:
    """Per latent, the smallest fit size whose correlation reaches the threshold, 0 where none does."""
    # correlations: (m, s)
    reached = np.nan_to_num(correlations, nan=-1.0) >= threshold  # (m, s)
    return np.where(reached.any(axis=1), np.asarray(sizes)[reached.argmax(axis=1)], 0)  # (m,)


def mass_shares(mass: np.ndarray, smallest: np.ndarray, sizes: Sequence[int] = SIZES) -> dict[int, float]:
    """The share of the dictionary's activity on latents a fit of at most each size reaches."""
    # mass, smallest: (m,)
    total = float(mass.sum())
    if total <= 0:
        raise ValueError("The dictionary never fired on the sampled residues.")
    return {size: float(mass[(smallest > 0) & (smallest <= size)].sum()) / total for size in sizes}


def _fit_basis(cross: dict[str, CorrelationAccumulator], pairs: dict[str, CorrelationAccumulator], alive: Tensor,
               chunk: int) -> tuple[Tensor, Tensor, Tensor]:
    """Every living latent's fits in one basis: the poles chosen, and the fits' correlations on each half."""
    # alive: (m_alive,) latent indices
    pole_fit, fit_deviation, _ = pairs["fit"].moments()  # (p, p), (p,)
    pole_held, _, _ = pairs["held_out"].moments()  # (p, p)
    valid = fit_deviation > 0  # (p,)
    scale = torch.outer(fit_deviation, fit_deviation)  # (p, p)
    gram = torch.where(scale > 0, pole_fit / scale.clamp(min=1e-300), torch.zeros_like(pole_fit))  # (p, p)
    del pole_fit, scale
    steps = max(SIZES)
    poles, fitted, held = [], [], []
    for start in range(0, len(alive), chunk):
        rows = alive[start:start + chunk]  # (b,)
        covariance, latent_deviation, _ = cross["fit"].moments(rows)  # (b, p), (b,)
        scale = torch.outer(latent_deviation, fit_deviation)  # (b, p)
        correlation = torch.where(scale > 0, covariance / scale.clamp(min=1e-300), torch.zeros_like(covariance))  # (b, p)
        chosen, coefficients = greedy_poles(correlation, gram, valid, steps)
        covariance_held, deviation_held, _ = cross["held_out"].moments(rows)  # (b, p), (b,)
        poles.append(chosen.cpu())
        fitted.append(fit_correlations(correlation, chosen, coefficients).cpu())
        held.append(held_out_correlations(chosen, coefficients, fit_deviation, covariance_held, pole_held, deviation_held).cpu())
    return torch.cat(poles), torch.cat(fitted), torch.cat(held)  # (m_alive, k), (m_alive, s), (m_alive, s)


def run_coalitions(
    model: nn.Module,
    sae: nn.Module,
    block: int,
    inputs: PassInputs,
    device: torch.device,
    *,
    residues: int = DICTIONARY_RESIDUES,
    token_budget: int = DICTIONARY_TOKEN_BUDGET,
    chunk: int = FIT_CHUNK,
    pilot: Pilot | None = None,
    log: Callable[[str], None] = print,
) -> tuple[pd.DataFrame | None, dict[str, object]]:
    """E14c at one block, for the SAE on its feed-forward write, over the dictionary test's residues.

    The pass sums, for each half and basis, the latents' products with the poles and the poles' with one another, in
    float32; every moment is then formed in float64. Returns one row per latent (its activity, the native poles chosen
    for it, and its fits' correlations by basis and half) and the receipt, whose `copy_shares` are the dictionary
    test's shares recomputed over both halves, for the stage to hold against E8's. Under a pilot only its window
    streams and no table is returned.
    """
    proteins = residue_budget_proteins(inputs.frame, residues, seed=SUBSET_SEED).ordered()
    lengths = proteins.lengths  # (n,)
    units = transformer_units(model)
    latents = int(sae.params.codebook_dim)
    control = haar_rotation(units, CONTROL_SEED, dtype=torch.float32, device=device)  # (f, f)
    cross = {basis: {half: CorrelationAccumulator(latents, 2 * units, device, torch.float32) for half in HALVES}
             for basis in BASES}
    pairs = {basis: {half: CorrelationAccumulator(2 * units, 2 * units, device, torch.float32) for half in HALVES}
             for basis in BASES}
    half = HALVES[0]
    seen = 0

    def consume(states: BlockStates) -> None:
        nonlocal seen
        activity = {"native": swiglu_poles(states.gate, states.up).main(),
                    "rotation": sign_poles(rotate(states.product(), control))}  # (r, 2f) each
        codes = encode_topk(states.write, sae)  # indices, values: (r, k)
        for basis, poles in activity.items():
            cross[basis][half].update_codes(codes.indices, codes.values, poles)
            pairs[basis][half].update(poles, poles)
        seen += int(states.gate.shape[0])

    batches = length_batches(lengths, token_budget)
    started = time.time()
    with BlockReader(model, [block], consume, write_blocks=[block]) as reader:
        indices = range(len(batches))
        for index in pilot.watch(indices) if pilot is not None else indices:
            half = HALVES[index % 2]
            input_ids, attention_mask, residue_mask = encode_batch(model.tokenizer, proteins.sequence[batches[index]], device)
            reader.run(input_ids, attention_mask, residue_mask)
    receipt: dict[str, object] = {"block": block, "proteins": len(lengths), "residues": seen, "pass_seconds": time.time() - started,
                                  "complete": seen == int(lengths.sum()), "sizes": list(SIZES),
                                  "half_residues": {name: cross["native"][name].count for name in HALVES}}
    if not receipt["complete"]:
        return None, receipt
    started = time.time()
    varies = [(cross["native"][name].latent_square > 0) for name in HALVES]  # (m,) each: a nonnegative latent that fired
    alive = torch.nonzero(varies[0] & varies[1]).reshape(-1)  # (m_alive,)
    columns: dict[str, object] = {"latent": np.arange(latents)}
    for basis in BASES:
        poles, fitted, held = _fit_basis(cross[basis], pairs[basis], alive, chunk)
        for name, values in (("fit", fitted), ("held_out", held)):
            full = np.full((latents, len(SIZES)), np.nan)  # (m, s)
            full[alive.cpu().numpy()] = values.numpy()
            columns.update({f"{basis}_{name}_{size}": full[:, position] for position, size in enumerate(SIZES)})
        if basis == "native":
            chosen = np.full((latents, max(SIZES)), -1, dtype=np.int64)  # (m, k)
            chosen[alive.cpu().numpy()] = poles.numpy()
            columns["native_poles"] = list(chosen)
        log(f"{basis}: {len(alive)} latents fit")
    receipt["fit_seconds"] = time.time() - started
    whole = cross["native"]["fit"]
    whole.absorb(cross["native"]["held_out"])
    copies = copy_report(whole, THRESHOLDS)
    mass = whole.mass.double().cpu().numpy()  # (m,)
    columns.update(mass=mass, best_correlation=copies.best_correlation.cpu().numpy())
    frame = pd.DataFrame(columns)
    receipt.update(latents=latents, alive=int(len(alive)), copy_shares={str(threshold): share for threshold, share in copies.shares.items()})
    return frame, receipt


def concept_latents(per_concept: pd.DataFrame, sae_arm: str, unit_arm: str, frame: pd.DataFrame, *, threshold: float = 0.7,
                    cut: float = 0.5, sizes: Sequence[int] = SIZES) -> dict[str, object]:
    """E13's concepts that the SAE reads (its best validation latent's test F1 above `cut`), apart by whether the
    block's units read them too: per group, the concepts by the smallest held-out fit of native poles, and of rotated
    poles, that reaches each concept's SAE latent at `threshold`."""
    # per_concept: E13's table of one plan, a row per arm and concept with `best_feature` and `best_test_f1`
    by_arm = {arm: rows.set_index("concept") for arm, rows in per_concept.groupby("arm")}
    latents, units = by_arm[sae_arm], by_arm[unit_arm].reindex(by_arm[sae_arm].index)
    read = (latents["best_test_f1"] > cut) & (latents["best_feature"] >= 0)
    shared = read & (units["best_test_f1"] > cut)
    smallest = {basis: smallest_sizes(frame[[f"{basis}_held_out_{size}" for size in sizes]].to_numpy(), threshold, sizes)
                for basis in BASES}  # (m,) each
    groups: dict[str, object] = {}
    for name, members in (("sae_only", read & ~shared), ("shared", shared)):
        chosen = latents.loc[members, "best_feature"].to_numpy()  # (concepts,)
        groups[name] = {"concepts": int(members.sum()), "distinct_latents": int(len(np.unique(chosen))),
                        **{basis: {"reached_by_size": {str(size): int((smallest[basis][chosen] == size).sum()) for size in sizes},
                                   "unreached": int((smallest[basis][chosen] == 0).sum())} for basis in BASES}}
    return groups


def coalition_report(frame: pd.DataFrame, thresholds: Sequence[float] = THRESHOLDS, sizes: Sequence[int] = SIZES) -> dict[str, object]:
    """The readings of one site: at each threshold and basis, the share of the dictionary's activity on latents that a
    held-out fit of at most each size reaches, and the latents by the smallest size that reaches them."""
    mass = frame["mass"].to_numpy()  # (m,)
    report: dict[str, object] = {}
    for threshold in thresholds:
        entry: dict[str, object] = {}
        for basis in BASES:
            held = frame[[f"{basis}_held_out_{size}" for size in sizes]].to_numpy()  # (m, s)
            smallest = smallest_sizes(held, threshold, sizes)  # (m,)
            entry[basis] = {"mass_share": {str(size): share for size, share in mass_shares(mass, smallest, sizes).items()},
                            "latents": {str(size): int((smallest == size).sum()) for size in sizes},
                            "unreached_latents": int((smallest == 0).sum())}
        report[str(threshold)] = entry
    return report
