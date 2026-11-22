"""loupmd.capacity (plan task S5-T05) against a fake engine: the plan's mode decides between the whole-system call
and the tiled call, a set receiver cap and memory fraction reach the engine, and what is not built is refused."""
from __future__ import annotations

import numpy as np
import pytest
from ase.build import bulk

from loupmd import PlanRefused, _core, capacity
from loupmd.config import CapacityConfig


class PlanEngine:
    def __init__(self, mode, receivers=5000):
        self.mode, self.receivers, self.calls = mode, receivers, []

    def set_execution(self, mode, receivers, memory_fraction):
        self.calls.append(("set_execution", mode, receivers, memory_fraction))

    def plan_execution(self, numbers, positions, cell, skin):
        self.calls.append(("plan_execution", len(numbers), skin))
        return _core.MemoryPlan(whole_bytes=100, tiled_global_bytes=10 if self.mode == _core.LOUP_EXEC_TILED else 0,
                                tile_workspace_bytes=20 if self.mode == _core.LOUP_EXEC_TILED else 0, free_bytes=1000,
                                receivers=self.receivers if self.mode == _core.LOUP_EXEC_TILED else 0, mode=self.mode)

    def set_system(self, numbers, masses, skin=0.5):
        self.calls.append(("set_system", len(numbers), skin))
        self.n = len(numbers)

    def evaluate(self, positions, cell):
        self.calls.append(("evaluate",))
        return -1.0 * self.n, np.zeros((self.n, 3)), np.zeros((3, 3))

    def evaluate_tiled(self, numbers, positions, cell, receivers, skin=0.5):
        self.calls.append(("evaluate_tiled", receivers, skin))
        n = len(numbers)
        return -2.0 * n, np.ones((n, 3)), np.eye(3), 3

    def last_execution(self):
        asked = next((c[1] for c in self.calls if c[0] == "set_execution"), _core.LOUP_EXEC_AUTO)
        mode = _core.LOUP_EXEC_WAVEFRONT if asked == _core.LOUP_EXEC_WAVEFRONT else _core.LOUP_EXEC_TILED
        return _core.Execution(mode=mode, receivers=self.receivers, tiles=3, budget_bytes=900, peak_bytes=700)


ATOMS = bulk("Cu", cubic=True).repeat(2)


def test_a_plan_of_the_whole_system_runs_the_whole_system_call():
    eng = PlanEngine(_core.LOUP_EXEC_WHOLE)
    res = capacity.evaluate(eng, ATOMS, skin=0.4)
    assert res.mode == "whole" and res.tiles == 1 and res.receivers == 0
    assert res.energy == -1.0 * len(ATOMS)
    assert [c[0] for c in eng.calls] == ["set_execution", "plan_execution", "set_system", "evaluate"]
    assert eng.calls[0] == ("set_execution", _core.LOUP_EXEC_AUTO, 0, 0.9)
    assert eng.calls[2] == ("set_system", len(ATOMS), 0.4)
    assert res.peak_bytes == 100 and res.budget_bytes == 1000     # the plan's estimate in the whole mode


def test_a_tiled_plan_runs_the_tiled_call_with_the_plans_cap():
    eng = PlanEngine(_core.LOUP_EXEC_TILED, receivers=6144)
    res = capacity.evaluate(eng, ATOMS, CapacityConfig(memory_fraction=0.8))
    assert res.mode == "tiled" and res.receivers == 6144 and res.tiles == 3
    assert eng.calls[0] == ("set_execution", _core.LOUP_EXEC_AUTO, 0, 0.8)
    assert eng.calls[-1] == ("evaluate_tiled", 6144, 0.5)
    assert res.energy == -2.0 * len(ATOMS) and res.peak_bytes == 700 and res.budget_bytes == 900


def test_a_set_mode_and_cap_reach_the_engine():
    eng = PlanEngine(_core.LOUP_EXEC_TILED, receivers=2000)
    capacity.evaluate(eng, ATOMS, CapacityConfig(mode="tiled", receivers=2000))
    assert eng.calls[0] == ("set_execution", _core.LOUP_EXEC_TILED, 2000, 0.9)


def test_the_wavefront_mode_reaches_the_engine_and_says_it_ran():
    """S5-T08: the engine runs the tiled call with the wavefront schedule and reports LOUP_EXEC_WAVEFRONT."""
    eng = PlanEngine(_core.LOUP_EXEC_TILED, receivers=3000)
    res = capacity.evaluate(eng, ATOMS, CapacityConfig(mode="wavefront"))
    assert eng.calls[0] == ("set_execution", _core.LOUP_EXEC_WAVEFRONT, 0, 0.9)
    assert res.mode == "wavefront" and res.receivers == 3000 and eng.calls[-1] == ("evaluate_tiled", 3000, 0.5)


@pytest.mark.parametrize("config,words", [(CapacityConfig(state="host"), "S5-T07")])
def test_what_is_not_built_is_refused_before_the_engine_is_asked(config, words):
    eng = PlanEngine(_core.LOUP_EXEC_WHOLE)
    with pytest.raises(PlanRefused, match=words):
        capacity.evaluate(eng, ATOMS, config)
    assert eng.calls == []


class SpringPlanEngine(PlanEngine):
    """A plan engine whose forces are springs to the starting sites (K eV/A^2): velocity Verlet must conserve."""

    K = 2.0

    def set_sites(self, atoms):
        self.sites = np.array(atoms.positions)

    def _spring(self, positions):
        d = np.asarray(positions) - self.sites
        return 0.5 * self.K * float(np.sum(d * d)), -self.K * d

    def evaluate(self, positions, cell, compute_stress=True):
        e, f = self._spring(positions)
        return e, f, np.zeros((3, 3))

    def evaluate_tiled(self, numbers, positions, cell, receivers, skin=0.5):
        self.tiled_calls = getattr(self, "tiled_calls", 0) + 1
        e, f = self._spring(positions)
        return e, f, np.zeros((3, 3)), 2

    def last_execution(self):
        return _core.Execution(_core.LOUP_EXEC_TILED, self.receivers, 2, 900, 700, True,
                               getattr(self, "tiled_calls", 0))


@pytest.mark.parametrize("mode", [_core.LOUP_EXEC_WHOLE, _core.LOUP_EXEC_TILED])
def test_run_nve_conserves_energy_on_springs(mode):
    at = ATOMS.copy()
    at.set_velocities(np.random.default_rng(2).normal(scale=0.01, size=(len(at), 3)))
    eng = SpringPlanEngine(mode, receivers=16)
    eng.set_sites(at)
    res = capacity.run_nve(eng, at, n_steps=400, dt_fs=1.0, every=20)
    assert res.mode == ("whole" if mode == _core.LOUP_EXEC_WHOLE else "tiled")
    assert len(res.times_ps) == 21 and res.times_ps[-1] == pytest.approx(0.4)
    assert np.ptp(res.total) <= 1e-3 * res.kinetic[0]
    assert abs(res.drift_mev_per_atom_ps(len(at))) < 1e-2
    if mode == _core.LOUP_EXEC_TILED:
        assert eng.tiled_calls == 401                  # the plan's first call and one per step
        assert res.receivers == 16 and res.tiles == 2


def test_run_nve_refuses_a_negative_step_count():
    with pytest.raises(PlanRefused):
        capacity.run_nve(PlanEngine(_core.LOUP_EXEC_WHOLE), ATOMS, n_steps=-1)
