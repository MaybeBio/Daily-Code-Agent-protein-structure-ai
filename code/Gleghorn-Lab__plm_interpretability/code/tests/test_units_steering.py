from __future__ import annotations

import numpy as np
import pytest
import torch

from torch import nn

from plm_interpretability.units import atlas, causal, intrinsic, steering


CPU = torch.device("cpu")
AMINO = list(intrinsic.AMINO_ACIDS)


def _sequences(count: int, low: int, high: int, seed: int) -> list[str]:
    generator = np.random.default_rng(seed)
    return ["".join(generator.choice(AMINO, size=int(generator.integers(low, high)))) for _ in range(count)]


def test_flank_hydropathy_leaves_out_the_center() -> None:
    sequence = _sequences(1, 40, 41, seed=1)[0]
    values = steering.flank_hydropathy(sequence)  # (l,)
    for position in range(len(sequence)):
        window = [intrinsic.KYTE_DOOLITTLE[sequence[index]] for index in range(position - 9, position + 10)
                  if index != position and 0 <= index < len(sequence)]
        if 9 <= position < len(sequence) - 9:
            assert values[position] == pytest.approx(np.mean(window))
        else:
            assert np.isnan(values[position])
    assert np.isnan(steering.flank_hydropathy(sequence[:15] + "X" + sequence[16:])[20])


def test_fit_positions_keep_their_flanks_apart() -> None:
    for length, positions in zip((19, 18, 200), steering.fit_positions([19, 18, 200]), strict=True):
        assert np.all(positions >= 9) and np.all(positions <= length - 10)
        assert np.all(np.diff(positions) == steering.SPACING)
    assert len(steering.fit_positions([18])[0]) == 0


def _curved(count: int = 4000, width: int = 16, classes: int = 21, seed: int = 0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """States on three quarters of a circle in a random plane and distributions whose peak moves with the concept."""
    generator = np.random.default_rng(seed)
    values = generator.uniform(-2.0, 2.0, count)  # (n,)
    angle = (values + 2.0) / 4.0 * 1.5 * np.pi  # (n,)
    plane = np.linalg.qr(generator.normal(size=(width, 2)))[0]  # (w, 2)
    states = np.stack((np.cos(angle), np.sin(angle)), axis=1) @ plane.T * 5 + generator.normal(0, 0.05, (count, width))  # (n, w)
    centers = (values + 2.0) / 4.0 * (classes - 1)  # (n,)
    logits = -0.5 * (np.arange(classes)[None, :] - centers[:, None]) ** 2  # (n, c)
    distributions = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)  # (n, c)
    return values, states, distributions  # (n,), (n, w), (n, c)


def test_manifolds_fit_a_curve_and_its_geodesics_beat_straight_lines() -> None:
    values, states, distributions = _curved()
    manifolds = steering.fit_manifolds(values, states, distributions, bins=8)
    assert np.all(np.diff(manifolds.knots) > 0) and manifolds.centroids.shape == (8, 16)
    radius = np.linalg.norm(manifolds.activation(np.linspace(-1.5, 1.5, 9)), axis=1)  # (9,): points stay near the circle
    assert np.all(np.abs(radius - 5) < 0.3)
    shape = steering.isometry(manifolds)
    assert shape["pairs"] == 28 and shape["geodesic_r"] > 0.98 and shape["geodesic_r"] > shape["straight_r"] + 0.02
    on_curve = manifolds.behavior_at(np.array([-1.0, 0.5])) ** 2  # (2, c)
    curve = manifolds.behavior_at(np.linspace(manifolds.knots[0], manifolds.knots[-1], 400))  # (q, c)
    assert np.all(steering.manifold_distance(on_curve, curve) < 1e-3)
    assert np.all(steering.manifold_distance(np.full((1, 21), 1 / 21), curve) > 0.1)
    with pytest.raises(ValueError, match="no calibration residue"):
        steering.fit_manifolds(np.r_[np.zeros(50), np.ones(50)], states[:100], distributions[:100], bins=4)


