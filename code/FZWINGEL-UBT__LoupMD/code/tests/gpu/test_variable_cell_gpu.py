"""The variable cell inside the captured step (plan task S4-T06): the cell and the edges' integer image shifts live
on the device, the Cartesian shifts are formed in every step, every step carries stress, and the list check
measures what an atom moved beside the cell's own deformation. No integrator changes the cell yet (S4-T07 to
S4-T09), so the tests drive it with ``LOUP_VARIABLE_CELL=1`` (a fixed-cell integrator through the variable-cell
step) and ``LOUP_DEBUG_CELL_RATE`` (the cell and the positions scaled by a constant factor per step)."""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

from loupmd import BackendError, LoupEngine, _core

GPA = 160.21766208          # eV/A^3 in GPa


def _start(eng, rep=3, temp=300.0, seed=5, skin=0.5):
    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=skin)
    eng.set_state(at.positions, maxwell_velocities(at, temp, seed + 1), at.cell.array)
    return at


def _nve(**fields):
    return _core.integrator(_core.LOUP_NVE, 1.0, **fields)


def _pressure_gpa(stress, e_kin, volume):
    """ASE's pressure with the ideal-gas part: minus a third of the trace of the stress, plus 2 E_kin / (3 V)."""
    return (-np.trace(stress) / 3.0 + 2.0 * e_kin / (3.0 * volume)) * GPA


def test_a_fixed_cell_run_through_the_variable_cell_step(sto_bundle, monkeypatch):
    """The plan's criterion: forces within 1e-6 eV/A of the fixed-cell step, or within what two runs of the
    fixed-cell step differ by (force sums use atomics, and 40 steps let that grow). After one step the two
    steps have computed forces for the same positions. The variable-cell rows carry volume and pressure."""
    def run(variable, steps=40):
        if variable:
            monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
        else:
            monkeypatch.delenv("LOUP_VARIABLE_CELL", raising=False)
        eng = LoupEngine(sto_bundle)
        at = _start(eng)
        stats = eng.run(steps, _nve(thermo_every=10))
        positions, _, forces, _ = eng.get_state()
        return eng, at, positions, forces, eng.read_thermo(), stats

    one = [run(variable, steps=1)[3] for variable in (False, False, True)]
    first = (np.abs(one[2] - one[0]).max(), np.abs(one[1] - one[0]).max())
    _, _, pos_a, f_a, rows_a, _ = run(False)
    _, _, pos_b, f_b, _, _ = run(False)
    eng, at, pos_v, f_v, rows_v, stats_v = run(True)
    spread = (np.abs(pos_b - pos_a).max(), np.abs(f_b - f_a).max())
    diff = (np.abs(pos_v - pos_a).max(), np.abs(f_v - f_a).max())
    volume = at.get_volume()
    monkeypatch.delenv("LOUP_VARIABLE_CELL")
    _, _, stress = eng.evaluate(pos_v, at.cell.array, compute_stress=True)
    expected = _pressure_gpa(stress, float(rows_v["e_kin"][-1]), volume)
    print(f"variable-cell step with a constant cell: forces after one step within {first[0]:.1e} eV/A of the "
          f"fixed-cell step (two fixed-cell runs: {first[1]:.1e}); after 40 NVE steps positions within {diff[0]:.1e} A "
          f"and forces within {diff[1]:.1e} eV/A (two fixed-cell runs: {spread[0]:.1e}, {spread[1]:.1e}); "
          f"pressure {float(rows_v['pressure_gpa'][-1]):.4f} GPa against {expected:.4f} GPa from the stress of an "
          f"evaluation; {stats_v.pipelined_steps} pipelined steps")
    assert first[0] <= max(1e-6, 5.0 * first[1])
    assert diff[1] <= max(1e-6, 5.0 * spread[1]) and diff[0] <= max(1e-8, 5.0 * spread[0])
    assert np.allclose(rows_v["volume_a3"], volume, rtol=1e-12) and not rows_a["volume_a3"].any()
    assert not rows_a["pressure_gpa"].any()                          # a fixed-cell step carries no stress
    assert float(rows_v["pressure_gpa"][-1]) == pytest.approx(expected, abs=2e-4)
    assert np.allclose(rows_v["e_pot"], rows_a["e_pot"], atol=1e-5 * len(at), rtol=0)
    assert np.allclose(eng.get_cell(), at.cell.array, rtol=0, atol=1e-12)


