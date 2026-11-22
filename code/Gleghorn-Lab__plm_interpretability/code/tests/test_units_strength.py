from __future__ import annotations

import numpy as np
import pytest
import scipy.sparse as sp
import torch

from collections.abc import Iterator
from torch import nn

from plm_interpretability.units import retest, strength


def test_tail_thresholds_leave_each_tail_s_share_above_and_never_fall_below_zero() -> None:
    generator = torch.Generator().manual_seed(0)
    sample = torch.rand(2_000, 5, generator=generator)  # (s, F)
    sample[:, 3] = torch.where(torch.arange(2_000) < 30, sample[:, 3] + 1.0, torch.zeros(2_000))  # fires at 1.5% of residues
    thresholds = strength.tail_thresholds(sample, tails=(0.05, 0.01, 0.001), chunk=2)  # (B, F)
    above = (sample[None] > thresholds[:, None]).sum(dim=1)  # (B, F)
    np.testing.assert_array_equal(above[:, [0, 1, 2, 4]].numpy(), np.array([[100] * 4, [20] * 4, [2] * 4]))
    assert float(thresholds[0, 3]) == 0.0 and int(above[0, 3]) == 30 and int(above[1, 3]) == 20
    with pytest.raises(ValueError):
        strength.tail_thresholds(sample[:100], tails=(0.05, 0.001))


def _counts(values: torch.Tensor, labels: torch.Tensor, thresholds: torch.Tensor) -> strength.BandCounts:
    # values: (n, F); labels: (n, C); thresholds: (B, F)
    counts = strength.BandCounts(labels.shape[1], thresholds)
    for start in range(0, len(values), 700):
        counts.update(values[start:start + 700], labels[start:start + 700])
    return counts


def test_band_counts_are_the_residues_between_two_thresholds() -> None:
    generator = torch.Generator().manual_seed(1)
    values = torch.rand(3_000, 4, generator=generator)  # (n, F)
    labels = (torch.rand(3_000, 3, generator=generator) < 0.3).float()  # (n, C)
    thresholds = strength.tail_thresholds(values, tails=(0.2, 0.05, 0.01))  # (B, F)
    within, fired = _counts(values, labels, thresholds).bands()  # (C, F, B), (F, B)
    for feature in range(4):
        edges = [*thresholds[:, feature].tolist(), float("inf")]
        for band in range(3):
            inside = (values[:, feature] > edges[band]) & ~(values[:, feature] > edges[band + 1])  # (n,)
            assert int(fired[feature, band]) == int(inside.sum())
            np.testing.assert_array_equal(within[:, feature, band].numpy(), labels[inside].sum(dim=0).numpy())
    np.testing.assert_array_equal(fired.sum(dim=1).numpy(), [600] * 4)


def _planted(seed: int, residues: int = 20_000) -> tuple[torch.Tensor, torch.Tensor]:
    """Feature 0 fires hardest inside concept 1 and weakly anywhere; feature 1 ignores every concept; concept 0 labels
    half of all residues and concept 2 is unreported."""
    generator = torch.Generator().manual_seed(seed)
    labels = torch.zeros(residues, 3)  # (n, C)
    labels[:, 0] = (torch.rand(residues, generator=generator) < 0.5).float()
    labels[:, 1] = (torch.rand(residues, generator=generator) < 0.02).float()
    labels[:, 2] = 1.0
    values = torch.rand(residues, 2, generator=generator)  # (n, F)
    values[:, 0] = values[:, 0] + 2.0 * labels[:, 1] * torch.rand(residues, generator=generator)
    return values, labels  # (n, F), (n, C)


def test_reading_picks_the_band_s_concept_on_validation_and_scores_it_on_test() -> None:
    reported = np.array([True, True, False])
    valid_values, valid_labels = _planted(2)
    test_values, test_labels = _planted(3)
    thresholds = strength.tail_thresholds(valid_values, tails=(0.2, 0.05, 0.01, 0.001))  # (B, F)
    valid, test = _counts(valid_values, valid_labels, thresholds), _counts(test_values, test_labels, thresholds)
    base_rate = test_labels.mean(dim=0).numpy()  # (C,)
    reading = strength.band_reading(valid, test, reported, base_rate, min_fired=5)
    assert reading.read.all() and not bool((reading.concept == 2).any())
    # the planted unit's strongest band is its concept; the unit that ignores concepts keeps the common one at its rate
    assert reading.concept[0, -1] == 1 and reading.precision[0, -1] > 0.9 and reading.lift[0, -1] > 30
    assert reading.concept[1, 0] == 0 and reading.precision[1, 0] == pytest.approx(0.5, abs=0.05)
    inside = test_values[:, 0] > thresholds[-1, 0]  # (n,)
    assert reading.precision[0, -1] == pytest.approx(float(test_labels[inside, 1].mean()))
    assert reading.fired[0, -1] == int(inside.sum())
    rises = strength.rises(reading)  # (F,)
    assert rises[0] > 0.3 and abs(rises[1]) < 0.3
    starved = strength.band_reading(valid, test, reported, base_rate, min_fired=100)
    assert not starved.read[:, -1].any() and np.isnan(starved.precision[:, -1]).all() and starved.read[:, 0].all()
    table = strength.band_table({"mlp_poles": reading, "mlp_rotation0": starved})
    assert list(table["band"][:4]) == list(strength.BANDS) and table["units_read"].tolist() == [2, 2, 2, 2, 2, 2, 2, 0]
    assert table["median_precision"].iloc[3] > 0.7 and np.isnan(table["median_precision"].iloc[7])


