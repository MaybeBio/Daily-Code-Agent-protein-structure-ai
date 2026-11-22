from __future__ import annotations

import math
import pytest
import torch

from plm_interpretability.units import rotations


def test_rotation_is_orthogonal_and_reproducible() -> None:
    first = rotations.haar_rotation(64, seed=3, dtype=torch.float64)  # (f, f)
    second = rotations.haar_rotation(64, seed=3, dtype=torch.float64)  # (f, f)
    torch.testing.assert_close(first, second, rtol=0, atol=0)
    torch.testing.assert_close(first.T @ first, torch.eye(64, dtype=torch.float64), rtol=0, atol=1e-12)
    assert not torch.equal(first, rotations.haar_rotation(64, seed=4, dtype=torch.float64))


def test_rotation_preserves_norms() -> None:
    state = torch.randn(100, 32, dtype=torch.float64)  # (r, f)
    rotated = rotations.rotate(state, rotations.haar_rotation(32, seed=0, dtype=torch.float64))  # (r, f)
    torch.testing.assert_close(rotated.norm(dim=1), state.norm(dim=1))


def test_haar_draws_have_no_sign_bias() -> None:
    # Without absorbing R's diagonal signs, QR's convention makes the first column's first entry negative or positive
    # far more often than chance; the Haar measure gives each sign half the time.
    signs = [float(torch.sign(rotations.haar_rotation(8, seed=seed, dtype=torch.float64)[0, 0])) for seed in range(400)]
    assert abs(sum(signs)) / len(signs) < 0.15


def test_basis_recovery_separates_permutations_from_random_rotations() -> None:
    permutation = torch.eye(256)[torch.randperm(256, generator=torch.Generator().manual_seed(0))]  # (f, f)
    signed = permutation * torch.where(torch.rand(256, generator=torch.Generator().manual_seed(1)) > 0.5, 1.0, -1.0)
    assert rotations.basis_recovery(signed) == pytest.approx(1.0)
    random_score = rotations.basis_recovery(rotations.haar_rotation(256, seed=0))
    assert random_score < 0.5
    assert random_score == pytest.approx(math.sqrt(2 * math.log(256) / 256), rel=0.5)


def test_mismatched_rotation_raises() -> None:
    with pytest.raises(ValueError):
        rotations.rotate(torch.zeros(3, 4), torch.eye(5))
    with pytest.raises(ValueError):
        rotations.haar_rotation(0, seed=0)
