"""E15d, exploratory: does ESMC use the poles that mark a concept when they are removed together.

H6 set one labeled pole of one block to its resting value and found the masked prediction all but unchanged. Shilov and
colleagues (Goodfire, November 2026) report groups of neurons across layers whose joint removal changes a prediction
that survives the removal of any one member, so a single pole's null does not test a group. Here a concept's group is
the pole that E13 chose for it on validation proteins at each block of ESMC-600 where that pole's F1 on test proteins
passes `F1_THRESHOLD` (`retest_esmc/esmc_600_depth`, arm `mlp_native`), at most one pole a block.

On up to `PROTEINS` of InterPLM's test proteins that carry the concept, with up to `MASKED` of its residues masked in
each, every pole of the group is set to zero wherever it fires at the concept's residues, and the fall in the masked
residues' log probability of the true residue is read. It is set against `PLACEBOS` placebo groups, each holding, for
every member, another pole of the same block whose removal takes the nearest activation mass at the same residues
(`ablation.matched_placebos`), against the group's best single pole removed alone, and against the group's removal
read at masked residues outside the concept. A member that never fires at the chosen residues is left out with its
placebos.

Symbols: b proteins; l token columns; r residues of the concept; f units; p poles, 2f.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import scipy.sparse as sp
import torch

from collections.abc import Callable, Sequence
from torch import Tensor, nn

from .ablation import MASKED_PER_PROTEIN, PLACEBOS, ablation_sites, column_mask, matched_placebos, removed_mass
from .atlas import encode_batch
from .capture import BlockReader, BlockStates
from .causal import PoleTarget, masked_readout, pole_ablation
from .poles import pole_unit


ARM = "mlp_native"
F1_THRESHOLD = 0.5
PROTEINS = 16
MIN_PROTEINS = 4
MASKED = MASKED_PER_PROTEIN
MAX_RESIDUES = 2_046
SEED = 24895


def concept_groups(per_concept: pd.DataFrame, *, arm: str = ARM, threshold: float = F1_THRESHOLD) -> dict[str, pd.DataFrame]:
    """Each concept's group: the block and pole column of every row of `arm` whose test F1 passes the threshold."""
    # per_concept: layer, arm, concept, best_feature, best_test_f1
    rows = per_concept[(per_concept["arm"] == arm) & (per_concept["best_test_f1"] > threshold)]
    return {str(concept): group.sort_values("layer")[["layer", "best_feature", "best_test_f1"]].reset_index(drop=True)
            for concept, group in rows.groupby("concept")}


def carriers(labels: sp.csr_matrix, lengths: Sequence[int], column: int) -> dict[int, np.ndarray]:
    """The proteins of one shard that carry a concept, each with its labeled residues, 0-based."""
    # labels: (n, C) over the shard's residues in protein order
    residues = labels[:, [column]].tocoo().row  # (q,) rows with any value for the concept
    offsets = np.concatenate(([0], np.cumsum(lengths)))  # (b + 1,)
    owner = np.searchsorted(offsets, residues, side="right") - 1  # (q,)
    return {int(protein): np.sort(residues[owner == protein] - offsets[protein]) for protein in np.unique(owner)}  # (r,) each


