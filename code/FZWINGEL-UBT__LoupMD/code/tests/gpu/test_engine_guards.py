"""API guards from review U1 / U3: a degraded 8-byte table is refused at load, and MD on a handle without positions
fails while one after only `evaluate` starts from rest (not from the previous system's velocities)."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd.export.bundle import read_bundle, write_bundle
from loupmd import LoupEngine, ensure_loup_bundle


def test_run_needs_positions_and_starts_from_rest_after_a_new_system():
    path = find_model("mace-omat-0-small.model")
    at = srtio3(2)
    eng = LoupEngine(ensure_loup_bundle(path, [8, 22, 38]))
    z, m = at.get_atomic_numbers(), at.get_masses()

    eng.set_system(z, m)
    with pytest.raises(RuntimeError, match="loup_run_nve: no positions or neighbour list"):
        eng.run_nve(1)  # no positions, no neighbour list
    with pytest.raises(RuntimeError, match="loup_profile_force: no positions or neighbour list"):
        eng.profile_force(1, 1)

    hot = np.random.default_rng(0).normal(scale=0.5, size=(len(at), 3))  # ~thousands of K
    eng.set_state(at.positions, hot, at.cell.array)
    assert eng.run_nve(1).final_temperature_k > 1000.0

    eng.set_system(z, m)  # the same handle, a new system: its velocities must not survive
    eng.evaluate(at.positions, at.cell.array)
    _, vel, _, _ = eng.get_state()
    assert not vel.any()
    eng.run_nve(1)  # and a run is accepted after only evaluate


@pytest.mark.parametrize("temp_k,friction", [(float("nan"), 0.01), (-1.0, 0.01), (300.0, float("inf")), (300.0, -0.01)])
def test_langevin_rejects_bad_temperature_or_friction(temp_k, friction):
    path = find_model("mace-omat-0-small.model")
    at = srtio3(2)
    eng = LoupEngine(ensure_loup_bundle(path, [8, 22, 38]))
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    eng.set_state(at.positions, np.zeros((len(at), 3)), at.cell.array)
    reason = "temp_k" if temp_k != 300.0 else "friction_per_fs"
    with pytest.raises(RuntimeError, match=reason + " must be finite and not negative"):
        eng.run_langevin(1, temp_k=temp_k, friction_per_fs=friction)
    assert np.isfinite(eng.run_langevin(1).final_temperature_k)  # the state was not touched


def test_a_packed_table_far_beyond_the_gated_error_is_refused(tmp_path):
    path = find_model("mace-omat-0-small.model")
    good = ensure_loup_bundle(path, [8, 22, 38])
    meta, T = read_bundle(good)
    LoupEngine(good)  # the exported bundle loads
    key = next(k for k in T if k.endswith(".spline") and not int(meta.get(k[:-6] + "first_hidden", "0")))
    sp = T[key].copy()
    # One entry 2^40 larger: the table's 5-bit shared exponent range (32 octaves) then quantises every column on a
    # grid set by that entry, far coarser than the certified table.
    sp[0, 0, 0, :] *= 2.0 ** 40
    T = dict(T, **{key: sp})
    bad = tmp_path / "degraded.loup"
    write_bundle(bad, meta, T)
    with pytest.raises(RuntimeError, match="8-byte table error"):  # the packing check, not an earlier one
        LoupEngine(bad)


def test_a_bundle_of_the_retired_specialised_path_is_refused(tmp_path):
    """JIT_DESIGN.md stage 5: arch omat0_medium_spec bundles are no longer loaded; the message says to re-export."""
    good = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    meta, T = read_bundle(good)
    old = tmp_path / "spec.loup"
    write_bundle(old, dict(meta, arch="omat0_medium_spec"), T)
    with pytest.raises(RuntimeError, match="'omat0_medium_spec' is no longer supported; re-export it"):
        LoupEngine(old)


def test_charge_and_spin_are_refused_for_a_model_without_their_embedding(tmp_path):
    """Only models with a total-charge / spin embedding (MACE-OMOL-0) take them; any other model must not silently
    ignore a requested charge."""
    import subprocess

    path = find_model("mace-omat-0-small.model")
    with pytest.raises(subprocess.CalledProcessError):
        ensure_loup_bundle(path, [8, 22, 38], cache_dir=str(tmp_path), charge=1)
    with pytest.raises(subprocess.CalledProcessError):
        ensure_loup_bundle(path, [8, 22, 38], cache_dir=str(tmp_path), spin_multiplicity=3)


def test_fractional_charge_or_spin_is_rejected_before_any_export(tmp_path):
    """Charge and spin are categorical model inputs: 0.5 must not truncate to a neutral bundle."""
    path = find_model("mace-omat-0-small.model")
    with pytest.raises(ValueError, match="charge"):
        ensure_loup_bundle(path, [8, 22, 38], cache_dir=str(tmp_path), charge=0.5)
    with pytest.raises(ValueError, match="spin_multiplicity"):
        ensure_loup_bundle(path, [8, 22, 38], cache_dir=str(tmp_path), spin_multiplicity=1.5)
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("model", ["mace-omat-0-medium.model", "mace-omat-0-small.model"])
def test_reused_list_after_a_cell_change_sees_a_pair_cross_the_cutoff(model):
    """Strain the cell (forces a rebuild), then move one atom by less than skin/2 so a pair just outside r_max comes
    inside it while the list is reused: the engine must agree with a fresh one at every step (cf. Symmetrix-XL PR 41:
    the displacement reference after a cell change, and skin-shell edges)."""
    from ase.geometry import get_distances

    path = find_model(model)
    at = srtio3(3)  # 11.8 A: room for pairs near r_max = 6 A without self-images
    at.positions += np.random.default_rng(5).normal(scale=0.05, size=at.positions.shape)
    eng = LoupEngine(ensure_loup_bundle(path, [8, 22, 38]))
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.evaluate(at.positions, at.cell.array)

    strained = at.copy()
    strained.set_cell(at.cell.array * 1.01, scale_atoms=True)
    vec, d = get_distances(strained.positions, cell=strained.cell, pbc=True)
    r_max = 6.0
    i, j = np.argwhere((d > r_max + 0.02) & (d < r_max + 0.12))[0]
    moved = strained.copy()
    moved.positions[i] += 0.15 * vec[i, j] / np.linalg.norm(vec[i, j])  # 0.15 A < skin / 2: no rebuild
    _, d2 = get_distances(moved.positions, cell=moved.cell, pbc=True)
    assert d2[i, j] < r_max

    for cfg in (strained, moved):
        e, f, s = eng.evaluate(cfg.positions, cfg.cell.array)
        fresh = LoupEngine(ensure_loup_bundle(path, [8, 22, 38]))
        fresh.set_system(cfg.get_atomic_numbers(), cfg.get_masses(), skin=0.5)
        e2, f2, s2 = fresh.evaluate(cfg.positions, cfg.cell.array)
        assert abs(e - e2) < 1e-4 and np.abs(f - f2).max() < 1e-4 and np.abs(s - s2).max() < 1e-6
