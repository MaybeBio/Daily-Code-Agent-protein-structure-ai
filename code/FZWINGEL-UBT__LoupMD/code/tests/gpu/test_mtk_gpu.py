"""Martyna-Tobias-Klein NPT on the GPU (plan task S4-T09): ASE 3.27's ``IsotropicMTKNPT`` (the cell keeps its
shape) and ``MTKNPT`` (the full cell), Nose-Hoover chains on the atoms and on the cell, in the variable-cell
step. The scheme is deterministic, so ASE's classes driven by ``lm.calc`` take the same steps."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, LoupEngine, _core

GPA = 160.21766208          # eV/A^3 in GPa


def _strained(rep=3, strain=0.99, seed=5, temp=300.0):
    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    at.set_cell(at.cell.array * strain, scale_atoms=True)
    at.set_velocities(maxwell_velocities(at, temp, seed + 1))
    return at


def _start(eng, at):
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, at.get_velocities(), at.cell.array)


def _mtk(temp_k=300.0, tdamp_fs=100.0, pdamp_fs=1000.0, pressure_gpa=0.0, full=False, **fields):
    return _core.integrator(_core.LOUP_MTK_NPT, 1.0, temp_k=temp_k, tau_t_fs=tdamp_fs, tau_p_fs=pdamp_fs,
                            pressure_gpa=pressure_gpa,
                            cell_mode=_core.LOUP_CELL_FULL if full else _core.LOUP_CELL_HYDROSTATIC, **fields)


def _conserved(rows):
    return rows["conserved"]


@pytest.mark.parametrize("full,chains", [(False, (3, 3, 1, 1)), (True, (3, 3, 1, 1)), (False, (2, 4, 2, 3))],
                         ids=["isotropic", "full-cell", "isotropic-2x2-4x3"])
def test_the_engine_takes_ase_s_steps(sto_bundle, model_path, full, chains):
    """The plan's criterion: the volume agrees with ASE's class to 1e-5 relative after 200 steps."""
    from ase.md.nose_hoover_chain import MTKNPT, IsotropicMTKNPT

    tchain, pchain, tloop, ploop = chains
    at, steps = _strained(), 200
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    eng.run(steps, _mtk(full=full, chain_length=tchain, chain_loops=tloop, p_chain_length=pchain, p_chain_loops=ploop,
                        thermo_every=steps))
    row = eng.read_thermo()[-1]
    cell = eng.get_cell()
    positions, velocities, _, _ = eng.get_state()

    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    dyn = (MTKNPT if full else IsotropicMTKNPT)(
        ref, 1.0 * units.fs, temperature_K=300.0, pressure_au=0.0, tdamp=100.0 * units.fs, pdamp=1000.0 * units.fs,
        tchain=tchain, pchain=pchain, tloop=tloop, ploop=ploop)
    dyn.run(steps)
    volume, volume_ase = abs(np.linalg.det(cell)), ref.get_volume()
    worst = np.abs(positions - ref.positions).max()
    conserved = dyn.get_conserved_energy()
    extra = float(row["conserved"]) - float(row["e_pot"]) - float(row["e_kin"])
    extra_ase = conserved - ref.get_potential_energy() - ref.get_kinetic_energy()
    print(f"MTK NPT {'full cell' if full else 'isotropic'}, chains {tchain}x{tloop} and {pchain}x{ploop}, {steps} "
          f"steps: volume {at.get_volume():.2f} -> {volume:.3f} A^3, ASE {volume_ase:.3f} (relative "
          f"{abs(volume / volume_ase - 1):.1e}); cell within {np.abs(cell - ref.cell.array).max():.1e} A, positions "
          f"within {worst:.1e} A, velocities within {np.abs(velocities - ref.get_velocities()).max():.1e}; the "
          f"conserved quantity's part beside E_pot + E_kin {extra:.6f} eV against {extra_ase:.6f} eV")
    assert abs(volume / volume_ase - 1) < 1e-5 and worst < 1e-4
    assert np.abs(cell - ref.cell.array).max() < 1e-6
    assert extra == pytest.approx(extra_ase, abs=5e-5) and abs(extra) > 1e-3
    # The totals carry each engine's float32 potential energy (two engines differ by up to 1e-6 eV/atom, PLAN D16).
    assert float(row["conserved"]) == pytest.approx(conserved, abs=3e-6 * len(at))
    assert volume > at.get_volume() * 1.0005                       # the compressed cell grows
    if not full:
        assert np.allclose(cell, cell[0, 0] * np.eye(3), rtol=0, atol=1e-9 * cell[0, 0])


@pytest.mark.parametrize("full", [False, True], ids=["isotropic", "full-cell"])
@pytest.mark.full
def test_the_conserved_quantity_holds(sto_bundle, full):
    """The plan's criterion: the conserved quantity drifts by less than 0.05 meV/atom/ps. 20,000 steps of 1 fs."""
    at = _strained(strain=1.0)
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    rows = []
    for _ in range(10):
        eng.run(2_000, _mtk(full=full, pressure_gpa=1.0, thermo_every=100))
        rows.append(eng.read_thermo())
    rows = np.concatenate(rows)
    time_ps = rows["step"] * 1e-3
    per_atom = 1e3 * _conserved(rows) / len(at)
    drift = np.polyfit(time_ps, per_atom, 1)[0]
    moved = 1e3 * (rows["e_pot"] + rows["e_kin"]) / len(at)
    late = rows[len(rows) // 2:]
    print(f"MTK NPT {'full cell' if full else 'isotropic'}, 20,000 steps of 1 fs at 300 K and 1 GPa: conserved "
          f"quantity drift {drift:+.4f} meV/atom/ps, range {np.ptp(per_atom):.3f} meV/atom while potential plus "
          f"kinetic moved {np.ptp(moved):.1f} meV/atom; second half: temperature {late['temp_k'].mean():.1f} K, "
          f"pressure {late['pressure_gpa'].mean():.3f} GPa, volume {late['volume_a3'].mean() / len(at):.4f} A^3/atom")
    assert abs(drift) < 0.05
    assert abs(late["temp_k"].mean() - 300.0) < 15.0 and abs(late["pressure_gpa"].mean() - 1.0) < 0.5


def test_calls_continue_and_the_state_block_carries_the_chains(sto_bundle):
    at = _strained()
    whole = LoupEngine(sto_bundle)
    _start(whole, at)
    whole.run(200, _mtk(thermo_every=200))
    reference = whole.read_thermo()[-1]

    parts = LoupEngine(sto_bundle)
    _start(parts, at)
    parts.run(100, _mtk())
    blob = parts.export_state()
    parts.run(100, _mtk(thermo_every=100))
    resumed = LoupEngine(sto_bundle)
    resumed.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    resumed.import_state(blob)
    resumed.run(100, _mtk(thermo_every=100))

    volume = abs(np.linalg.det(whole.get_cell()))
    relative = [abs(abs(np.linalg.det(e.get_cell())) / volume - 1.0) for e in (parts, resumed)]

    def beside(row):
        return float(row["conserved"]) - float(row["e_pot"]) - float(row["e_kin"])

    print(f"MTK NPT, 200 steps in one call against two calls and against a state block imported into another "
          f"engine after 100: volume relative {relative[0]:.1e} and {relative[1]:.1e}")
    assert max(relative) < 1e-7
    assert beside(parts.read_thermo()[-1]) == pytest.approx(beside(reference), abs=1e-5)
    assert beside(resumed.read_thermo()[-1]) == pytest.approx(beside(reference), abs=1e-5)


def test_refusals(sto_bundle):
    eng = LoupEngine(sto_bundle)
    at = _strained()
    _start(eng, at)
    for fields, reason in (
            (dict(tdamp_fs=0.0), "tau_t_fs must be finite and positive, got 0 fs"),
            (dict(pdamp_fs=0.0), "tau_p_fs must be finite and positive, got 0 fs"),
            (dict(pressure_gpa=float("nan")), "pressure_gpa must be finite"),
            (dict(chain_length=9), "chain_length must be from 1 to 8 thermostats for LOUP_MTK_NPT, got 9"),
            (dict(p_chain_length=9), "p_chain_length must be from 1 to 8"),
            (dict(p_chain_loops=-1), "p_chain_loops must be from 0 to 100"),
            (dict(temp_k=0.0), "temp_k must be positive for LOUP_MTK_NPT")):
        with pytest.raises(BackendError, match="loup_run: " + reason):
            eng.run(10, _mtk(**fields))
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_fixed_atoms(fixed)
    with pytest.raises(BackendError, match="loup_run: a barostat with fixed atoms"):
        eng.run(10, _mtk())
    eng.set_fixed_atoms(None)
    assert eng.run(10, _mtk()).final_temperature_k > 100.0           # chain lengths 0: ASE's defaults, 3 and 3


def test_the_record_and_the_drop_in_run_the_engine_s_steps(sto_bundle, model_path, tmp_path):
    """``lm.integrators.MTK`` through ``lm.Simulation`` and ``loupmd.ase.md.IsotropicMTKNPT``: the same 200 steps
    as one engine call, with volume and pressure in the rows."""
    from loupmd import integrators, output
    from loupmd.ase import md as ase_md

    at = _strained()
    ff = loupmd.load(model_path, trusted=True)
    record = integrators.MTK(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=0.0, tdamp_fs=100.0, pdamp_fs=1000.0,
                             fixcm=False)
    sim = loupmd.Simulation(at, ff, integrator=record, seed=1,
                            output=loupmd.Output(str(tmp_path / "mtk"), thermo_every=50, trajectory_every=None,
                                                 restart_every=None))
    sim.run(steps=200)
    volume = sim.atoms.get_volume()
    sim.close()
    header, rows = output.read_thermo(tmp_path / "mtk")

    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    eng.run(200, _mtk())
    direct = abs(np.linalg.det(eng.get_cell()))
    atoms = at.copy()
    ase_md.IsotropicMTKNPT(atoms, 1.0 * units.fs, 300.0, 0.0, 100.0 * units.fs, 1000.0 * units.fs, model=ff).run(200)
    print(f"lm.integrators.MTK through lm.Simulation, 200 steps: volume {volume:.3f} A^3 (one engine call: relative "
          f"{abs(volume / direct - 1):.1e}; the IsotropicMTKNPT drop-in: {abs(atoms.get_volume() / direct - 1):.1e}); "
          f"pressure {float(rows[0][9]):.2f} GPa at step 0, {float(rows[-1][9]):.2f} GPa at step 200")
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS) and [int(r[0]) for r in rows] == [0, 50, 100, 150, 200]
    assert abs(volume / direct - 1) < 1e-6 and abs(atoms.get_volume() / direct - 1) < 1e-6
    assert float(rows[-1][8]) * len(at) == pytest.approx(volume, rel=1e-12)