def ablate_group(model: nn.Module, members: pd.DataFrame, sequences: Sequence[str], residues: Sequence[np.ndarray],
                 device: torch.device, *, seed: int) -> dict[str, object]:
    """One concept's group against its placebo groups on one set of carrying proteins."""
    # members: layer, best_feature, best_test_f1; residues: (r,) the concept's 0-based residues for each of b proteins
    tokenizer = model.tokenizer
    intervals = [[(int(residue), int(residue)) for residue in chosen] for chosen in residues]
    regions, inside, outside = ablation_sites(intervals, [len(sequence) for sequence in sequences], masked=MASKED, seed=seed)
    input_ids, attention_mask, _ = encode_batch(tokenizer, sequences, device)  # (b, l) each
    region = column_mask(regions, tuple(input_ids.shape)).to(device)  # (b, l)
    positions = column_mask(inside, tuple(input_ids.shape)).to(device)  # (b, l)
    away = column_mask(outside, tuple(input_ids.shape)).to(device)  # (b, l)
    blocks = [int(block) for block in members["layer"]]
    masses: dict[int, Tensor] = {}

    def keep(states: BlockStates) -> None:
        masses[states.block] = removed_mass(states, torch.zeros(2 * states.gate.shape[1]))  # (p,)

    with BlockReader(model, blocks, keep) as reader:
        reader.run(input_ids.masked_fill(positions, tokenizer.mask_token_id), attention_mask, region)
    width = next(iter(masses.values())).shape[0] // 2
    targets: list[PoleTarget] = []
    placebos: list[list[PoleTarget]] = [[] for _ in range(PLACEBOS)]
    removed = 0.0
    for block, pole in zip(blocks, members["best_feature"].astype(int), strict=True):
        if float(masses[block][pole]) <= 0:
            continue
        matched = matched_placebos(masses[block], pole, [], seed=seed + block)
        if len(matched) < PLACEBOS:
            continue
        targets.append(PoleTarget(block, *pole_unit(pole, width), 0.0))
        removed += float(masses[block][pole])
        for group, placebo in zip(placebos, matched, strict=True):
            group.append(PoleTarget(block, *pole_unit(placebo, width), 0.0))
    entry: dict[str, object] = {"members": len(members), "firing_members": len(targets), "proteins": len(sequences),
                                "masked": int(positions.sum()), "removed": removed}
    if not targets:
        return {**entry, "status": "silent"}

    def fall(chosen: Sequence[PoleTarget], where: Tensor, clean: Tensor) -> float:
        # where: (b, l) the masked residues read; clean: (s,) their intact log probabilities
        with pole_ablation(model, chosen, region):
            edited, _ = masked_readout(model, input_ids, attention_mask, where, tokenizer.mask_token_id)  # (s,)
        return float((clean - edited).mean())

    clean, _ = masked_readout(model, input_ids, attention_mask, positions, tokenizer.mask_token_id)  # (s,)
    best = int(members["best_test_f1"].to_numpy().argmax())
    single = [target for target in targets if target.block == blocks[best]] or targets[:1]
    outside_drop = None
    if bool(away.any()):
        clean_away, _ = masked_readout(model, input_ids, attention_mask, away, tokenizer.mask_token_id)  # (s_away,)
        outside_drop = fall(targets, away, clean_away)
    return {**entry, "status": "tested", "blocks": ",".join(str(target.block) for target in targets),
            "clean_log_prob": float(clean.mean()), "drop": fall(targets, positions, clean),
            "single_drop": fall(single, positions, clean), "single_block": single[0].block, "outside_drop": outside_drop,
            "placebo_drops": [fall(group, positions, clean) for group in placebos]}


def run_concept_groups(model: nn.Module, per_concept: pd.DataFrame, names: Sequence[str], shards: Sequence[object],
                       device: torch.device, *, limit: int | None = None, log: Callable[[str], None] = print) -> pd.DataFrame:
    """Every concept's group on InterPLM's test proteins that carry it; a concept with fewer than `MIN_PROTEINS`
    carriers is kept as `too_few`. `limit` stops after that many concepts, for a pilot."""
    # shards: the test shards, each with `sequences` and `labels` (n, C) whose columns follow `names`
    column = {name: index for index, name in enumerate(names)}
    groups = concept_groups(per_concept)
    rows = []
    for order, (concept, members) in enumerate(sorted(groups.items())[:limit]):
        found: list[tuple[str, np.ndarray]] = []
        for shard in shards:
            lengths = [len(sequence) for sequence in shard.sequences]
            for protein, residues in carriers(shard.labels, lengths, column[concept]).items():
                if lengths[protein] <= MAX_RESIDUES:
                    found.append((shard.sequences[protein], residues))
        if len(found) < MIN_PROTEINS:
            rows.append({"concept": concept, "members": len(members), "proteins": len(found), "status": "too_few"})
            continue
        generator = np.random.default_rng(SEED + order)
        picked = np.sort(generator.choice(len(found), size=min(PROTEINS, len(found)), replace=False))
        rows.append({"concept": concept, **ablate_group(model, members, [found[index][0] for index in picked],
                                                        [found[index][1] for index in picked], device, seed=SEED + order)})
        log(f"concept group {concept} ({order + 1}/{len(groups)}): {rows[-1]['status']}, "
            f"drop {rows[-1].get('drop')}, placebo mean {np.mean(rows[-1].get('placebo_drops', [np.nan])):.5f}")
    return pd.DataFrame(rows)


def group_report(table: pd.DataFrame) -> dict[str, object]:
    """Over the tested concepts: the median fall for groups, single poles and placebo groups, the median excess of a
    group over its placebos' mean, and the share of groups that fall more than every one of their placebo groups."""
    tested = table[table["status"] == "tested"]
    if tested.empty:
        return {"tested": 0}
    placebo = np.array([np.mean(drops) for drops in tested["placebo_drops"]])  # (c,)
    highest = np.array([np.max(drops) for drops in tested["placebo_drops"]])  # (c,)
    drop = tested["drop"].to_numpy()  # (c,)
    return {"tested": int(len(tested)), "statuses": {str(status): int(count) for status, count in table["status"].value_counts().items()},
            "median_drop": float(np.median(drop)), "median_single_drop": float(tested["single_drop"].median()),
            "median_placebo_drop": float(np.median(placebo)), "median_excess": float(np.median(drop - placebo)),
            "above_every_placebo": float((drop > highest).mean()),
            "median_outside_drop": float(tested["outside_drop"].dropna().median()),
            "median_firing_members": float(tested["firing_members"].median())}
