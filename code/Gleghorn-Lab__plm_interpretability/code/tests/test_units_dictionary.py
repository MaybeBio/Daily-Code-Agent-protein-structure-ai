from __future__ import annotations

import pytest
import torch

from plm_interpretability.units import dictionary, rotation_search, rotations


def test_correlations_match_torch_corrcoef_over_batches() -> None:
    generator = torch.Generator().manual_seed(0)
    latents = torch.relu(torch.randn(3_000, 7, generator=generator, dtype=torch.float64))  # (r, m)
    poles = torch.relu(torch.randn(3_000, 5, generator=generator, dtype=torch.float64))  # (r, p)
    accumulator = dictionary.CorrelationAccumulator(7, 5)
    for start in range(0, 3_000, 700):
        accumulator.update(latents[start:start + 700].to_sparse(), poles[start:start + 700])
    expected = torch.corrcoef(torch.cat((latents, poles), dim=1).T)[:7, 7:]  # (m, p)
    torch.testing.assert_close(accumulator.correlations(), expected, rtol=1e-10, atol=1e-10)
    torch.testing.assert_close(accumulator.correlations(slice(2, 5)), expected[2:5], rtol=1e-10, atol=1e-10)
    best, pole = accumulator.best(chunk=3)  # (m,), (m,)
    torch.testing.assert_close(best, expected.max(dim=1).values, rtol=1e-10, atol=1e-10)
    assert torch.equal(pole, expected.argmax(dim=1))


def test_topk_codes_give_the_dense_update() -> None:
    generator = torch.Generator().manual_seed(4)
    preactivations = torch.relu(torch.randn(900, 40, generator=generator, dtype=torch.float64))  # (r, m)
    values, indices = preactivations.topk(4, dim=1)  # (r, k)
    values[::7, -1] = 0.0  # zero-valued slots carry an index but no activity
    dense = torch.zeros_like(preactivations).scatter_(1, indices, values)  # (r, m)
    poles = torch.relu(torch.randn(900, 6, generator=generator, dtype=torch.float64))  # (r, p)
    by_codes, by_dense = dictionary.CorrelationAccumulator(40, 6), dictionary.CorrelationAccumulator(40, 6)
    for start in range(0, 900, 250):
        rows = slice(start, start + 250)
        by_codes.update_codes(indices[rows], values[rows], poles[rows])
        by_dense.update(dense[rows], poles[rows])
    assert by_codes.count == by_dense.count == 900
    torch.testing.assert_close(by_codes.correlations(), by_dense.correlations(), rtol=1e-10, atol=1e-10)
    torch.testing.assert_close(by_codes.mass, dense.sum(dim=0), rtol=1e-12, atol=1e-12)


def test_copy_share_weights_latents_by_their_activity() -> None:
    generator = torch.Generator().manual_seed(1)
    poles = torch.relu(torch.randn(5_000, 4, generator=generator, dtype=torch.float64))  # (r, p)
    noise = torch.relu(torch.randn(5_000, 1, generator=generator, dtype=torch.float64))  # (r, 1)
    # Latent 0 copies pole 2 at three times its scale; latent 1 is unrelated noise at unit scale.
    latents = torch.cat((3 * poles[:, 2:3], noise), dim=1)  # (r, m)
    accumulator = dictionary.CorrelationAccumulator(2, 4)
    accumulator.update(latents, poles)
    report = dictionary.copy_report(accumulator)
    assert int(report.best_pole[0]) == 2 and float(report.best_correlation[0]) == pytest.approx(1.0)
    assert report.shares[0.9] == pytest.approx(float(latents[:, 0].sum() / latents.sum()))


def test_matched_write_cosines_sign_the_pole_and_ignore_a_constant_offset() -> None:
    generator = torch.Generator().manual_seed(5)
    write = torch.randn(8, 3, generator=generator, dtype=torch.float64)  # (d, f)
    # Latent 0 writes along unit 1 plus a constant in every dimension; latent 1 writes along -w_2 for unit 2's negative
    # pole; latent 2 writes along +w_2 but is matched to that same negative pole.
    decoder = torch.stack((write[:, 1] + 5.0, -2 * write[:, 2], write[:, 2]))  # (m, d)
    cosines = dictionary.matched_write_cosines(decoder, write, torch.tensor([1, 5, 5]))  # (m,)
    torch.testing.assert_close(cosines, torch.tensor([1.0, 1.0, -1.0], dtype=torch.float64), rtol=1e-12, atol=1e-12)
    raw = dictionary.matched_write_cosines(decoder, write, torch.tensor([1, 5, 5]), centered=False, chunk=2)  # (m,)
    assert float(raw[0]) < 0.99 and float(raw[1]) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="Pole columns"):
        dictionary.matched_write_cosines(decoder, write, torch.tensor([1, 6, 0]))