def test_arm_offsets_share_their_start_and_the_lines_their_end() -> None:
    values, states, distributions = _curved()
    manifolds = steering.fit_manifolds(values, states, distributions, bins=6)
    offsets = steering.arm_offsets(manifolds, 1, 4, steps=5)
    difference = manifolds.centroids[4] - manifolds.centroids[1]  # (w,)
    for arm in steering.ARMS:
        np.testing.assert_allclose(offsets[arm][0], 0.0, atol=1e-9)
    np.testing.assert_allclose(offsets["manifold"][-1], difference, atol=1e-9)
    np.testing.assert_allclose(offsets["linear"][-1], difference, atol=1e-9)
    np.testing.assert_allclose(np.linalg.norm(offsets["random"], axis=1), np.linalg.norm(offsets["linear"], axis=1))
    middle = manifolds.activation(np.array([(manifolds.knots[1] + manifolds.knots[4]) / 2]))[0] - manifolds.centroids[1]  # (w,)
    np.testing.assert_allclose(offsets["manifold"][2], middle, atol=1e-9)
    assert np.linalg.norm(offsets["manifold"][2] - offsets["linear"][2]) > 0.5  # the circle bends away from its chord


def test_masked_pass_reads_and_shifts_in_input_order(tiny_esmc: nn.Module) -> None:
    sequences = _sequences(5, 20, 60, seed=4)
    positions = steering.fit_positions([len(sequence) for sequence in sequences], spacing=7)
    ids = steering.amino_acid_ids(tiny_esmc.tokenizer)
    streams, distributions = steering.masked_pass(tiny_esmc, sequences, positions, ids, CPU, block=1, read_stream=True,
                                                  token_budget=96)  # several batches
    torch.testing.assert_close(distributions.sum(dim=1), torch.ones(len(distributions)))
    start = 0
    for sequence, chosen in zip(sequences, positions, strict=True):
        kept: list[torch.Tensor] = []
        input_ids, attention_mask, _ = atlas.encode_batch(tiny_esmc.tokenizer, [sequence], CPU)
        mask = torch.zeros_like(input_ids, dtype=torch.bool)
        mask[0, torch.from_numpy(chosen + 1)] = True
        with causal.stream_reading(tiny_esmc, 1, mask, kept), torch.no_grad():
            tiny_esmc(input_ids=input_ids.masked_fill(mask, tiny_esmc.tokenizer.mask_token_id), attention_mask=attention_mask)
        torch.testing.assert_close(streams[start:start + len(chosen)], kept[0], atol=1e-5, rtol=1e-4)
        start += len(chosen)
    _, unshifted = steering.masked_pass(tiny_esmc, sequences, positions, ids, CPU, block=1,
                                        shifts=torch.zeros(len(distributions), 64), token_budget=96)
    torch.testing.assert_close(unshifted, distributions)
    shifts = torch.zeros(len(distributions), 64)
    shifts[0] = 25.0 * torch.linspace(-1, 1, 64)  # not constant: the blocks' layer norms remove a constant shift exactly
    _, shifted = steering.masked_pass(tiny_esmc, sequences, positions, ids, CPU, block=1, shifts=shifts, token_budget=96)
    assert not torch.allclose(shifted[0], distributions[0])
    other_proteins = slice(len(positions[0]), None)  # the shift lands on the first protein only, whatever the batches
    torch.testing.assert_close(shifted[other_proteins], distributions[other_proteins])
    with pytest.raises(ValueError, match="ascending"):
        steering.masked_pass(tiny_esmc, sequences[:1], [np.array([12, 10])], ids, CPU, block=1)


def test_run_e7d_steers_every_pair_and_summarizes(tiny_esmc: nn.Module) -> None:
    calibration, test = _sequences(60, 40, 120, seed=8), _sequences(40, 30, 90, seed=9)
    run = steering.run_e7d(tiny_esmc, calibration, test, CPU, block=1, bins=4, steps=3, per_bin=4, log=lambda message: None)
    assert len(run.pairs) == 4 * 3 * 3 and set(run.pairs["arm"]) == set(steering.ARMS)
    assert set(run.natural) == {0, 1, 2, 3} and all(len(values) == 4 for values in run.natural.values())
    for start, end in steering.steering_plan(4):
        for arm in steering.ARMS:
            assert run.energies[start, end, arm].shape == (4,) and np.all(run.energies[start, end, arm] >= 0)
    summary = steering.steering_summary(run, draws=40)
    assert summary["pairs"] == 12 and set(summary["energy"]) == set(steering.ARMS)
    interval = summary["linear_minus_manifold"]
    assert interval["low"] <= interval["estimate"] <= interval["high"]
