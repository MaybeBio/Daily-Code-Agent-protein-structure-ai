"""Exemplar tracks of chosen neuron poles on InterPLM's evaluation, for the paper's figure of labeled neurons.

Exploratory and added on 2026-11-16, after every preregistered decision and E13: the poles are chosen after the fact,
for biology a reader recognizes, among poles that E13 found to read a Swiss-Prot concept on InterPLM's evaluation (a
concept's best validation pole at ESMC-600's block 26, its test F1 above 0.5). Figure 4's `exemplars` draws its poles
by a frozen rule and shows them on the atlas's held-out carriers, which rarely carry a Swiss-Prot feature; these poles
are shown instead on InterPLM's test proteins, where E13 scored them.

One pass reads the chosen poles (`mlp_native` features, positive poles first) over every evaluation protein in E13's
batches, keeping their activations (`collect_chosen`). From them come each pole's maximum, InterPLM's scale
(`chosen_ranges`); its counts and F1 at InterPLM's five thresholds on the validation and test halves, exactly as E13
counts them (`chosen_counts`, `pole_scores`), which must give E13's archived test F1 (`check_archived`); and each
protein's maximum (`protein_maxima`). Carriers follow a fixed rule (`choose_carriers`): of the test proteins whose
residues carry the concept, the `TOP` with the highest maximum (identical sequences once), then `DRAWN` drawn uniformly
from the rest with `SEED` plus the exemplar's index, and one test protein that does not carry the concept, drawn with the
same generator, as a negative control. `concept_track_table` writes the tracks in the schema of `exemplars.track_table`,
with `term` the concept's index in the evaluation's concept set, the concept's name, the threshold in activation units
(the validation-chosen threshold times the pole's maximum) and the pole's F1 on both halves.

Symbols: n residues of a shard; k chosen poles; C concepts; T thresholds; p proteins of a shard; l residues of one protein.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .exemplars import POLE_NAMES
from .retest import (SPLITS, THRESHOLDS, ConceptCounts, ConceptSet, FeatureRanges, RetestBatch, RetestShard, _best_entries,
                     batch_labels, f1_scores, protein_batches)


ARM = "mlp_native"  # the neurons' gate-tagged poles, as E13 reads them
TOP = 3
DRAWN = 3
SEED = 24895  # the study's seed, as `exemplars.SEED`
CHOICE_COLUMNS = ("model", "concept", "feature")
ROLES = (*(f"top{rank}" for rank in range(1, TOP + 1)), *(f"drawn{rank}" for rank in range(1, DRAWN + 1)), "negative")
RULE = (f"Per concept, of the test-half proteins with any residue labeled with the concept, the {TOP} with the highest "
        f"maximum of the pole (an identical sequence once), then {DRAWN} drawn uniformly without replacement from the "
        f"remaining carriers by numpy's default_rng(SEED + exemplar), then one test-half protein without the concept drawn by "
        f"the same generator as a negative control.")
POSTHOC = ("The poles were chosen after the fact, for biology a reader recognizes, among poles whose concept E13 found "
           "them to read on InterPLM's evaluation (best validation pole, test F1 above 0.5); they are illustrations, not "
           "a sample.")


@dataclass(frozen=True)
class PoleScore:
    """One chosen pole's F1 for its concept on a half of the evaluation, at the threshold that half selects by
    InterPLM's rule (F1 per domain first, then F1, then the lower threshold); NaN where the pole never fires on one of
    the concept's residues."""

    f1: float
    threshold: float


