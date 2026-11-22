"""The wavefront schedule of the tiled mode (plan task S5-T08), host code in ``src/tile_plan.cu``.

Sweep 2 (the last layer) visits the tiles in order; sweep 1 (the forward sweep) runs on a tile just before the first
sweep-2 tile that reads it, sweep 3 (the backward sweep) just after the last sweep-2 tile that adds to its
receivers. Between a tile's sweeps 1 and 3 its receivers' rows must be held, so the most receivers held at once is
the size of the row pool. Compiled with g++ like ``test_tile_plan.py``; needs neither a GPU nor libloupmd.so.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "tile_plan.cu"
REACH = 6.5
c_ll, c_int, c_double, ptr = ctypes.c_longlong, ctypes.c_int, ctypes.c_double, ctypes.POINTER


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    gxx = shutil.which("g++")
    if gxx is None or not SOURCE.is_file():
        pytest.skip("needs g++ and the source tree")
    out = tmp_path_factory.mktemp("tile_schedule") / "libtileplan.so"
    done = subprocess.run([gxx, "-x", "c++", "-std=c++17", "-O2", "-shared", "-fPIC", f"-I{ROOT / 'src'}",
                           f"-I{ROOT / 'include'}", str(SOURCE), "-o", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]
    lib = ctypes.CDLL(str(out))
    lib.loup_tile_plan.argtypes = [ptr(c_double), c_ll, ptr(c_double), c_int, c_ll, ptr(c_int), c_double, ptr(c_int),
                                   ptr(c_ll), ptr(c_ll), ptr(c_int)]
    lib.loup_tile_plan_copy.argtypes = [ptr(c_ll), ptr(c_int), ptr(c_int), ptr(c_ll), ptr(c_int), ptr(c_int)]
    lib.loup_tile_plan_error.restype = ctypes.c_char_p
    lib.loup_wavefront_schedule.argtypes = [c_ll, ptr(c_ll), ptr(c_ll), ptr(c_ll), ptr(c_ll), c_int, ptr(c_int),
                                            ptr(c_ll), ptr(c_ll)]
    lib.loup_tile_plan_wavefront.argtypes = [ptr(c_double), c_ll, ptr(c_double), c_int, c_double, c_double, ptr(c_int),
                                             ptr(c_ll), ptr(c_ll), ptr(c_int)]
    lib.loup_tile_dependencies.argtypes = [ptr(c_ll), ptr(c_ll), ptr(c_ll), ptr(c_ll)]
    return lib


def _schedule(lib, needs, ready, counts, group=1):
    tiles = len(counts)
    needs_ptr = np.zeros(tiles + 1, dtype=np.int64)
    needs_ptr[1:] = np.cumsum([len(n) for n in needs])
    flat = np.ascontiguousarray(np.concatenate([np.asarray(n, dtype=np.int64) for n in needs]))
    ready = np.ascontiguousarray(ready, dtype=np.int64)
    counts = np.ascontiguousarray(counts, dtype=np.int64)
    sweep = np.zeros(3 * tiles, dtype=np.int32)
    tile = np.zeros(3 * tiles, dtype=np.int64)
    peak = c_ll()
    status = lib.loup_wavefront_schedule(tiles, needs_ptr.ctypes.data_as(ptr(c_ll)), flat.ctypes.data_as(ptr(c_ll)),
                                         ready.ctypes.data_as(ptr(c_ll)), counts.ctypes.data_as(ptr(c_ll)), group,
                                         sweep.ctypes.data_as(ptr(c_int)), tile.ctypes.data_as(ptr(c_ll)),
                                         ctypes.byref(peak))
    assert status == 0, lib.loup_tile_plan_error().decode()
    return list(zip(sweep.tolist(), tile.tolist())), peak.value


def _check(steps, peak, needs, ready, counts):
    tiles = len(counts)
    assert sorted(steps) == sorted((s, t) for s in (1, 2, 3) for t in range(tiles))
    position = {step: i for i, step in enumerate(steps)}
    assert [t for s, t in steps if s == 2] == list(range(tiles))
    for t in range(tiles):
        assert all(position[(1, u)] < position[(2, t)] for u in needs[t])
        assert position[(3, t)] > position[(2, ready[t])]
    live = most = 0
    for sweep, t in steps:
        live += counts[t] if sweep == 1 else -counts[t] if sweep == 3 else 0
        most = max(most, live)
    assert peak == most and live == 0


def _changes(steps):
    return sum(a[0] != b[0] for a, b in zip(steps, steps[1:]))


@pytest.mark.parametrize("group", [1, 3, 5])
def test_the_schedule_runs_every_sweep_once_after_what_it_reads_on_a_periodic_ring(lib, group):
    """FastMACE's invariants (tests/cpu/test_tiled.py there): a ring of 16 tiles, tile t reads its neighbours' rows
    and its receivers sit in their halos too."""
    tiles = 16
    needs = [sorted({(t - 1) % tiles, t, (t + 1) % tiles}) for t in range(tiles)]
    ready = [tiles - 1 if t == 0 else min(t + 1, tiles - 1) for t in range(tiles)]
    counts = [3] * tiles
    steps, peak = _schedule(lib, needs, ready, counts, group)
    _check(steps, peak, needs, ready, counts)
    assert peak < sum(counts)
    assert _changes(steps) <= 3 * -(-tiles // group)
    if group > 1:
        assert _changes(steps) < _changes(_schedule(lib, needs, ready, counts)[0])


def test_a_schedule_that_cannot_hold_is_refused(lib):
    """A tile that is ready before itself (its sweep 3 would precede its own sweep 2), or a need out of range."""
    needs = [[0, 1], [0, 1]]
    with pytest.raises(AssertionError):
        _schedule(lib, needs, [0, 0], [1, 1])
    with pytest.raises(AssertionError):
        _schedule(lib, [[0, 2], [0, 1]], [1, 1], [1, 1])


def _crystal(cells):
    """Cubic SrTiO3 (a = 3.905 A), cells[i] unit cells along axis i, rattled."""
    a = 3.905
    basis = np.array([[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]) * a
    grid = np.stack(np.meshgrid(*[np.arange(c) for c in cells], indexing="ij"), -1).reshape(-1, 3) * a
    positions = (grid[:, None, :] + basis[None]).reshape(-1, 3)
    positions += np.random.default_rng(2).normal(scale=0.03, size=positions.shape)
    return positions, np.diag(np.array(cells, dtype=float) * a)


def _plan_and_dependencies(lib, positions, cell, shape, skin=0.0):
    positions = np.ascontiguousarray(positions)
    cell = np.ascontiguousarray(cell)
    shape_c = np.ascontiguousarray(shape, dtype=np.int32)
    tiles, ghosts, grid = c_ll(), c_ll(), (c_int * 3)()
    assert lib.loup_tile_plan_wavefront(positions.ctypes.data_as(ptr(c_double)), len(positions),
                                        cell.ctypes.data_as(ptr(c_double)), 10 ** 9, REACH, skin,
                                        shape_c.ctypes.data_as(ptr(c_int)), ctypes.byref(tiles), ctypes.byref(ghosts),
                                        grid) == 0, lib.loup_tile_plan_error().decode()
    t = tiles.value
    local_ptr, ghost_ptr = np.zeros(t + 1, dtype=np.int64), np.zeros(t + 1, dtype=np.int64)
    local, ghost = np.zeros(len(positions), dtype=np.int32), np.zeros(ghosts.value, dtype=np.int32)
    assert lib.loup_tile_plan_copy(local_ptr.ctypes.data_as(ptr(c_ll)), local.ctypes.data_as(ptr(c_int)), None,
                                   ghost_ptr.ctypes.data_as(ptr(c_ll)), ghost.ctypes.data_as(ptr(c_int)), None) == 0
    needs_ptr, ready, total = np.zeros(t + 1, dtype=np.int64), np.zeros(t, dtype=np.int64), c_ll()
    assert lib.loup_tile_dependencies(needs_ptr.ctypes.data_as(ptr(c_ll)), None, ready.ctypes.data_as(ptr(c_ll)),
                                      ctypes.byref(total)) == 0
    needs = np.zeros(total.value, dtype=np.int64)
    assert lib.loup_tile_dependencies(needs_ptr.ctypes.data_as(ptr(c_ll)), needs.ctypes.data_as(ptr(c_ll)),
                                      ready.ctypes.data_as(ptr(c_ll)), ctypes.byref(total)) == 0
    return (local_ptr, local, ghost_ptr, ghost), [needs[needs_ptr[i]:needs_ptr[i + 1]].tolist() for i in range(t)], \
        ready.tolist()


def test_the_dependencies_of_a_plan_name_every_tile_a_tile_reads_and_the_last_that_reads_it(lib):
    positions, cell = _crystal((24, 4, 4))
    (local_ptr, local, ghost_ptr, ghost), needs, ready = _plan_and_dependencies(lib, positions, cell, (8, 2, 1))
    tiles = len(local_ptr) - 1
    tile_of = np.empty(len(positions), dtype=np.int64)
    for t in range(tiles):
        tile_of[local[local_ptr[t]:local_ptr[t + 1]]] = t
    last = list(range(tiles))
    for t in range(tiles):
        atoms = np.concatenate([local[local_ptr[t]:local_ptr[t + 1]], ghost[ghost_ptr[t]:ghost_ptr[t + 1]]])
        owners = sorted(set(tile_of[atoms].tolist()))
        assert needs[t] == owners                              # ascending, itself included
        for u in owners:
            last[u] = max(last[u], t)
    assert ready == last and all(ready[u] >= u for u in range(tiles))


def test_twenty_layers_hold_under_a_quarter_of_the_atoms(lib):
    """S5-T08's acceptance on the schedule: tiles in 20 layers along the grid's slowest axis (blocks thicker than
    the reach), the row pool (the peak) under 25% of the atoms."""
    positions, cell = _crystal((80, 6, 6))                     # 14,400 atoms; layers 15.6 A thick
    pools = {}
    for skin in (0.0, REACH):
        (local_ptr, *_), needs, ready = _plan_and_dependencies(lib, positions, cell, (20, 2, 2), skin)
        counts = np.diff(local_ptr).tolist()
        assert sum(counts) == len(positions) and len(counts) == (80 if skin == 0.0 else 88)
        steps, peak = _schedule(lib, needs, ready, counts, group=4)
        _check(steps, peak, needs, ready, counts)
        pools[skin] = peak / len(positions)
    print(f"20 layers: row pool {pools[0.0]:.1%} of the atoms without the boundary skins, {pools[REACH]:.1%} with")
    assert pools[REACH] < 0.25 and pools[REACH] < pools[0.0]


def test_the_boundary_skins_hold_the_atoms_within_the_skin_of_the_faces(lib):
    positions, cell = _crystal((40, 4, 4))
    (local_ptr, local, *_), _, _ = _plan_and_dependencies(lib, positions, cell, (5, 1, 1), REACH)
    assert len(local_ptr) - 1 == 7                             # skin, 5 layers, skin
    x = np.mod(positions[:, 0], cell[0, 0])
    first, last = local[local_ptr[0]:local_ptr[1]], local[local_ptr[6]:local_ptr[7]]
    assert np.all(x[first] < REACH) and np.all(x[last] >= cell[0, 0] - REACH)
    inner = np.setdiff1d(np.arange(len(positions)), np.concatenate([first, last]))
    assert np.all((x[inner] >= REACH) & (x[inner] < cell[0, 0] - REACH))
