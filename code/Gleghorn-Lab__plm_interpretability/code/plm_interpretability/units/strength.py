"""E14a: does a unit's reading narrow as it fires harder?

Tigges and colleagues (Goodfire, 2026) report that a language model's neurons mean fewer things the harder they fire,
while random directions stay mixed at every strength; their meanings were judged by a language model. InterPLM's
residue labels measure the same in a protein model. Each unit's residues are cut into bands by how hard it fires
there: the top 5 to 1 percent of residues, 1 to 0.1, 0.1 to 0.01 and the top 0.01 percent, with thresholds set on a
sample of validation residues. In each band the concept that covers the largest share of the band's validation
residues is chosen, and the share of the band's test residues it covers is the band's precision. A unit narrows when
that precision rises from its weakest band to its strongest.

Symbols: n residues; s sampled residues; F features; C concepts; B bands.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from torch import Tensor

from .bootstrap import median_difference
from .retest import ConceptSet, RetestBatch, RetestShard, batch_labels, protein_batches


TAILS = (0.05, 0.01, 0.001, 0.0001)  # a band holds the residues above one tail's threshold and not above the next
BANDS = ("top 5 to 1%", "top 1 to 0.1%", "top 0.1 to 0.01%", "top 0.01%")
SAMPLE_RESIDUES = 100_000
SAMPLE_SEED = 24895
SAMPLE_POOL = 4  # the sampled validation batches hold at least this many times the sample
MIN_FIRED = 10  # residues a band needs on each split to be read
MOSTLY = 0.5
ROTATION_SEEDS = (0, 1, 2)
ARMS = ("mlp_poles", "mlp_native", *(f"mlp_rotation{seed}" for seed in ROTATION_SEEDS))
NATIVE_ARMS = ("mlp_poles", "mlp_native")  # the sign poles, the reading the rotations share, then the gate-tagged poles


def sample_window(shards: Sequence[RetestShard], token_budget: int, residues: int = SAMPLE_RESIDUES,
                  seed: int = SAMPLE_SEED) -> tuple[Callable[[list[tuple[int, int, np.ndarray]]], list[tuple[int, int, np.ndarray]]], float]:
    """A wrapper of `retest.stream_esmc_arms`'s plan that keeps a seeded random set of validation batches holding at
    least `SAMPLE_POOL` times `residues` residues, and the share of their residues that makes the sample."""
    lengths = [np.array([len(sequence) for sequence in shard.sequences]) for shard in shards]  # (p_shard,) each
    entries = [(number, index, int(lengths[number][proteins].sum())) for number, shard in enumerate(shards) if shard.split == "valid"
               for index, proteins in enumerate(protein_batches(list(lengths[number]), token_budget))]
    order = np.random.default_rng(seed).permutation(len(entries))  # (batches,)
    kept: set[tuple[int, int]] = set()
    held = 0
    for position in order:
        if held >= SAMPLE_POOL * residues:
            break
        kept.add(entries[position][:2])
        held += entries[position][2]
    if held < residues:
        raise ValueError(f"The validation shards hold {held} residues, fewer than the {residues} sampled.")
    return (lambda plan: [entry for entry in plan if (entry[0], entry[1]) in kept]), residues / held  # (p_b,) proteins an entry


def collect_sample(batches: Iterable[RetestBatch], rate: float, seed: int = SAMPLE_SEED) -> dict[str, Tensor]:
    """Each arm's activations at a seeded sample of the batches' residues, each residue kept with probability `rate`,
    the same residues for every arm."""
    generator = torch.Generator().manual_seed(seed)
    kept: dict[str, list[Tensor]] = {}
    for batch in batches:
        chosen = torch.nonzero(torch.rand(len(batch.rows), generator=generator) < rate).reshape(-1)  # (n_kept,)
        for arm, values in batch.arms.items():  # (n, F)
            kept.setdefault(arm, []).append(values[chosen.to(values.device)])
    sample = {}
    for arm in list(kept):
        sample[arm] = torch.cat(kept.pop(arm))  # (s, F); an arm's batches are freed as it is joined
    return sample  # (s, F) each


def tail_thresholds(sample: Tensor, tails: Sequence[float] = TAILS, chunk: int = 1024) -> Tensor:
    """Per feature and tail, the activation that the tail's share of the sampled residues exceed, never below zero, so
    a unit silent at more residues than a tail leaves only the residues where it fires."""
    # sample: (s, F)
    ranks = [int(round(tail * sample.shape[0])) for tail in tails]
    if min(ranks) < 1 or sorted(ranks, reverse=True) != ranks:
        raise ValueError(f"Tails {tuple(tails)} must fall, and each must leave a sampled residue above it of {sample.shape[0]}.")
    thresholds = []
    for start in range(0, sample.shape[1], chunk):
        top = sample[:, start:start + chunk].topk(ranks[0] + 1, dim=0).values  # (rank + 1, c), falling
        thresholds.append(top[ranks])  # (B, c): exactly `rank` sampled residues lie above each, ties aside
    return torch.cat(thresholds, dim=1).clamp(min=0)  # (B, F)


class BandCounts:
    """Running sums for one arm and split: per concept, feature and tail the labeled residues where the feature exceeds
    the tail's threshold, and per feature and tail the residues where it does."""

    def __init__(self, concepts: int, thresholds: Tensor) -> None:
        # thresholds: (B, F)
        self.thresholds = thresholds
        bands, features = thresholds.shape
        self.positive = torch.zeros((concepts, features, bands), dtype=torch.int32, device=thresholds.device)  # (C, F, B)
        self.fired = torch.zeros((features, bands), dtype=torch.int64, device=thresholds.device)  # (F, B)

    def update(self, values: Tensor, presence: Tensor) -> None:
        """Add a batch of residues: each feature's activations and the residues' concepts."""
        # values: (n, F); presence: (n, C) float32
        for band, threshold in enumerate(self.thresholds):  # (F,)
            above = (values > threshold).float()  # (n, F)
            self.fired[:, band] += above.sum(dim=0).round().long()
            self.positive[:, :, band] += (presence.T @ above).round().int()  # (C, F); exact below 2**24 residues

    def bands(self) -> tuple[Tensor, Tensor]:
        """The counts within each band: above its own threshold and not above the next tail's."""
        positive, fired = self.positive.long(), self.fired  # (C, F, B), (F, B)
        within = torch.cat((positive[:, :, :-1] - positive[:, :, 1:], positive[:, :, -1:]), dim=2)  # (C, F, B)
        return within, torch.cat((fired[:, :-1] - fired[:, 1:], fired[:, -1:]), dim=1)  # (C, F, B), (F, B)