def read_choices(frame: pd.DataFrame, concepts: ConceptSet, model: str) -> pd.DataFrame:
    """The chosen poles of one model, in order, with each concept's index in the evaluation's concept set."""
    # frame: model, concept, feature
    missing = set(CHOICE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"The choices lack columns {sorted(missing)}.")
    chosen = frame[frame["model"] == model].reset_index(drop=True)
    if chosen.empty or len(chosen) != len(frame):
        raise ValueError(f"Every choice must be of {model}; {len(frame) - len(chosen)} are not.")
    position = {name: index for index, name in enumerate(concepts.names)}
    unknown = sorted(set(chosen["concept"]) - set(position))
    if unknown:
        raise ValueError(f"Concepts {unknown} are not in the evaluation's concept set.")
    if chosen["concept"].duplicated().any():
        raise ValueError("A concept is chosen twice.")
    return chosen.assign(feature=chosen["feature"].astype(np.int64), concept_index=chosen["concept"].map(position).astype(np.int64))


def collect_chosen(batches: Iterable[RetestBatch], shards: Sequence[RetestShard], features: Sequence[int], *,
                   arm: str = ARM) -> list[np.ndarray]:
    """The chosen features' activations at every residue of every shard, in the shard's label-row order, from one
    pass of E13's stream at one block."""
    columns = torch.as_tensor(list(features), dtype=torch.int64)  # (k,)
    store = [np.full((shard.labels.shape[0], len(features)), np.nan, dtype=np.float32) for shard in shards]  # (n, k) each
    blocks: set[int] = set()
    for batch in batches:
        blocks.add(batch.layer)
        values = batch.arms[arm]  # (n_b, F)
        store[batch.shard][batch.rows] = values[:, columns.to(values.device)].float().cpu().numpy()  # (n_b, k)
    if len(blocks) != 1:
        raise ValueError(f"The pass read blocks {sorted(blocks)}, not one.")
    unread = [index for index, values in enumerate(store) if np.isnan(values).any()]
    if unread:
        raise ValueError(f"Shards {unread} have residues the pass did not read.")
    return store  # (n, k) for each shard


def chosen_ranges(store: Sequence[np.ndarray], block: int, *, arm: str = ARM) -> FeatureRanges:
    """Each chosen feature's minimum and maximum over every residue of both halves, E13's first pass for them."""
    # store: (n, k) for each shard
    ranges = FeatureRanges()
    for values in store:  # (n, k)
        ranges.update((block, arm), torch.from_numpy(values))
    return ranges


def chosen_counts(store: Sequence[np.ndarray], shards: Sequence[RetestShard], ranges: FeatureRanges,
                  concepts: ConceptSet, block: int, *, token_budget: int, arm: str = ARM) -> dict[str, ConceptCounts]:
    """Each half's counts for the chosen features, E13's second pass for them, over E13's own protein batches (a
    domain is numbered within a shard, so the counts do not depend on the batching)."""
    # store: (n, k) for each shard
    counts: dict[str, ConceptCounts] = {}
    for shard, values in zip(shards, store, strict=True):
        lengths = [len(sequence) for sequence in shard.sequences]
        offsets = np.concatenate(([0], np.cumsum(lengths)))  # (p + 1,)
        if shard.split not in counts:
            counts[shard.split] = ConceptCounts(len(concepts.names), values.shape[1])
        for proteins in protein_batches(lengths, token_budget):  # (p_b,)
            rows = np.concatenate([np.arange(offsets[protein], offsets[protein + 1]) for protein in proteins])  # (n_b,)
            labels = batch_labels(shard.labels[rows], concepts.domain_level)
            counts[shard.split].update(ranges.scale((block, arm), torch.from_numpy(values[rows])), labels)
    if set(counts) != set(SPLITS):
        raise ValueError(f"The shards cover the halves {sorted(counts)}, not {list(SPLITS)}.")
    return counts


def _pole_score(arrays: tuple[torch.Tensor, torch.Tensor, torch.Tensor], concept: int, column: int) -> PoleScore:
    """A pole's F1 for a concept on one half at the threshold InterPLM's rule selects there."""
    # arrays: (C, k, T) each, whether present, F1 and F1 per domain
    present, f1, per_domain = (array[concept, column][None] for array in arrays)  # (1, T) each
    position, found = _best_entries(present, f1, per_domain)  # (1,), (1,)
    if not bool(found[0]):
        return PoleScore(float("nan"), float("nan"))
    return PoleScore(float(per_domain[0, position[0]]), float(THRESHOLDS[int(position[0])]))


