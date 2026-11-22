"""loup_plan_memory (plan task S1-T10): the device memory of a system, scaled from a small one of the same material.

The comparison with measured memory reads the device's free memory, so it is only valid on a GPU no other process
is allocating on; every test creates an engine.
"""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd import BackendError, LoupEngine, ensure_loup_bundle
from loupmd import _core


def _probe(bundle, rep=3):
    at = srtio3(rep)
    at.positions += np.random.default_rng(1).normal(scale=0.02, size=at.positions.shape)
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.evaluate(at.positions, at.cell.array)
    return eng


def _measured(bundle, probe, rep):
    """Device memory a rep x rep x rep system takes from set_system to its first evaluation, read as the drop of
    free memory (the engine and its model are created before the first reading)."""
    at = srtio3(rep)
    at.positions += np.random.default_rng(1).normal(scale=0.02, size=at.positions.shape)
    eng = LoupEngine(bundle)
    before = probe.plan_memory(1).free_bytes
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.evaluate(at.positions, at.cell.array)
    after = probe.plan_memory(1).free_bytes
    own = eng.plan_memory(len(at))  # the same size, from its own buffers
    del eng
    return before - after, own.whole_bytes


@pytest.mark.parametrize("rep", [10, 16, 20], ids=["5000", "20480", "40000"])
def test_prediction_from_a_small_cell_matches_the_measured_memory(sto_bundle, rep):
    probe = _probe(sto_bundle)
    n = 5 * rep ** 3
    predicted = probe.plan_memory(n)
    assert predicted.mode == _core.LOUP_EXEC_WHOLE
    measured, own = _measured(sto_bundle, probe, rep)
    print(f"memory plan {n} atoms: predicted {predicted.whole_bytes / 1e6:.1f} MB, measured {measured / 1e6:.1f} MB, "
          f"own {own / 1e6:.1f} MB")
    assert abs(predicted.whole_bytes - measured) < 0.04 * measured, (predicted.whole_bytes, measured)
    assert abs(predicted.whole_bytes - own) < 0.03 * own, (predicted.whole_bytes, own)  # the scaling itself


def test_prediction_on_the_generic_path(tmp_path):
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    probe = _probe(bundle)
    predicted = probe.plan_memory(5000)
    measured, own = _measured(bundle, probe, 10)
    print(f"memory plan generic 5000 atoms: predicted {predicted.whole_bytes / 1e6:.1f} MB, measured "
          f"{measured / 1e6:.1f} MB, own {own / 1e6:.1f} MB")
    assert abs(predicted.whole_bytes - measured) < 0.04 * measured, (predicted.whole_bytes, measured)
    assert abs(predicted.whole_bytes - own) < 0.03 * own


def test_plan_scales_with_atoms_and_edges_and_names_what_does_not_fit(sto_bundle):
    probe = _probe(sto_bundle)
    small, large = probe.plan_memory(5000), probe.plan_memory(50000)
    # ten times the atoms: ten times the rows and edges, and the same 64 MB that does not scale (11% of the small one)
    assert 8.5 < large.whole_bytes / small.whole_bytes < 10.5
    dense = probe.plan_memory(5000, edges_per_atom=400.0)
    sparse = probe.plan_memory(5000, edges_per_atom=40.0)
    assert dense.whole_bytes > sparse.whole_bytes
    assert small.free_bytes > 0 and small.tiled_global_bytes == small.tile_workspace_bytes == small.receivers == 0
    too_large = probe.plan_memory(50_000_000)  # of the order of terabytes: needs the capacity mode
    assert too_large.whole_bytes > 10 * too_large.free_bytes and too_large.mode == _core.LOUP_EXEC_TILED


def test_plan_refusals(sto_bundle):
    eng = LoupEngine(sto_bundle)
    with pytest.raises(BackendError, match="loup_plan_memory: no system is set"):
        eng.plan_memory(1000)
    at = srtio3(2)
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    with pytest.raises(BackendError, match="loup_plan_memory: no neighbour list to scale from"):
        eng.plan_memory(1000)
    eng.evaluate(at.positions, at.cell.array)
    with pytest.raises(BackendError, match="loup_plan_memory: n_atoms must be positive, got 0"):
        eng.plan_memory(0)
    assert eng._lib.loup_plan_memory(eng._h, 1000, 0.0, None) == -1
    assert eng.last_error() == "loup_plan_memory: out is NULL"