def collect_bands(batches: Iterable[RetestBatch], shards: Sequence[RetestShard], thresholds: Mapping[str, Tensor],
                  concepts: ConceptSet) -> dict[tuple[str, str], BandCounts]:
    """Every arm's band counts on each split, over one block's batches."""
    # thresholds: (B, F) by arm
    counts: dict[tuple[str, str], BandCounts] = {}
    for batch in batches:
        presence = None
        for arm, values in batch.arms.items():  # (n, F)
            if presence is None:
                presence = batch_labels(shards[batch.shard].labels[batch.rows], concepts.domain_level, values.device).presence
            key = (arm, batch.split)
            if key not in counts:
                counts[key] = BandCounts(len(concepts.names), thresholds[arm])
            counts[key].update(values, presence)
    return counts


@dataclass(frozen=True)
class BandReading:
    concept: np.ndarray  # (F, B) the concept chosen on validation, -1 where the band lacks residues on a split
    precision: np.ndarray  # (F, B) the share of the band's test residues that concept labels, NaN where unread
    lift: np.ndarray  # (F, B) that share over the concept's share of all test residues
    fired: np.ndarray  # (F, B) test residues in the band

    @property
    def read(self) -> np.ndarray:
        """(F, B) bool: the bands with enough residues on both splits."""
        return self.concept >= 0  # (F, B)


