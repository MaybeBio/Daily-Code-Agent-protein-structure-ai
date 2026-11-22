from __future__ import annotations

import torch

from plm_interpretability.units import write_sums


def _write(width: int = 24, units: int = 40, seed: int = 0) -> torch.Tensor:
    return torch.randn(width, units, generator=torch.Generator().manual_seed(seed))  # (d, f)


def test_pursuit_recovers_planted_sums() -> None:
    write = _write()
    atoms = write_sums.write_atoms([write])  # (f, d)
    planted = torch.stack((atoms[3], atoms[5] - 0.8 * atoms[11], atoms[1] + atoms[2] + atoms[30]))
    cosines, chosen = write_sums.pursuit(torch.nn.functional.normalize(planted, dim=1), atoms, cap=8)
    assert write_sums.sizes(cosines, stop=0.999).tolist() == [1, 2, 3]
    assert chosen[0, 0] == 3 and set(chosen[1, :2].tolist()) == {5, 11} and set(chosen[2, :3].tolist()) == {1, 2, 30}
    assert bool((cosines[:, 1:] >= cosines[:, :-1] - 1e-5).all()) and bool((cosines <= 1 + 1e-5).all())


def test_sizes_and_taxonomy() -> None:
    cosines = torch.tensor([[0.8, 0.9], [0.2, 0.75], [0.1, 0.3]])
    size = write_sums.sizes(cosines, stop=0.7)
    assert size.tolist() == [1, 2, 3]
    assert write_sums.taxonomy(size, cap=2) == {"copy": 1 / 3, "coalition": 1 / 3, "unmatched": 1 / 3, "median_size": 1.5}


def test_decoder_directions_of_single_units_are_copies() -> None:
    writes = [_write(seed=0), _write(seed=1)]
    generator = torch.Generator().manual_seed(2)
    decoder = torch.cat((writes[0][:, :6].T * 3.0, -writes[1][:, 4:8].T, torch.randn(5, 24, generator=generator)))  # (15, d)
    frame, report = write_sums.run_write_sums(decoder, writes, cap=4, random_directions=64)
    assert frame["size"].iloc[:10].tolist() == [1] * 10
    assert [atoms[0] for atoms in frame["first_atoms"].iloc[:10]] == [0, 1, 2, 3, 4, 5, 44, 45, 46, 47]
    assert report["atoms"] == 80 and report["native"]["copy"] >= 10 / 15
    # No unit's write vector is an axis of the rotated basis, so the copies are gone there.
    assert report["rotated"]["copy"] < report["native"]["copy"]
    assert report["random"]["steps"] == 16 and set(report["random"]["size_quantiles"]) == {"0.1", "0.5", "0.9"}
