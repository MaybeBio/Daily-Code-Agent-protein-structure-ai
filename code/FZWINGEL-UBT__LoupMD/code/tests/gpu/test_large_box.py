"""Large boxes (plan task S5-T09): the same crystal piece in a 100 A box and in a 1,000 A box, placed near the far
corner where float32 coordinates would lose 6e-5 A, gives the same forces to rounding in the whole-system and in
the tiled call. Every test creates engines and skips when its model file is absent."""
from __future__ import annotations

import gc

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd import LoupEngine, ensure_loup_bundle

SKIN = 0.5


def _piece():
    """A 1,080-atom SrTiO3 block, rattled: no periodic image of it is within reach in either box."""
    at = srtio3(6)
    at.positions += np.random.default_rng(9).normal(scale=0.03, size=at.positions.shape)
    return at


def _whole(bundle, at, positions, cell):
    eng = LoupEngine(bundle)
    try:
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=SKIN)
        return eng.evaluate(positions, cell)
    finally:
        del eng
        gc.collect()


def _tiled(bundle, at, positions, cell, receivers):
    eng = LoupEngine(bundle)
    try:
        return eng.evaluate_tiled(at.numbers, positions, cell, receivers, skin=SKIN)
    finally:
        del eng
        gc.collect()


@pytest.mark.full
@pytest.mark.parametrize("call", ["whole", "tiled"])
def test_a_1000_angstrom_box_gives_the_100_angstrom_boxs_forces(call, monkeypatch):
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")     # same GEMM kernels on both sides whatever the row counts (D60)
    at = _piece()
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    small_cell, big_cell = np.eye(3) * 100.0, np.eye(3) * 1000.0
    small = at.positions + 30.0
    big = at.positions + 960.0 - at.positions.max(axis=0)   # the far corner: coordinates up to 960 A
    if call == "whole":
        e_s, f_s, _ = _whole(bundle, at, small, small_cell)
        e_b, f_b, _ = _whole(bundle, at, big, big_cell)
    else:
        e_s, f_s, _, t_s = _tiled(bundle, at, small, small_cell, 400)
        e_b, f_b, _, t_b = _tiled(bundle, at, big, big_cell, 400)
        assert t_s >= 2 and t_b >= 2
    df = np.abs(f_b - f_s).max()
    print(f"large box, {call}: dE {abs(e_b - e_s) / len(at):.2e} eV/atom, dF {df:.2e} eV/A")
    assert abs(e_b - e_s) / len(at) <= 1e-7
    assert df <= 1e-5


@pytest.mark.full
def test_an_edge_count_beyond_the_index_range_is_refused_and_auto_runs_it_in_tiles(monkeypatch):
    """The whole-system list indexes edges in int (e * 3, e * 4): above its limit a call is refused with a message,
    never wrapped, and the capacity plan runs the system in tiles. LOUP_DEBUG_EDGE_LIMIT lowers the limit (536,870,911
    edges) to a size this test can build."""
    from loupmd import BackendError, capacity

    at = srtio3(14)                                  # 13,720 atoms, periodic
    at.positions += np.random.default_rng(10).normal(scale=0.03, size=at.positions.shape)
    # SrTiO3 within 6.5 A has about 100 edges per atom: a 4,096-receiver tile about 410,000, the system 1.37M
    limit = 600000
    monkeypatch.setenv("LOUP_DEBUG_EDGE_LIMIT", str(limit))
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    eng = LoupEngine(bundle)
    try:
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=SKIN)
        with pytest.raises(BackendError, match=f"more than the {limit} one call can index"):
            eng.evaluate(at.positions, at.cell.array)
        res = capacity.evaluate(eng, at, skin=SKIN)
    finally:
        del eng
        gc.collect()
    assert res.mode == "tiled" and res.tiles >= 2
    monkeypatch.delenv("LOUP_DEBUG_EDGE_LIMIT")
    e0, f0, _ = _whole(bundle, at, at.positions, at.cell.array)
    assert abs(res.energy - e0) / len(at) <= 1e-6 and np.abs(res.forces - f0).max() <= 1e-5
