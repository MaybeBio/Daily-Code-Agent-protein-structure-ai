"""The step-displacement maximum decays (plan task S1-T11, review item S2).

Since the merge of round6-hardening the MD loop checks every step's list before its force pass, so the maximum no
longer decides anything in the loop. It still feeds ``LoupEngine.step_displacement`` (the automatic skin of
loupmd.simulation) and the saved state, and it covers the current and the previous window only: one fast step is
forgotten two windows later. Every test creates an engine.
"""
from __future__ import annotations

import numpy as np
from gpu_support import maxwell_velocities, srtio3

KICK = 0.75  # A per ASE time unit: 0.074 A in a 1 fs step


def _kicked_start(eng, temp_k):
    """SrTiO3 4x4x4 at ``temp_k`` with one fast oxygen."""
    at = srtio3(4)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    vel = maxwell_velocities(at, temp_k, 3) if temp_k > 0 else np.zeros((len(at), 3))
    assert at.get_chemical_symbols()[7] == "O"
    vel[7] = (KICK, 0.0, 0.0)
    eng.set_state(at.positions, vel, at.cell.array)
    return at


def test_one_fast_step_is_forgotten(sto_engine):
    eng = sto_engine
    _kicked_start(eng, 300.0)
    eng.run_nve(40, 1.0)
    early = eng.step_displacement()
    assert early > 0.06, early  # the kick's step
    eng.run_nve(1200, 1.0)  # two windows pass: by rebuilds, or by the 512-step limit at the latest
    eng.run_nve(300, 1.0)
    late = eng.step_displacement()
    assert late < 0.5 * early, (early, late)


def test_a_cold_system_without_rebuilds_forgets_a_fast_start_too(sto_engine):
    """With no rebuild to end a window, a window still ends after 512 steps."""
    eng = sto_engine
    _kicked_start(eng, 0.0)
    cold = dict(dt_fs=1.0, temp_k=1.0, friction_per_fs=0.2, seed=1)  # the kick is damped within a few steps
    eng.run_langevin(40, **cold)
    early = eng.step_displacement()
    middle = eng.run_langevin(1100, **cold)
    later = eng.run_langevin(100, **cold)
    assert middle.rebuilds == 0 and later.rebuilds == 0, "the premise: nothing moves far enough to rebuild"
    assert eng.step_displacement() < 0.25 * early, (early, eng.step_displacement())


def test_reheating_raises_the_maximum_again(sto_engine):
    """The decayed maximum follows a system that speeds up again: the current window sees every step."""
    eng = sto_engine
    _kicked_start(eng, 100.0)
    eng.run_langevin(1300, 1.0, temp_k=100.0, friction_per_fs=0.05, seed=2)
    cool = eng.step_displacement()
    hot = eng.run_langevin(150, 1.0, temp_k=1500.0, friction_per_fs=0.05, seed=10)
    assert hot.dangerous_builds == 0
    assert eng.step_displacement() > cool, (cool, eng.step_displacement())
