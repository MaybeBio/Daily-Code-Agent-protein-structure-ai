"""MD graphs and forces are kept across run calls (plan task S1-T03, review item S4).

A run made of many short calls must cost what one long call costs: no re-capture of the step graphs while dt,
thermostat and seed stay the same, and no force pass at the start of a call whose forces are already on the device.
LOUP_DEBUG_GRAPHS makes the library report both events on stderr.
"""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

from loupmd import LoupEngine, _core

CAPTURE = "loupmd: MD graph capture"
FORCE_PASS = "loupmd: initial force pass"


def _start(eng, rep=3, temp_k=300.0, seed=4):
    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, temp_k, seed + 1), at.cell.array)
    return at


@pytest.fixture
def debug_graphs(monkeypatch, capfd):
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    capfd.readouterr()
    return capfd


def test_short_calls_reuse_the_graphs_and_the_forces(sto_engine, debug_graphs):
    eng = sto_engine
    _start(eng)
    eng.run_nve(10, 1.0)
    first = debug_graphs.readouterr().err
    assert first.count(FORCE_PASS) == 1  # set_state brought new positions
    assert first.count(CAPTURE) >= 2     # the unpipelined pair, and the pipelined graph if the call switched
    for _ in range(30):                  # past the first rebuilds: variant timing and edge bucket have settled
        eng.run_nve(10, 1.0)
    debug_graphs.readouterr()
    for _ in range(20):
        eng.run_nve(10, 1.0)
    later = debug_graphs.readouterr().err
    assert FORCE_PASS not in later
    # One invalidation (an edge bucket outgrown at a rebuild) re-captures up to three graphs; a re-capture per call,
    # as before this task, would be 40 or more.
    assert later.count(CAPTURE) <= 3, later.count(CAPTURE)


def test_a_run_after_evaluate_needs_no_force_pass_and_one_after_new_positions_does(sto_engine, debug_graphs):
    eng = sto_engine
    at = _start(eng)
    eng.run_nve(5, 1.0)
    pos, vel, _, _ = eng.get_state()
    debug_graphs.readouterr()
    eng.evaluate(pos, at.cell.array)
    eng.run_nve(5, 1.0)
    assert FORCE_PASS not in debug_graphs.readouterr().err
    eng.set_state(pos, vel, at.cell.array)
    eng.run_nve(5, 1.0)
    assert debug_graphs.readouterr().err.count(FORCE_PASS) == 1


def test_a_changed_temperature_reuses_the_graphs(sto_bundle, debug_graphs, monkeypatch):
    """The thermostat's target lives on the device (plan task S3-T06), so a schedule's calls capture nothing.

    Two engines run the same eight short calls, one at a constant temperature and one whose temperature changes
    a little with every call (and ramps in the last). A graph is captured the first time its loop variant is
    used, which both runs do at the same steps; before this change the second run captured every graph again at
    every call."""
    # The generic layers' conv variants are timed at an engine's first MD rebuild, and a faster one drops the graphs
    # (ledger S64). On 135 atoms they are near ties, so whether an engine captures once more would be chance.
    monkeypatch.setenv("LOUP_CONV_TUNE", "0")
    def captures(temperatures, rate):
        eng = LoupEngine(sto_bundle)
        _start(eng)
        debug_graphs.readouterr()
        for temp_k in temperatures:
            eng.run_langevin(6, 1.0, temp_k=temp_k, friction_per_fs=0.01, seed=3)
        eng.run(6, _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, temp_rate_k_per_step=rate,
                                    friction_per_fs=0.01, seed=3))
        err = debug_graphs.readouterr().err
        return err.count(CAPTURE), err.count(FORCE_PASS)

    constant = captures([300.0] * 8, 0.0)
    varied = captures([300.0, 300.5, 299.5, 300.2, 299.8, 300.4, 299.6, 300.0], 0.05)
    assert varied == constant and constant[1] == 1, (constant, varied)


@pytest.mark.parametrize("change", ["timestep", "kind", "friction", "seed"])
def test_changed_parameters_are_captured_again(sto_engine, debug_graphs, change):
    eng = sto_engine
    _start(eng)
    base = dict(dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=3)
    eng.run_langevin(6, **base)
    eng.run_langevin(6, **base)
    debug_graphs.readouterr()
    if change == "kind":
        eng.run_nve(6, 1.0)
    else:
        new = dict(base, **{"timestep": {"dt_fs": 0.5}, "friction": {"friction_per_fs": 0.02},
                            "seed": {"seed": 4}}[change])
        eng.run_langevin(6, **new)
    assert debug_graphs.readouterr().err.count(CAPTURE) >= 2


def test_a_changed_thermostat_takes_effect_on_reused_handles(sto_engine):
    eng = sto_engine
    _start(eng, temp_k=100.0)
    cold = eng.run_langevin(150, 1.0, temp_k=100.0, friction_per_fs=0.05, seed=1).final_temperature_k
    hot = eng.run_langevin(300, 1.0, temp_k=900.0, friction_per_fs=0.05, seed=1).final_temperature_k
    assert cold < 250.0 < 500.0 < hot, (cold, hot)


def _trajectory(bundle, chunks, steps_per_chunk):
    eng = LoupEngine(bundle)
    _start(eng)
    for _ in range(chunks):
        st = eng.run_nve(steps_per_chunk, 1.0)
    pos, vel, _, _ = eng.get_state()
    return pos, vel, st.final_potential_energy_ev + st.final_kinetic_energy_ev


def test_chunked_trajectory_matches_one_call(sto_bundle):
    """200 NVE steps in 20 calls against one call, from the same state. Force sums use atomics, so two identical
    runs already differ at rounding level: the chunked run may differ from a single call by no more than a few
    times what two single calls differ by (floor 1e-6 A)."""
    single_a = _trajectory(sto_bundle, 1, 200)
    single_b = _trajectory(sto_bundle, 1, 200)
    chunked = _trajectory(sto_bundle, 20, 10)
    spread = np.abs(single_a[0] - single_b[0]).max()
    diff = np.abs(chunked[0] - single_a[0]).max()
    assert diff <= max(5.0 * spread, 1e-6), (diff, spread)
    assert abs(chunked[2] - single_a[2]) <= max(5.0 * abs(single_a[2] - single_b[2]), 1e-6 * 135), (chunked[2], single_a[2])