def test_the_search_returns_to_a_sparse_native_basis() -> None:
    generator = torch.Generator().manual_seed(2)
    width = 12
    # Independent heavy-tailed units, sparse in the native basis: Laplace draws (a difference of two exponentials),
    # each unit silent on most residues.
    exponentials = -torch.log(torch.rand(2, 20_000, width, generator=generator, dtype=torch.float64))  # (2, r, f)
    sources = (exponentials[0] - exponentials[1]) * (torch.rand(20_000, width, generator=generator) < 0.2)  # (r, f)
    samples = rotation_search.standardize(sources)  # (r, f)
    search = rotation_search.sparsest_rotation(samples, seed=7, steps=400)
    assert search.objective[-1] > search.objective[0]
    assert rotations.basis_recovery(search.rotation) > 0.95
    native = float(rotation_search.native_objective(samples))
    identity = torch.eye(width, dtype=torch.float64)  # (f, f)
    assert native == pytest.approx(float(rotation_search.fourth_power_objective(samples, identity)), rel=1e-12)
    assert search.objective[-1] == pytest.approx(native, rel=1e-3)


def test_standardization_reads_new_residues_in_the_sample_s_coordinates() -> None:
    generator = torch.Generator().manual_seed(4)
    samples = torch.randn(500, 5, generator=generator, dtype=torch.float32) * torch.tensor([1.0, 2.0, 0.5, 3.0, 1.0])  # (r, f)
    samples[:, 4] = 2.5  # a constant unit
    standard = rotation_search.standardization(samples)
    centered = samples.double() - samples.double().mean(dim=0, keepdim=True)  # (r, f)
    expected = centered / centered.std(dim=0, keepdim=True)  # (r, f), the constant unit's column 0/0
    torch.testing.assert_close(rotation_search.standardize(samples)[:, :4], expected[:, :4], rtol=0, atol=0)
    assert bool((rotation_search.standardize(samples)[:, 4] == 0).all())
    fresh = torch.randn(30, 5, generator=generator)  # (r', f)
    narrow = standard.to("cpu", torch.float32).apply(fresh)  # (r', f)
    assert narrow.dtype == torch.float32 and bool((narrow[:, 4] == 0).all())
    torch.testing.assert_close(narrow[:, :4], ((fresh.double() - standard.mean) / standard.scale)[:, :4].float())


def test_the_search_stops_once_a_step_gains_less_than_the_tolerance() -> None:
    generator = torch.Generator().manual_seed(6)
    exponentials = -torch.log(torch.rand(2, 5_000, 6, generator=generator, dtype=torch.float64))  # (2, r, f)
    samples = rotation_search.standardize(exponentials[0] - exponentials[1])  # (r, f)
    loose = rotation_search.sparsest_rotation(samples, seed=1, steps=300, tolerance=1e-2)
    tight = rotation_search.sparsest_rotation(samples, seed=1, steps=300, tolerance=0.0)
    assert len(loose.objective) < len(tight.objective)
    assert loose.objective == tight.objective[:len(loose.objective)]


def test_the_search_finds_no_basis_in_isotropic_gaussian_activity() -> None:
    generator = torch.Generator().manual_seed(3)
    samples = rotation_search.standardize(torch.randn(20_000, 12, generator=generator, dtype=torch.float64))  # (r, f)
    start = rotations.basis_recovery(rotations.haar_rotation(12, seed=7, dtype=torch.float64))
    search = rotation_search.sparsest_rotation(samples, seed=7, steps=100)
    # Gaussian activity has no preferred axes: the objective barely moves and neither does recovery, far from 1.
    assert search.objective[-1] - search.objective[0] < 0.05 * search.objective[0]
    assert rotations.basis_recovery(search.rotation) < 0.9
    assert start < 0.9
