"""Open domains with ghost atoms (plan task S1-T09), the unit a tiled run evaluates.

A periodic cell is evaluated as an open domain: its atoms are the locals, the periodic images within reach of them
are ghosts that only send, in a non-periodic box. The per-layer sweeps run on it; after each sweep the ghosts'
layer outputs are copied from the locals they are images of, and what a sweep adds to ghost rows is folded back.
Energy, forces and virial must then be those of the periodic call. Every test creates an engine and skips when
its model file is absent.
"""
from __future__ import annotations

import ctypes
import itertools
import os

import numpy as np
import pytest
from gpu_support import find_model, srtio3, unfolded

from loupmd import BackendError, LoupEngine, ensure_loup_bundle
from loupmd import _core

SKIN = 0.5
_dp = ctypes.POINTER(ctypes.c_double)
_ip = ctypes.POINTER(ctypes.c_int)


def _bind(lib):
    lib.loup_debug_set_domain.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, _ip, ctypes.c_double]
    lib.loup_debug_evaluate_domain.argtypes = [ctypes.c_void_p, _dp, _dp, _ip, _dp, _dp, _dp]
    lib.loup_debug_set_domain.restype = lib.loup_debug_evaluate_domain.restype = ctypes.c_int


def _oxide():
    at = srtio3(3)
    at.positions += np.random.default_rng(7).normal(scale=0.04, size=at.positions.shape)
    at.set_cell(at.cell.array * np.array([[1.01, 0.004, 0.0], [0.0, 0.995, 0.003], [0.002, 0.0, 1.004]]),
                scale_atoms=True)
    return at


def _water():
    from ase.io import read

    from loupmd.bench import suites

    at = read(suites.find_file("water_216.extxyz", {}))      # the box shipped with the package
    at.positions += np.random.default_rng(8).normal(scale=0.02, size=at.positions.shape)
    return at


def _images(at, reach):
    """Positions of the periodic images within ``reach`` of an atom of the cell, and the atom each is an image of.
    One shell of image cells is enough while the cell is wider than ``reach``."""
    pos, cell = at.positions, at.cell.array
    assert np.all(at.cell.cellpar()[:3] > reach), "the test's image shell assumes a cell wider than the reach"
    ghosts, ghost_of = [], []
    for shift in itertools.product((-1, 0, 1), repeat=3):
        if shift == (0, 0, 0):
            continue
        moved = pos + np.asarray(shift, dtype=float) @ cell
        nearest = np.full(len(pos), np.inf)
        for start in range(0, len(pos), 256):   # in slices: the full distance matrix of the water box is large
            d = np.linalg.norm(moved[start:start + 256, None, :] - pos[None, :, :], axis=2)
            nearest[start:start + 256] = d.min(axis=1)
        keep = np.nonzero(nearest < reach)[0]
        ghosts.append(moved[keep])
        ghost_of.extend(keep.tolist())
    return np.concatenate(ghosts), np.asarray(ghost_of, dtype=np.int32)


def _evaluate_domain(eng, n_local, z_all, positions, cell, ghost_of):
    lib = eng._lib
    _bind(lib)
    z = np.ascontiguousarray(z_all, dtype=np.int32)
    n_ghost = len(z) - n_local
    rc = lib.loup_debug_set_domain(eng._h, n_local, n_ghost, z.ctypes.data_as(_ip), SKIN)
    if rc != 0:
        raise BackendError(_core.last_error(eng._h), call="loup_debug_set_domain")
    pos = np.ascontiguousarray(positions, dtype=np.float64)
    cel = np.ascontiguousarray(cell, dtype=np.float64)
    energy = ctypes.c_double()
    forces = np.zeros((n_local, 3))
    stress = np.zeros((3, 3))
    gmap = np.ascontiguousarray(ghost_of, dtype=np.int32) if n_ghost else None
    rc = lib.loup_debug_evaluate_domain(eng._h, pos.ctypes.data_as(_dp), cel.ctypes.data_as(_dp),
                                        gmap.ctypes.data_as(_ip) if n_ghost else None, ctypes.byref(energy),
                                        forces.ctypes.data_as(_dp), stress.ctypes.data_as(_dp))
    if rc != 0:
        raise BackendError(_core.last_error(eng._h), call="loup_debug_evaluate_domain")
    return energy.value, forces, stress


def _periodic(bundle, at):
    """The periodic call without the skip-chain fold: the operations a domain runs (gpu_support.unfolded)."""
    with unfolded():
        eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=SKIN)
    e, f, s = eng.evaluate(at.positions, at.cell.array)
    return e, f, s, eng.info().r_max


# (model file, structure, generic=True for a model of the specialised architecture, layers)
CASES = [
    ("mace-omat-0-small.model", _oxide, False, 2),
    ("mace-omat-0-medium.model", _oxide, True, 2),
    ("mace-mh-1.model", _oxide, False, 2),
    ("MACE-OFF23_medium.model", _water, False, 2),
    ("MACE-omol-0-extra-large-1024.model", _water, False, 3),
    # a pruned conv layer and compact layers (see tests/gpu/test_tiled.py's cases)
    ("2023-12-03-mace-128-L1_epoch-199.model", _oxide, False, 2),
    ("MACE_MPtrj_2022.9.model", _oxide, False, 2),
]
IDS = [c[0].split(".model")[0] for c in CASES]