# ---------------------------------------------------------------- the capacity plan against what a call takes

def _cube(rep):
    at = srtio3(1).repeat((rep, rep, rep))
    at.positions += np.random.default_rng(1).normal(scale=0.04, size=at.positions.shape)
    return at


def test_the_capacity_plans_whole_count_is_the_systems(sto_bundle):
    """loup_plan_execution counts a whole system from a probe tile: every layer's own buffers, less what the
    skip-chain fold never forms. Against the system itself (20,480 atoms): within 4% of the measured memory and
    of the system's own count (measured 17 November 2026: 0.4% and 0.1%)."""
    at = _cube(16)
    probe = _probe(sto_bundle)
    eng = LoupEngine(sto_bundle)
    eng.set_execution(_core.LOUP_EXEC_AUTO, 0, 0.9)
    plan = eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=0.5)
    del eng
    assert plan.mode == _core.LOUP_EXEC_WHOLE
    measured, own = _measured(sto_bundle, probe, 16)
    print(f"capacity plan 20,480 atoms: whole {plan.whole_bytes / 1e6:.1f} MB, measured {measured / 1e6:.1f} MB, own "
          f"{own / 1e6:.1f} MB")
    assert abs(plan.whole_bytes - measured) < 0.04 * measured, (plan.whole_bytes, measured)
    assert abs(plan.whole_bytes - own) < 0.04 * own, (plan.whole_bytes, own)


@pytest.mark.parametrize("fraction", [0.9, 0.25])
def test_the_tiled_plan_is_the_calls_device_peak(fraction):
    """tile-plan-exact: the plan's tiled_global_bytes + tile_workspace_bytes is what the call holds on the device,
    its kept slots included: within 6% of the peak of a kept call (135,000 atoms, OMAT-0 small; measured 1-5% above
    on 13 plans of two models), and the peak stays within the fraction of the budget (2% for what another program
    may take meanwhile)."""
    at = _cube(30)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    eng = LoupEngine(bundle)
    eng.set_execution(_core.LOUP_EXEC_TILED, 0, fraction)
    plan = eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=0.5)
    eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, 0, skin=0.5, compute_stress=False)
    eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, 0, skin=0.5, compute_stress=False)
    ex = eng.last_execution()
    del eng
    predicted = plan.tiled_global_bytes + plan.tile_workspace_bytes
    print(f"tiled plan 135,000 atoms at {fraction}: cap {plan.receivers}, plan {predicted / 1e6:.0f} MB, peak "
          f"{ex.peak_bytes / 1e6:.0f} MB of {ex.budget_bytes / 1e6:.0f} MB")
    assert abs(predicted - ex.peak_bytes) < 0.06 * ex.peak_bytes, (predicted, ex.peak_bytes)
    assert ex.peak_bytes <= (fraction + 0.02) * ex.budget_bytes


def test_prediction_for_a_long_range_model():
    """The long-range part's buffers count too (per-atom charges, potentials and features per SCF step, and the
    k-space arrays, which grow with the cell): MACE-POLAR-1-S, NaCl 8,000 atoms from a 216-atom cell, within 5% of
    the measured memory (18 November 2026: 1.1% above; 23% below before they were counted)."""
    from ase.build import bulk

    def cell_of(rep):
        at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((rep, rep, rep))
        at.positions += np.random.default_rng(1).normal(scale=0.04, size=at.positions.shape)
        return at

    bundle = ensure_loup_bundle(find_model("MACE-POLAR-1-S.model"), [11, 17])
    small, large = cell_of(3), cell_of(10)
    probe = LoupEngine(bundle)
    probe.set_system(small.numbers, small.get_masses(), skin=0.5)
    probe.evaluate(small.positions, small.cell.array)
    predicted = probe.plan_memory(len(large))
    eng = LoupEngine(bundle)
    before = probe.plan_memory(1).free_bytes
    eng.set_system(large.numbers, large.get_masses(), skin=0.5)
    eng.evaluate(large.positions, large.cell.array)
    measured = before - probe.plan_memory(1).free_bytes
    del eng
    print(f"memory plan POLAR-1-S 8,000 atoms: predicted {predicted.whole_bytes / 1e6:.1f} MB, measured "
          f"{measured / 1e6:.1f} MB")
    assert abs(predicted.whole_bytes - measured) < 0.05 * measured, (predicted.whole_bytes, measured)
