"""E7's ablation runs: does ESMC use the units we label, read through its own masked-token prediction.

H6 (preregistration, `hypotheses`): the labeled poles of ESMC-600's block 26, native poles whose dominant local term is
also one of their selected local labels (at most 200, drawn with a seed), are each set to their non-firing mean wherever
they fire inside that term's intervals, on up to 16 held-out proteins carrying the term with up to eight of its residues
masked. The drop in the masked residues' log probability is set against the drops of ten placebo poles of the same block,
those whose ablation removes the activation mass closest to the labeled pole's at the same residues (log scale), poles
labeled with the same term excluded (`causal.pole_ablation`); the labeled pole's ablation is also read at up to eight
masked residues outside the term, its in-distribution cost. The secondary weak-against-strong test zeroes, network-wide,
each unit's weakest 75% of activations by magnitude, or its strongest activations carrying the same total magnitude, and
reads masked-token loss and accuracy on held-out proteins (`causal.activation_removal`; Cammarata, Goodfire, 2026).

Symbols: n proteins; b proteins of a batch; l token columns; r residues; s masked residues; f units; p poles, 2f.
"""

from __future__ import annotations

import time
import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Sequence
from contextlib import nullcontext
from torch import Tensor, nn

from foundry.pilot import Pilot
from .atlas import TOKEN_BUDGET, calibration_states, encode_batch, length_batches, residue_sample
from .capture import BlockReader, BlockStates
from .causal import PoleTarget, activation_removal, magnitude_thresholds, masked_readout, pole_ablation, transformer_blocks
from .poles import pole_unit


LABELED_POLES = 200
PROTEINS_PER_POLE = 16
MIN_PROTEINS = 4
MASKED_PER_PROTEIN = 8
PLACEBOS = 10
HELD_OUT = ("validation", "test")
SEED = 24895
WEAKEST = 0.75
THRESHOLD_RESIDUES = 65_536
READOUT_PROTEINS = 1_000
MASK_SHARE = 0.15


def labeled_poles(labels: pd.DataFrame, scores: pd.DataFrame, *, limit: int = LABELED_POLES, seed: int = SEED) -> pd.DataFrame:
    """The poles H6 ablates, with their term: poles whose dominant local term is also one of their selected local
    labels; at most `limit`, drawn with `seed`, in pole order."""
    # labels: pole, term (the pass's selected local pairs); scores: pole, best_local_term, dominant
    dominant = scores.loc[scores["dominant"], ["pole", "best_local_term"]].rename(columns={"best_local_term": "term"})
    chosen = dominant.merge(labels[["pole", "term"]].drop_duplicates(), on=["pole", "term"]).sort_values("pole")
    if len(chosen) > limit:
        chosen = chosen.iloc[np.sort(np.random.default_rng(seed).choice(len(chosen), size=limit, replace=False))]
    return chosen.reset_index(drop=True)


def term_intervals(row: pd.Series, term: int) -> list[tuple[int, int]]:
    """A local term's intervals in one protein, 0-based and inclusive, clipped to its observed residues."""
    length = len(row["sequence"])
    return [(int(start) - 1, min(int(end), length) - 1)
            for token, start, end in zip(row["local_term_ids"], row["local_starts"], row["local_ends"], strict=True)
            if int(token) == term and int(start) <= length]


def held_out_carriers(proteins: pd.DataFrame) -> dict[int, list[int]]:
    """Each local term's held-out proteins, as positions in `proteins`."""
    carriers: dict[int, list[int]] = {}
    for position, (split, tokens) in enumerate(zip(proteins["split"], proteins["local_term_ids"], strict=True)):
        if split in HELD_OUT:
            for token in set(int(token) for token in tokens):
                carriers.setdefault(token, []).append(position)
    return carriers