@pytest.mark.parametrize("model,structure,generic,layers", CASES, ids=IDS)
@pytest.mark.full
def test_a_cell_as_an_open_domain_with_its_images_as_ghosts(model, structure, generic, layers, monkeypatch):
    monkeypatch.delenv("LOUP_CHAIN_FOLD", raising=False)   # the domain's engine is a default one: it builds the
    at = structure()                                       # fold and leaves it off for the domain
    n = len(at)
    zs = sorted(set(at.get_atomic_numbers().tolist()))
    bundle = ensure_loup_bundle(find_model(model), zs, generic=generic if "omat-0-medium" in model else None)
    e_a, f_a, s_a, r_max = _periodic(bundle, at)
    e_b, f_b, s_b, _ = _periodic(bundle, at)
    # The same periodic call on other GEMM kernels (no tensor-core hybrids): what float32 rounding in another order
    # of operations does to the result. A domain's GEMMs have other row counts, so it sees the same kind of change.
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    e_c, f_c, s_c, _ = _periodic(bundle, at)
    monkeypatch.delenv("LOUP_NO_HYBRID")

    reach = r_max + SKIN + 0.2
    ghosts, ghost_of = _images(at, reach)
    everyone = np.concatenate([at.positions, ghosts])
    pad = reach + 1.0                                  # images of the box are then further than the list reaches
    origin = everyone.min(axis=0) - pad
    box = np.diag(np.ptp(everyone, axis=0) + 2.0 * pad)
    z_all = np.concatenate([at.get_atomic_numbers(), at.get_atomic_numbers()[ghost_of]])
    eng = LoupEngine(bundle)
    assert eng.info().n_layers == layers
    e, f, s_box = _evaluate_domain(eng, n, z_all, everyone - origin, box, ghost_of)
    stress = s_box * np.linalg.det(box) / at.get_volume()   # the same virial, per volume of the cell

    spread = (abs(e_a - e_b) / n, np.abs(f_a - f_b).max(), np.abs(s_a - s_b).max())
    other = (abs(e_c - e_a) / n, np.abs(f_c - f_a).max(), np.abs(s_c - s_a).max())
    diff = (abs(e - e_a) / n, np.abs(f - f_a).max(), np.abs(stress - s_a).max())
    print(f"open domain {model}: {n} locals, {len(ghost_of)} ghosts; dE {diff[0]:.2e} eV/atom, dF {diff[1]:.2e} "
          f"eV/A, dS {diff[2]:.2e} eV/A^3 (two periodic engines: {spread[0]:.1e}, {spread[1]:.1e}, {spread[2]:.1e}; "
          f"periodic on other GEMM kernels: {other[0]:.1e}, {other[1]:.1e}, {other[2]:.1e})")
    # Forces: the plan's bound. Energy and stress: a tenth of the accuracy gate's floors (0.01 meV/atom,
    # 1e-7 eV/A^3); the plan's 1e-7 eV/atom is below what another order of float32 operations already changes
    # (PLAN.md 1.3 D16).
    bounds = (1e-6, 3e-6, 1e-7)
    for name, d, sp, bound in zip(("energy", "forces", "stress"), diff, spread, bounds):
        assert d <= max(bound, 5.0 * sp), f"{name}: the open domain differs by {d:.3e} (two periodic engines: {sp:.3e})"


def test_sweeps_on_a_periodic_system_without_ghosts():
    """n_ghost = 0: the same driver on an ordinary periodic cell (a default engine: the fold built, off for the
    domain) against the periodic call without the fold."""
    at = _oxide()
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    e_ref, f_ref, s_ref, _ = _periodic(bundle, at)
    eng = LoupEngine(bundle)
    e, f, s = _evaluate_domain(eng, len(at), at.get_atomic_numbers(), at.positions, at.cell.array, None)
    assert abs(e - e_ref) / len(at) < 1e-7 and np.abs(f - f_ref).max() < 3e-6 and np.abs(s - s_ref).max() < 3e-8


def test_domain_refusals():
    at = _oxide()
    n = len(at)
    z2 = np.ascontiguousarray(np.concatenate([at.get_atomic_numbers(), at.get_atomic_numbers()[:5]]), dtype=np.int32)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    eng = LoupEngine(bundle)
    _bind(eng._lib)
    assert eng._lib.loup_debug_set_domain(eng._h, n, 5, z2.ctypes.data_as(_ip), SKIN) == 0
    with pytest.raises(BackendError, match="the handle holds an open domain"):
        eng.run_nve(1)                                 # public calls do not run on a domain
    pos = np.ascontiguousarray(np.concatenate([at.positions, at.positions[:5] + at.cell.array[0]]))
    box = np.ascontiguousarray(np.diag([60.0, 60.0, 60.0]))
    bad = np.ascontiguousarray([0, 1, 2, 3, n], dtype=np.int32)   # the last one names no local atom
    energy = ctypes.c_double()
    rc = eng._lib.loup_debug_evaluate_domain(eng._h, pos.ctypes.data_as(_dp), box.ctypes.data_as(_dp),
                                             bad.ctypes.data_as(_ip), ctypes.byref(energy), None, None)
    assert rc == -1 and eng.last_error() == f"loup_debug_evaluate_domain: ghost_of[4] = {n} is not a local atom (0 .. {n - 1})"
    eng.set_system(at.get_atomic_numbers(), at.get_masses())      # an ordinary system again
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    assert np.isfinite(e) and np.isfinite(f).all()
