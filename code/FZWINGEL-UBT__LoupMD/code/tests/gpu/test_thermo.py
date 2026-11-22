"""The device thermo buffer (plan task S1-T05): with thermo_every = k every k-th step appends a row of energies on
the device, inside the captured step, and loup_read_thermo drains the rows. Every test creates an engine."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

from loupmd import BackendError
from loupmd import _core


def _start(eng, seed=4):
    at = srtio3(3)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 300.0, seed + 1), at.cell.array)
    return at


def _nve(every):
    return _core.integrator(_core.LOUP_NVE, 1.0, thermo_every=every)


def test_rows_equal_the_engines_own_energies_at_the_same_steps(sto_engine):
    eng = sto_engine
    at = _start(eng)
    seen = []
    for _ in range(10):  # each call ends on a row step, where LoupMDStats reports the same state
        st = eng.run(20, _nve(20))
        seen.append((st.final_potential_energy_ev, st.final_kinetic_energy_ev, st.final_temperature_k))
    assert eng.thermo_pending() == 10
    rows = eng.read_thermo()
    assert rows["step"].tolist() == list(range(20, 201, 20))
    e_pot, e_kin, temp = (np.array(x) for x in zip(*seen))
    assert np.array_equal(rows["e_pot"], e_pot)                  # the same device value
    assert np.allclose(rows["e_kin"], e_kin, rtol=1e-12, atol=0.0)  # the same velocities, summed in another order
    assert np.allclose(rows["temp_k"], temp, rtol=1e-12, atol=0.0)
    assert np.allclose(rows["conserved"], rows["e_pot"] + rows["e_kin"], rtol=1e-15)
    assert np.ptp(rows["conserved"]) < 2e-4 * len(at)            # NVE: the total energy stays put
    assert not rows["pressure_gpa"].any() and not rows["volume_a3"].any()
    assert eng.thermo_pending() == 0 and len(eng.read_thermo()) == 0   # drained


def test_one_long_call_writes_the_same_rows_without_stopping(sto_engine):
    eng = sto_engine
    _start(eng)
    st = eng.run(205, _nve(20))
    rows = eng.read_thermo()
    assert rows["step"].tolist() == list(range(20, 201, 20))  # step 205 is not a row step
    assert st.pipelined_steps > 100                           # the rows did not cost the pipelined loop
    assert np.isfinite(rows["e_pot"]).all() and (rows["e_kin"] > 0).all()
    later = eng.run(15, _nve(20))                             # the step count carries over: 220 is the next row
    assert eng.read_thermo()["step"].tolist() == [220]
    assert later.final_potential_energy_ev == pytest.approx(later.final_potential_energy_ev)


def test_cadence_changes_without_a_new_capture_and_rows_stop_with_zero(sto_engine, capfd, monkeypatch):
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    eng = sto_engine
    _start(eng)
    for _ in range(6):
        eng.run(20, _nve(20))
    eng.read_thermo()
    capfd.readouterr()
    eng.run(20, _nve(5))    # steps 121 .. 140: rows at 125, 130, 135, 140
    eng.run(20, _nve(10))   # rows at 150, 160
    assert capfd.readouterr().err.count("loupmd: MD graph capture") <= 3   # the cadence is not baked into the graph
    assert eng.read_thermo()["step"].tolist() == [125, 130, 135, 140, 150, 160]
    eng.run(20, _nve(0))
    eng.run_nve(20, 1.0)
    assert eng.thermo_pending() == 0
    eng.run(20, _nve(20))   # the steps without rows were counted: 220 is a row step
    assert eng.read_thermo()["step"].tolist() == [220]


def test_partial_reads_keep_the_rest_in_order(sto_engine):
    eng = sto_engine
    _start(eng)
    eng.run(70, _nve(10))
    assert eng.read_thermo(3)["step"].tolist() == [10, 20, 30]
    assert eng.thermo_pending() == 4
    eng.run(20, _nve(10))
    assert eng.read_thermo(100)["step"].tolist() == [40, 50, 60, 70, 80, 90]


def test_a_run_that_would_overflow_the_buffer_is_refused_before_its_first_step(sto_engine):
    eng = sto_engine
    at = _start(eng)
    eng.run(4000, _nve(1))
    pos, _, _, _ = eng.get_state()
    with pytest.raises(BackendError, match="loup_run: this call would write 200 thermo rows and the buffer has room "
                                           "for 96 of 4096"):
        eng.run(200, _nve(1))
    assert np.array_equal(eng.get_state()[0], pos)     # nothing ran
    assert len(eng.read_thermo()) == 4000
    eng.run(200, _nve(1))
    assert eng.read_thermo()["step"].tolist() == list(range(4001, 4201))
    assert len(at) == 135


def test_langevin_rows_and_new_positions_reset_the_step_count(sto_engine):
    eng = sto_engine
    at = _start(eng)
    it = _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, friction_per_fs=0.01, seed=3, thermo_every=25)
    eng.run(100, it)
    rows = eng.read_thermo()
    assert rows["step"].tolist() == [25, 50, 75, 100] and (rows["temp_k"] > 50.0).all()
    eng.run(30, it)                                           # one unread row (step 125)
    pos, vel, _, _ = eng.get_state()
    eng.set_state(pos, vel, at.cell.array)                    # discards it and restarts the count
    assert eng.thermo_pending() == 0
    eng.run(50, it)
    assert eng.read_thermo()["step"].tolist() == [25, 50]


def test_read_refusals(sto_engine):
    eng = sto_engine
    _start(eng)
    assert eng._lib.loup_read_thermo(eng._h, None, 0, None) == -1
    assert eng.last_error() == "loup_read_thermo: n_rows is NULL"
    import ctypes

    n = ctypes.c_int()
    assert eng._lib.loup_read_thermo(eng._h, None, 5, ctypes.byref(n)) == -1
    assert eng.last_error() == "loup_read_thermo: rows is NULL or max_rows is negative (max_rows = 5)"