@pytest.mark.parametrize("rate", [-2e-4, 2e-4], ids=["compression", "expansion"])
def test_a_deforming_cell_keeps_forces_and_list_right(sto_bundle, monkeypatch, rate):
    """The cell and the positions are scaled by 1 + rate in every step (3% in 150 steps). Afterwards the forces
    on the device are those a new engine computes for the same positions and cell: the Cartesian shifts
    followed the cell, and the list was rebuilt where the deformation had used up the skin."""
    monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
    monkeypatch.setenv("LOUP_DEBUG_CELL_RATE", repr(rate))
    eng = LoupEngine(sto_bundle)
    at = _start(eng)
    steps = 150
    stats = eng.run(steps, _nve(thermo_every=50))
    rows = eng.read_thermo()
    positions, _, forces, energy = eng.get_state()
    cell = eng.get_cell()
    factor = (1.0 + rate) ** steps
    monkeypatch.delenv("LOUP_VARIABLE_CELL")
    monkeypatch.delenv("LOUP_DEBUG_CELL_RATE")
    fresh = LoupEngine(sto_bundle)
    fresh.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    e_ref, f_ref, s_ref = fresh.evaluate(positions, cell, compute_stress=True)
    worst = np.abs(forces - f_ref).max()
    volume = abs(np.linalg.det(cell))
    expected = _pressure_gpa(s_ref, float(rows["e_kin"][-1]), volume)
    print(f"cell scaled by {factor:.4f} in {steps} steps: forces within {worst:.1e} eV/A and energy within "
          f"{abs(energy - e_ref) / len(at):.1e} eV/atom of a new engine at the final cell; {stats.rebuilds} rebuilds, "
          f"{stats.dangerous_builds} on an incomplete list; pressure {float(rows['pressure_gpa'][-1]):.3f} GPa "
          f"against {expected:.3f} GPa")
    assert np.allclose(cell, at.cell.array * factor, rtol=1e-12, atol=0)
    assert np.allclose(rows["volume_a3"], at.get_volume() * (1.0 + rate) ** (3 * np.array([50, 100, 150])), rtol=1e-10)
    assert worst < 5e-6 and abs(energy - e_ref) / len(at) < 1e-6
    assert float(rows["pressure_gpa"][-1]) == pytest.approx(expected, abs=1e-3)
    assert stats.dangerous_builds == 0 and stats.rebuilds >= 1
    # compression raises the pressure, expansion lowers it
    assert (rows["pressure_gpa"][-1] - rows["pressure_gpa"][0]) * rate < 0


def test_the_cell_limits_stop_the_run(sto_bundle, monkeypatch):
    """Outside [V0 / 20, 20 V0] the run stops with the volume in its message (FastMACE's limits)."""
    monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
    monkeypatch.setenv("LOUP_DEBUG_CELL_RATE", "0.02")              # volume x 1.061 per step: beyond 20 V0 in 51 steps
    eng = LoupEngine(sto_bundle)
    _start(eng)
    with pytest.raises(BackendError, match=r"loup_run: the cell diverged: its volume is .* A\^3, outside "
                                           r"\[V0 / 20, 20 V0\] with V0 = "):
        eng.run(200, _nve())


def test_set_cell_and_get_cell(sto_bundle):
    eng = LoupEngine(sto_bundle)
    at = _start(eng)
    start = eng.get_state()[0]
    assert np.array_equal(eng.get_cell(), at.cell.array)

    strained = at.cell.array * np.array([1.02, 1.0, 0.99])[None, :]     # the x and z components of every vector
    eng.set_cell(strained, scale_atoms=True)
    positions = eng.get_state()[0]
    assert np.array_equal(eng.get_cell(), strained)
    assert np.allclose(positions, start * np.array([1.02, 1.0, 0.99])[None, :], rtol=1e-13, atol=1e-13)
    energy = eng.run(1, _nve()).final_potential_energy_ev             # forces at the new cell, one small step
    fresh = LoupEngine(sto_bundle)
    fresh.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    e_ref, _, _ = fresh.evaluate(eng.get_state()[0], strained, compute_stress=False)
    assert energy == pytest.approx(e_ref, abs=1e-6 * len(at))

    before = eng.get_state()[0]
    eng.set_cell(at.cell.array * 1.01, scale_atoms=False)             # the cell alone
    assert np.array_equal(eng.get_state()[0], before) and np.array_equal(eng.get_cell(), at.cell.array * 1.01)

    for cell, reason in ((np.zeros((3, 3)), "singular or zero cell"),
                         (np.full((3, 3), np.nan), "non-finite cell entry")):
        with pytest.raises(BackendError, match="loup_set_cell: .*" + reason):
            eng.set_cell(cell)


def test_refusals(sto_bundle, monkeypatch):
    eng = LoupEngine(sto_bundle)
    at = srtio3(2)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    with pytest.raises(BackendError, match="loup_set_cell: no positions"):
        eng.set_cell(at.cell.array)
    with pytest.raises(BackendError, match="loup_get_cell: no positions"):
        eng.get_cell()


@pytest.mark.full
def test_what_the_variable_cell_step_costs(sto_bundle, monkeypatch):
    """Langevin at 5,000 atoms through the fixed-cell step (pipelined) and through the variable-cell step (stress
    in every step, the Cartesian shifts formed in every step, one host wait per step): a b b a twice."""
    engines = {}
    for name in ("fixed", "variable"):
        if name == "variable":
            monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
        else:
            monkeypatch.delenv("LOUP_VARIABLE_CELL", raising=False)
        eng = LoupEngine(sto_bundle)
        _start(eng, rep=10)
        engines[name] = eng
    langevin = _core.integrator(_core.LOUP_LANGEVIN, 1.0, temp_k=300.0, friction_per_fs=0.01, seed=3)

    def run(name, steps):
        if name == "variable":
            monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
        else:
            monkeypatch.delenv("LOUP_VARIABLE_CELL", raising=False)
        return engines[name].run(steps, langevin)

    for name in engines:
        run(name, 300)
    times = {"fixed": [], "variable": []}
    piped = {}
    for name in ("fixed", "variable", "variable", "fixed") * 2:
        stats = run(name, 400)
        times[name].append(stats.step_ms)
        piped[name] = stats.pipelined_steps
    ratio = float(np.median(times["variable"]) / np.median(times["fixed"]))
    print(f"variable-cell step against the fixed-cell step, Langevin, 5,000 atoms: ms/step "
          f"{np.round(times['variable'], 3)} against {np.round(times['fixed'], 3)}, ratio of the medians {ratio:.4f}; "
          f"pipelined steps of the last runs: {piped['variable']} and {piped['fixed']}")
    assert ratio < 1.15