def band_reading(valid: BandCounts, test: BandCounts, reported: np.ndarray, base_rate: np.ndarray, *,
                 min_fired: int = MIN_FIRED, chunk: int = 2048) -> BandReading:
    """Per feature and band, the reported concept with the largest share of the band's validation residues (the lowest
    index on a tie), and its share of the band's test residues."""
    # reported: (C,) bool; base_rate: (C,), each concept's share of all test residues
    positive_valid, fired_valid = valid.bands()  # (C, F, B), (F, B)
    positive_test, fired_test = test.bands()  # (C, F, B), (F, B)
    keep = torch.as_tensor(reported, device=positive_valid.device)[:, None, None]  # (C, 1, 1)
    concepts, shares = [], []
    for start in range(0, fired_valid.shape[0], chunk):
        rows = slice(start, start + chunk)
        share = positive_valid[:, rows].double() / fired_valid[rows].double().clamp(min=1)[None]  # (C, c, B)
        chosen = torch.where(keep, share, torch.full_like(share, -1.0)).argmax(dim=0)  # (c, B)
        covered = positive_test[:, rows].gather(0, chosen[None]).squeeze(0)  # (c, B)
        concepts.append(chosen)
        shares.append(covered.double() / fired_test[rows].double().clamp(min=1))
    concept = torch.cat(concepts).cpu().numpy()  # (F, B)
    precision = torch.cat(shares).cpu().numpy()  # (F, B)
    read = ((fired_valid >= min_fired) & (fired_test >= min_fired)).cpu().numpy()  # (F, B)
    return BandReading(np.where(read, concept, -1), np.where(read, precision, np.nan),
                       np.where(read, precision / np.maximum(base_rate[concept], 1e-300), np.nan), fired_test.cpu().numpy())


def rises(reading: BandReading) -> np.ndarray:
    """Per feature, the strongest band's precision minus the weakest's; NaN unless both are read."""
    return reading.precision[:, -1] - reading.precision[:, 0]  # (F,)


def band_table(readings: Mapping[str, BandReading]) -> pd.DataFrame:
    """Per arm and band: the units read, their mean and median precision and median lift, and the share of them whose
    band is mostly one concept."""
    rows = []
    for arm, reading in readings.items():
        for band, name in enumerate(BANDS):
            read = reading.read[:, band]  # (F,)
            precision, lift = reading.precision[read, band], reading.lift[read, band]  # (F_read,) each
            rows.append({"arm": arm, "band": name, "units_read": int(read.sum()),
                         "mean_precision": float(precision.mean()) if read.any() else float("nan"),
                         "median_precision": float(np.median(precision)) if read.any() else float("nan"),
                         "mostly_one_concept": float((precision > MOSTLY).mean()) if read.any() else float("nan"),
                         "median_lift": float(np.median(lift)) if read.any() else float("nan"),
                         "median_test_residues": float(np.median(reading.fired[read, band])) if read.any() else float("nan")})
    return pd.DataFrame(rows)


def narrowing(readings: Mapping[str, BandReading]) -> dict[str, object]:
    """Per arm, the units read in both their weakest and strongest bands, their median rise in precision between the
    two and the share whose two bands chose the same concept; and each native reading's median rise minus each
    rotation's, with its 95 percent interval from resampling each arm's units."""
    summary: dict[str, object] = {}
    by_arm = {arm: rises(reading) for arm, reading in readings.items()}  # (F,) each
    for arm, reading in readings.items():
        both = np.isfinite(by_arm[arm])  # (F,)
        summary[arm] = {"units": int(both.sum()), "median_rise": float(np.median(by_arm[arm][both])) if both.any() else None,
                        "mean_rise": float(by_arm[arm][both].mean()) if both.any() else None,
                        "same_concept": float((reading.concept[both, 0] == reading.concept[both, -1]).mean()) if both.any() else None}
    differences = {}
    for native in NATIVE_ARMS:
        for arm in by_arm:
            if arm.startswith("mlp_rotation") and native in by_arm:
                interval = median_difference(by_arm[native], by_arm[arm])
                differences[f"{native}_minus_{arm}"] = {"estimate": interval.estimate, "low": interval.low, "high": interval.high}
    summary["rise_differences"] = differences
    return summary