def ablation_sites(
    intervals: Sequence[list[tuple[int, int]]], lengths: Sequence[int], *, masked: int, seed: int,
) -> tuple[list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    """Per protein, every residue inside the term's intervals (where ablation applies), a seeded subset of at most
    `masked` of them (the residues masked and read), and a seeded subset of at most `masked` residues outside them (the
    in-distribution readout)."""
    generator = np.random.default_rng(seed)
    regions, inside, outside = [], [], []
    for ranges, length in zip(intervals, lengths, strict=True):
        region = np.unique(np.concatenate([np.arange(start, end + 1) for start, end in ranges]))  # (r_protein,)
        rest = np.setdiff1d(np.arange(length), region)  # (o_protein,)
        regions.append(region)
        inside.append(np.sort(generator.choice(region, size=min(masked, len(region)), replace=False)))  # (s_protein,)
        outside.append(np.sort(generator.choice(rest, size=min(masked, len(rest)), replace=False)))  # (s_protein,)
    return regions, inside, outside  # (r_protein,), (s_protein,), (s_protein,) for each of b proteins


def column_mask(residues: Sequence[np.ndarray], shape: tuple[int, int]) -> Tensor:
    """A (b, l) mask of the given 0-based residues of each protein, shifted past the BOS token."""
    # residues: (r_protein,) for each of b proteins
    mask = torch.zeros(shape, dtype=torch.bool)  # (b, l)
    for row, chosen in enumerate(residues):
        mask[row, torch.from_numpy(chosen + 1)] = True
    return mask  # (b, l)


def removed_mass(states: BlockStates, values: Tensor) -> Tensor:
    """For every pole, the activation mass its ablation would remove at these residues: the sum, where it fires, of
    |z - value|."""
    # values: (p,)
    is_open = states.gate > 0  # (r, f)
    fires = torch.cat((is_open & (states.up > 0), is_open & (states.up < 0)), dim=1)  # (r, p)
    product = states.product().double()  # (r, f)
    gap = (torch.cat((product, product), dim=1) - values.to(product.device).double()).abs()  # (r, p)
    return (gap * fires).sum(dim=0)  # (p,)


def matched_placebos(removed: Tensor, pole: int, excluded: Sequence[int], *, count: int = PLACEBOS, seed: int = SEED) -> list[int]:
    """The `count` poles whose removed mass is closest to `pole`'s on a log scale, among poles that remove some mass and
    are neither `pole` nor `excluded`; ties fall to a seeded order."""
    # removed: (p,)
    mass = removed.double().cpu().numpy()  # (p,)
    candidates = np.flatnonzero(mass > 0)  # (c,)
    candidates = candidates[~np.isin(candidates, [pole, *excluded])]  # (c,)
    distance = np.abs(np.log(mass[candidates]) - np.log(mass[pole]))  # (c,)
    order = np.lexsort((np.random.default_rng(seed).random(len(candidates)), distance))  # (c,)
    return [int(candidate) for candidate in candidates[order[:count]]]


def ablate_pole(
    model: nn.Module,
    block: int,
    pole: int,
    term: int,
    sequences: Sequence[str],
    intervals: Sequence[list[tuple[int, int]]],
    values: Tensor,
    excluded: Sequence[int],
    device: torch.device,
    *,
    seed: int = SEED,
) -> dict[str, object]:
    """One labeled pole against its placebos on one set of proteins carrying its term; the labeled pole's ablation is
    also read at masked residues outside the term (`outside_drop`), the in-distribution cost."""
    # values: (p,), each pole's non-firing mean
    tokenizer = model.tokenizer
    regions, inside, outside = ablation_sites(intervals, [len(sequence) for sequence in sequences], masked=MASKED_PER_PROTEIN,
                                              seed=seed + pole)
    input_ids, attention_mask, _ = encode_batch(tokenizer, sequences, device)  # (b, l) each
    region = column_mask(regions, tuple(input_ids.shape)).to(device)  # (b, l)
    positions = column_mask(inside, tuple(input_ids.shape)).to(device)  # (b, l)
    away = column_mask(outside, tuple(input_ids.shape)).to(device)  # (b, l)
    clean, _ = masked_readout(model, input_ids, attention_mask, positions, tokenizer.mask_token_id)  # (s,)
    masses: list[Tensor] = []
    with BlockReader(model, [block], lambda states: masses.append(removed_mass(states, values))) as reader:
        reader.run(input_ids.masked_fill(positions, tokenizer.mask_token_id), attention_mask, region)
    removed = masses[0]  # (p,)
    entry: dict[str, object] = {"pole": pole, "term": term, "proteins": len(sequences), "masked": int(positions.sum()),
                                "removed": float(removed[pole])}
    if float(removed[pole]) <= 0:
        return {**entry, "status": "silent"}
    placebos = matched_placebos(removed, pole, excluded, seed=seed + pole)
    width = len(values) // 2
    targets = {}
    for chosen_pole in (pole, *placebos):
        unit, sign = pole_unit(chosen_pole, width)
        targets[chosen_pole] = PoleTarget(block, unit, sign, float(values[chosen_pole]))
    drops = []
    for target in targets.values():
        with pole_ablation(model, [target], region):
            ablated, _ = masked_readout(model, input_ids, attention_mask, positions, tokenizer.mask_token_id)  # (s,)
        drops.append(float((clean - ablated).mean()))
    outside_drop = None
    if bool(away.any()):
        clean_away, _ = masked_readout(model, input_ids, attention_mask, away, tokenizer.mask_token_id)  # (s_away,)
        with pole_ablation(model, [targets[pole]], region):
            ablated_away, _ = masked_readout(model, input_ids, attention_mask, away, tokenizer.mask_token_id)  # (s_away,)
        outside_drop = float((clean_away - ablated_away).mean())
    return {**entry, "status": "tested", "drop": drops[0], "outside_drop": outside_drop, "placebo_poles": placebos,
            "placebo_removed": [float(removed[placebo]) for placebo in placebos], "placebo_drops": drops[1:]}


def run_h6(
    model: nn.Module,
    block: int,
    labels: pd.DataFrame,
    scores: pd.DataFrame,
    proteins: pd.DataFrame,
    values: Tensor,
    device: torch.device,
    *,
    pilot: Pilot | None = None,
    log: Callable[[str], None] = print,
) -> pd.DataFrame:
    """H6 over every labeled pole; a pole with fewer than `MIN_PROTEINS` held-out carriers is kept as `too_few`."""
    # values: (p,), each pole's non-firing mean from calibration
    chosen = labeled_poles(labels, scores)
    carriers = held_out_carriers(proteins)
    same_term = labels.groupby("term")["pole"].apply(list).to_dict()
    rows = []
    indices = range(len(chosen))
    for index in pilot.watch(indices) if pilot is not None else indices:
        pole, term = int(chosen["pole"].iloc[index]), int(chosen["term"].iloc[index])
        positions = [position for position in carriers.get(term, [])
                     if term_intervals(proteins.iloc[position], term)]
        if len(positions) < MIN_PROTEINS:
            rows.append({"pole": pole, "term": term, "proteins": len(positions), "status": "too_few"})
            continue
        generator = np.random.default_rng(SEED + pole)
        picked = np.sort(generator.choice(positions, size=min(PROTEINS_PER_POLE, len(positions)), replace=False))
        frame = proteins.iloc[picked]
        rows.append(ablate_pole(model, block, pole, term, frame["sequence"].tolist(),
                                [term_intervals(row, term) for _, row in frame.iterrows()], values,
                                same_term.get(term, []), device))
        log(f"H6 pole {pole} ({index + 1}/{len(chosen)}): {rows[-1]['status']}")
    return pd.DataFrame(rows)


def readout_positions(lengths: np.ndarray, *, share: float = MASK_SHARE, seed: int = SEED) -> list[np.ndarray]:
    """Per protein, a seeded `share` of its residues (at least one), 0-based, the positions every condition masks."""
    # lengths: (n,)
    generator = np.random.default_rng(seed)
    return [np.sort(generator.choice(length, size=max(1, int(round(share * length))), replace=False))
            for length in lengths]  # n arrays of (s_protein,)


def weak_strong(
    model: nn.Module,
    calibration: Sequence[str],
    held_out: Sequence[str],
    device: torch.device,
    *,
    weakest: float = WEAKEST,
    residues: int = THRESHOLD_RESIDUES,
    token_budget: int = TOKEN_BUDGET,
    log: Callable[[str], None] = print,
) -> dict[str, object]:
    """Masked-token loss and accuracy on `held_out` with the model intact, with each unit's weakest share of activations
    removed in every block, and with its strongest activations of the same total magnitude removed; thresholds come from
    a seeded sample of `residues` calibration residues."""
    blocks = list(range(len(transformer_blocks(model))))
    total = sum(len(sequence) for sequence in calibration)
    states = calibration_states(model, model.tokenizer, calibration, blocks, residue_sample(total, residues, SEED),
                                token_budget=token_budget, device=device)
    lower, upper, shares = {}, {}, {}
    for block in blocks:
        product = states.pop(block).product().to(device)  # (r, f)
        lower[block], upper[block] = (threshold.float() for threshold in magnitude_thresholds(product, weakest))  # (f,) each
        magnitude = product.abs()  # (r, f)
        shares[block] = {"weak": float((magnitude <= lower[block]).float().mean()),
                         "strong": float((magnitude >= upper[block]).float().mean())}
    lengths = np.array([len(sequence) for sequence in held_out], dtype=np.int64)  # (n,)
    chosen = readout_positions(lengths)
    conditions = {"intact": nullcontext, "weak": lambda: activation_removal(model, lower=lower),
                  "strong": lambda: activation_removal(model, upper=upper)}
    readout = {}
    for name, context in conditions.items():
        started = time.time()
        log_probs, correct = [], []
        with context():
            for batch in length_batches(lengths, token_budget):
                input_ids, attention_mask, _ = encode_batch(model.tokenizer, held_out[batch], device)  # (b, l) each
                positions = column_mask(chosen[batch], tuple(input_ids.shape)).to(device)  # (b, l)
                true, hit = masked_readout(model, input_ids, attention_mask, positions, model.tokenizer.mask_token_id)
                log_probs.append(true.cpu())
                correct.append(hit.cpu())
        true_all, hit_all = torch.cat(log_probs), torch.cat(correct)  # (s,), (s,)
        readout[name] = {"loss": float(-true_all.double().mean()), "accuracy": float(hit_all.double().mean()),
                         "masked": len(true_all), "seconds": time.time() - started}
        log(f"{name}: masked-token loss {readout[name]['loss']:.4f}, accuracy {readout[name]['accuracy']:.4f}")
    return {"weakest": weakest, "threshold_residues": residues, "proteins": len(held_out), "readout": readout,
            "removed_share": {"weak": float(np.mean([entry["weak"] for entry in shares.values()])),
                              "strong": float(np.mean([entry["strong"] for entry in shares.values()]))},
            "removed_share_by_block": shares}