def pole_scores(counts: dict[str, ConceptCounts], concepts: ConceptSet, choices: pd.DataFrame) -> pd.DataFrame:
    """Each chosen pole's F1 for its concept and the threshold selected on each half: on test, the number E13 reports
    as the concept's best test F1 when this pole is its best validation pole."""
    arrays = {split: f1_scores(counts[split], concepts, split) for split in SPLITS}
    rows = []
    for column, choice in enumerate(choices.itertuples()):
        scores = {split: _pole_score(arrays[split], int(choice.concept_index), column) for split in SPLITS}
        rows.append({"concept": choice.concept, "feature": int(choice.feature),
                     **{f"{split}_f1": score.f1 for split, score in scores.items()},
                     **{f"{split}_threshold": score.threshold for split, score in scores.items()}})
    return pd.DataFrame(rows)


def check_archived(scores: pd.DataFrame, archived: pd.DataFrame, block: int, *, arm: str = ARM,
                   tolerance: float = 1e-12) -> float:
    """Every chosen pole is its concept's archived best validation pole and gives the archived test F1; the largest
    difference, which must not exceed `tolerance`."""
    # archived: E13's per-concept table (layer, arm, concept, best_feature, best_test_f1)
    rows = archived[(archived["layer"] == block) & (archived["arm"] == arm)].set_index("concept")
    largest = 0.0
    for score in scores.itertuples():
        if score.concept not in rows.index:
            raise ValueError(f"{score.concept} is not in the archived table at block {block}.")
        entry = rows.loc[score.concept]
        if int(entry["best_feature"]) != int(score.feature):
            raise ValueError(f"{score.concept}: the archived best pole is {int(entry['best_feature'])}, not {score.feature}.")
        difference = abs(float(entry["best_test_f1"]) - float(score.test_f1))
        if not difference <= tolerance:  # NaN fails too
            raise ValueError(f"{score.concept}: test F1 {score.test_f1!r} against the archived {float(entry['best_test_f1'])!r}.")
        largest = max(largest, difference)
    return largest


def protein_maxima(values: np.ndarray, lengths: Sequence[int]) -> np.ndarray:
    """Each protein's maximum of each chosen feature, from a shard's residues in label-row order."""
    # values: (n, k)
    starts = np.concatenate(([0], np.cumsum(lengths)[:-1]))  # (p,)
    if values.shape[0] != int(np.sum(lengths)) or min(lengths) < 1:
        raise ValueError("The residues do not split into the proteins' lengths.")
    return np.maximum.reduceat(values, starts, axis=0)  # (p, k)


def concept_carriers(labels: object, lengths: Sequence[int], concept: int) -> np.ndarray:
    """Whether each of consecutive proteins has a residue labeled with the concept."""
    # labels: (n, C) the proteins' residues' concept labels, sparse
    offsets = np.concatenate(([0], np.cumsum(lengths)))  # (p + 1,)
    if labels.shape[0] != offsets[-1]:
        raise ValueError(f"The labels have {labels.shape[0]} rows for {offsets[-1]} residues.")
    labeled = labels[:, concept].nonzero()[0]  # (q,) label rows
    carries = np.zeros(len(lengths), dtype=bool)  # (p,)
    carries[np.searchsorted(offsets, labeled, side="right") - 1] = True
    return carries  # (p,)