def test_narrowing_compares_each_native_reading_with_each_rotation() -> None:
    def reading(rise: np.ndarray) -> strength.BandReading:
        # rise: (F,)
        precision = np.stack((np.full_like(rise, 0.2), 0.2 + rise), axis=1)  # (F, B)
        return strength.BandReading(np.zeros_like(precision, dtype=np.int64), precision, precision / 0.1,
                                    np.full(precision.shape, 50))

    rng = np.random.default_rng(0)
    readings = {"mlp_poles": reading(rng.normal(0.4, 0.05, 300)), "mlp_native": reading(rng.normal(0.4, 0.05, 300)),
                "mlp_rotation0": reading(rng.normal(0.1, 0.05, 300))}
    summary = strength.narrowing(readings)
    assert summary["mlp_poles"]["units"] == 300 and summary["mlp_poles"]["same_concept"] == 1.0
    difference = summary["rise_differences"]["mlp_poles_minus_mlp_rotation0"]
    assert difference["low"] < difference["estimate"] < difference["high"] and difference["low"] > 0.25
    assert set(summary["rise_differences"]) == {"mlp_poles_minus_mlp_rotation0", "mlp_native_minus_mlp_rotation0"}


def test_stream_samples_validation_residues_and_counts_every_arm(tiny_esmc: nn.Module) -> None:
    rng = np.random.default_rng(4)
    shards = []
    for split in ("valid", "test"):
        sequences = tuple("".join(rng.choice(list("ACDEFGHIKLMNPQRSTVWY"), size=int(length))) for length in rng.integers(20, 40, size=30))
        residues = sum(len(sequence) for sequence in sequences)
        shards.append(retest.RetestShard(split, sequences, sp.csr_matrix((rng.random((residues, 3)) < 0.3).astype(np.uint32))))
    concepts = retest.ConceptSet(("Helix", "Site", "Motif"), np.zeros(3, dtype=bool),
                                 {shard.split: np.asarray(shard.labels.sum(axis=0)).reshape(-1) for shard in shards},
                                 {shard.split: np.zeros(3) for shard in shards})

    def stream(batches: object = None) -> Iterator[retest.RetestBatch]:
        return retest.stream_esmc_arms(tiny_esmc, None, (1,), shards, {}, device="cpu", token_budget=200,
                                       rotation_seeds=strength.ROTATION_SEEDS, arms=strength.ARMS, batches=batches)

    window, rate = strength.sample_window(shards, 200, residues=100)
    kept = window([(number, index, np.array([0])) for number in range(2) for index in range(40)])
    assert kept and all(number == 0 for number, _, _ in kept) and 0 < rate <= 1 / strength.SAMPLE_POOL + 1e-9
    sample = strength.collect_sample(stream(window), rate)
    assert set(sample) == set(strength.ARMS) and len({len(values) for values in sample.values()}) == 1
    assert 40 <= len(sample["mlp_poles"]) <= 180 and sample["mlp_poles"].shape[1] == 512
    thresholds = {arm: strength.tail_thresholds(values, tails=(0.2, 0.05)) for arm, values in sample.items()}
    counts = strength.collect_bands(stream(), shards, thresholds, concepts)
    assert set(counts) == {(arm, split) for arm in strength.ARMS for split in ("valid", "test")}
    for shard in shards:
        total = shard.labels.shape[0]
        fired = counts["mlp_poles", shard.split].fired  # (F, B)
        assert int(fired.max()) <= total and bool((fired[:, 0] >= fired[:, 1]).all())
        assert bool((counts["mlp_poles", shard.split].positive.sum(dim=0) <= 3 * fired).all())
    with pytest.raises(ValueError):
        strength.sample_window(shards, 200, residues=10**6)