def choose_carriers(exemplar: int, carries: np.ndarray, maxima: np.ndarray, sequences: Sequence[str], *, top: int = TOP,
                    drawn: int = DRAWN, seed: int = SEED) -> pd.DataFrame:
    """One exemplar's proteins by the rule `RULE`, over the test proteins in a fixed order: the strongest carriers,
    carriers drawn at random and one protein without the concept; `protein` indexes that order. A concept with fewer
    carriers than `top` plus `drawn` gives the strongest and as many drawn as remain, which the roles show."""
    # carries: (p,) bool; maxima: (p,) the pole's maximum per protein
    carriers = np.flatnonzero(carries)  # (c,)
    if carriers.size == 0:
        raise ValueError(f"Exemplar {exemplar}'s concept has no test carrier.")
    ranked = carriers[np.argsort(-maxima[carriers], kind="stable")]  # (c,)
    chosen: list[int] = []
    seen: set[str] = set()
    for protein in ranked:
        if sequences[protein] not in seen:
            chosen.append(int(protein))
            seen.add(sequences[protein])
        if len(chosen) == top:
            break
    generator = np.random.default_rng(seed + exemplar)
    rest = np.setdiff1d(carriers, chosen)  # (c_rest,)
    picked = [int(protein) for protein in generator.choice(rest, size=min(drawn, rest.size), replace=False)]
    others = np.flatnonzero(~carries)  # (p_neg,)
    if others.size == 0:
        raise ValueError(f"Every test protein carries exemplar {exemplar}'s concept.")
    negative = int(others[generator.integers(others.size)])
    proteins = [*chosen, *picked, negative]
    roles = [f"top{rank}" for rank in range(1, len(chosen) + 1)] + [f"drawn{rank}" for rank in range(1, len(picked) + 1)] + ["negative"]
    return pd.DataFrame({"exemplar": exemplar, "protein": proteins, "role": roles, "maximum": maxima[proteins]})


def track_maxima_difference(pairs: pd.DataFrame, tracks: Sequence[np.ndarray], units: int) -> float:
    """The largest relative difference between each track's own pole maximum, read one protein a pass, and the pass's
    maximum for that protein: a check that pole, unit and protein line up."""
    # pairs: feature, maximum; tracks: (l, 4) per pair
    largest = 0.0
    for pair, track in zip(pairs.itertuples(), tracks, strict=True):
        own = float(track[:, int(pair.feature) // units].max())
        if pair.maximum > 0:
            largest = max(largest, abs(own - float(pair.maximum)) / float(pair.maximum))
    return largest


def concept_track_table(pairs: pd.DataFrame, sequences: Sequence[str], accessions: Sequence[str], labels: object,
                        offsets: np.ndarray, tracks: Sequence[np.ndarray], units: int) -> pd.DataFrame:
    """One row per residue of each chosen protein, in the schema of `exemplars.track_table` (with `term` the concept's
    index), beside the concept's name and the pole's F1 on both halves."""
    # pairs: exemplar, protein, role, kind, feature, concept, concept_index, threshold, valid_f1, test_f1;
    # sequences, accessions: the test proteins in order; labels: (n, C) their residues' concept labels, sparse;
    # offsets: (p + 1,) each protein's first label row; tracks: (l, 4) per pair
    frames = []
    for pair, track in zip(pairs.itertuples(), tracks, strict=True):
        sequence = sequences[int(pair.protein)]
        if track.shape != (len(sequence), len(POLE_NAMES)):
            raise ValueError(f"The track of {accessions[int(pair.protein)]} does not cover its {len(sequence)} residues.")
        rows = np.arange(offsets[int(pair.protein)], offsets[int(pair.protein) + 1])  # (l,)
        inside = np.asarray(labels[rows, int(pair.concept_index)].todense()).reshape(-1) != 0  # (l,)
        frames.append(pd.DataFrame({
            "exemplar": int(pair.exemplar), "kind": pair.kind, "pole": int(pair.feature), "term": int(pair.concept_index),
            "own": POLE_NAMES[int(pair.feature) // units], "accession": accessions[int(pair.protein)], "role": pair.role,
            "position": np.arange(1, len(sequence) + 1), "residue": list(sequence),
            **{name: track[:, column] for column, name in enumerate(POLE_NAMES)},
            "in_term": inside, "threshold": float(pair.threshold), "concept": pair.concept,
            "valid_f1": float(pair.valid_f1), "test_f1": float(pair.test_f1),
        }))
    return pd.concat(frames, ignore_index=True)
