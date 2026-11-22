"""Langevin BAOAB NPT on the GPU (plan task S4-T08): ASE 3.27's ``LangevinBAOAB`` with a barostat (Leimkuhler
and Matthews' BAOAB for the atoms, Quigley and Probert's Langevin-Hoover barostat for the cell) in the
variable-cell step. At a target of 0 K nothing is drawn, so the step is compared with ASE's own class exactly;
with a temperature the engine draws its own noise, and temperature and pressure are checked against their
targets."""
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


def _baoab(temp_k=300.0, t_tau_fs=50.0, p_tau_fs=500.0, pressure_gpa=0.0, full=False, **fields):
    return _core.integrator(_core.LOUP_BAOAB_NPT, 1.0, temp_k=temp_k, friction_per_fs=1.0 / t_tau_fs,
                            tau_p_fs=p_tau_fs, pressure_gpa=pressure_gpa,
                            cell_mode=_core.LOUP_CELL_FULL if full else _core.LOUP_CELL_HYDROSTATIC, **fields)


def _ase_class(identity_drag):
    from ase.md.langevinbaoab import LangevinBAOAB

    if not identity_drag:
        return LangevinBAOAB

    class WithIdentity(LangevinBAOAB):
        """Quigley and Probert's drag of the cell on the velocities, (p + Tr(p) / Ndof 1) / W. ASE 3.27 adds the
        trace term to all nine elements (no identity); the engine follows the paper, as FastMACE's default."""

        def _barostat_BAOAB_OU_gamma_mod(self):
            if self.hydrostatic:
                return super()._barostat_BAOAB_OU_gamma_mod()
            return (self.p_eps + np.trace(self.p_eps) / self.Ndof * np.identity(3)) / self.barostat_mass

    return WithIdentity


@pytest.mark.parametrize("full", [False, True], ids=["hydrostatic", "full-cell"])
def test_a_run_without_noise_is_ase_s(sto_bundle, model_path, full):
    """The plan's criterion for the step itself: at a target of 0 K the thermostat only damps, so ASE's class
    driven by ``lm.calc`` takes the same steps. 100 steps from a compressed cell with 300 K of velocities."""
    import warnings

    at, steps = _strained(), 100
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    eng.run(steps, _baoab(temp_k=0.0, full=full, thermo_every=50))
    rows = eng.read_thermo()
    cell = eng.get_cell()
    positions, velocities, _, _ = eng.get_state()

    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dyn = _ase_class(full)(ref, 1.0 * units.fs, temperature_K=0.0, externalstress=0.0, hydrostatic=not full,
                               T_tau=50.0 * units.fs, P_tau=500.0 * units.fs, rng=np.random.default_rng(1))
        dyn.run(steps)
    rel = np.abs(cell - ref.cell.array) / np.abs(ref.cell.array).max()      # of the cell's length
    worst = np.abs(positions - ref.positions).max()
    print(f"BAOAB NPT without noise, {'full cell' if full else 'hydrostatic'}, {steps} steps: volume "
          f"{at.get_volume():.2f} -> {abs(np.linalg.det(cell)):.3f} A^3; against ASE's LangevinBAOAB: cell within "
          f"{rel.max():.1e} of its length, positions within {worst:.1e} A, velocities within "
          f"{np.abs(velocities - ref.get_velocities()).max():.1e}; temperature {rows['temp_k'][0]:.0f} K at step 50, "
          f"{rows['temp_k'][-1]:.0f} K at step 100")
    assert rel.max() < 1e-7 and worst < 1e-5
    assert abs(np.linalg.det(cell)) > at.get_volume() * 1.0005          # the compressed cell grows
    assert rows["temp_k"][-1] < 150.0                                    # 0 K target: the velocities are damped
    assert np.allclose(rows["volume_a3"][-1], abs(np.linalg.det(cell)), rtol=1e-12)
    if not full:
        assert np.allclose(cell, cell[0, 0] * np.eye(3), rtol=0, atol=1e-9 * cell[0, 0])


@pytest.mark.full
def test_temperature_and_pressure_are_the_targets(sto_bundle):
    """The plan's criterion for the ensemble: over 20,000 steps on SrTiO3 5x5x5 the mean pressure is within its
    standard error of the target (three of them here), and so is the mean temperature."""
    at = _strained(rep=5, strain=1.0)
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    target_gpa = 1.0
    it = _baoab(temp_k=300.0, t_tau_fs=50.0, p_tau_fs=500.0, pressure_gpa=target_gpa, thermo_every=10, seed=11)
    eng.run(5_000, it)                                               # to the target volume and temperature
    eng.read_thermo()
    rows = []
    for _ in range(4):
        eng.run(5_000, it)
        rows.append(eng.read_thermo())
    rows = np.concatenate(rows)

    def mean_and_error(values, block=100):                           # blocks of 1,000 steps
        means = values[:len(values) // block * block].reshape(-1, block).mean(axis=1)
        return means.mean(), means.std(ddof=1) / np.sqrt(len(means))

    pressure, pressure_error = mean_and_error(rows["pressure_gpa"])
    temperature, temperature_error = mean_and_error(rows["temp_k"])
    volume = rows["volume_a3"]
    print(f"BAOAB NPT, SrTiO3 5x5x5, 300 K and {target_gpa:g} GPa, 20,000 steps after 5,000: pressure "
          f"{pressure:.3f} +- {pressure_error:.3f} GPa, temperature {temperature:.1f} +- {temperature_error:.1f} K, "
          f"volume {volume.mean() / len(at):.4f} A^3/atom (relative scatter {volume.std() / volume.mean():.1e})")
    assert abs(pressure - target_gpa) < 3.0 * pressure_error + 0.02
    assert abs(temperature - 300.0) < 3.0 * temperature_error + 1.0
    assert 1e-5 < volume.std() / volume.mean() < 2e-2                 # the cell moves, and stays


def test_calls_continue_and_the_state_block_carries_the_barostat(sto_bundle):
    at = _strained()
    whole = LoupEngine(sto_bundle)
    _start(whole, at)
    whole.run(200, _baoab(temp_k=0.0))

    parts = LoupEngine(sto_bundle)
    _start(parts, at)
    parts.run(100, _baoab(temp_k=0.0))
    blob = parts.export_state()
    parts.run(100, _baoab(temp_k=0.0))

    resumed = LoupEngine(sto_bundle)
    resumed.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    resumed.import_state(blob)
    resumed.run(100, _baoab(temp_k=0.0))

    reference = abs(np.linalg.det(whole.get_cell()))
    relative = [abs(abs(np.linalg.det(e.get_cell())) / reference - 1.0) for e in (parts, resumed)]
    print(f"BAOAB NPT, 200 steps in one call against two calls and against a state block imported into another "
          f"engine after 100: volume relative {relative[0]:.1e} and {relative[1]:.1e}")
    assert max(relative) < 1e-7
    assert np.abs(resumed.get_state()[0] - whole.get_state()[0]).max() < 1e-5


def test_refusals(sto_bundle):
    eng = LoupEngine(sto_bundle)
    at = _strained()
    _start(eng, at)
    for fields, reason in (
            (dict(t_tau_fs=float("inf")), "friction_per_fs must be finite and positive for LOUP_BAOAB_NPT"),
            (dict(p_tau_fs=-1.0), "tau_p_fs must be finite and not negative"),
            (dict(pressure_gpa=float("nan")), "pressure_gpa must be finite"),
            (dict(temp_k=-1.0), "temp_k must be finite and not negative"),
            (dict(fix_com=1), "fix_com is not part of LOUP_BAOAB_NPT")):
        with pytest.raises(BackendError, match="loup_run: " + reason):
            eng.run(10, _baoab(**fields))
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_fixed_atoms(fixed)
    with pytest.raises(BackendError, match="loup_run: a barostat with fixed atoms"):
        eng.run(10, _baoab())
    eng.set_fixed_atoms(None)
    assert eng.run(10, _baoab(p_tau_fs=0.0)).final_temperature_k > 100.0      # 0: ASE's default, 20 T_tau


def test_lm_md_runs_npt_and_resumes(model_path, tmp_path):
    """``lm.md(ensemble="NPT")`` is Langevin BAOAB: rows with volume and pressure, a resumed run that goes on with
    the barostat's momentum from the restart, and the ASE drop-in."""
    from loupmd import output
    from loupmd.ase import md as ase_md

    at = _strained()
    ff = loupmd.load(model_path, trusted=True)
    result = loupmd.md(at, model=ff, ensemble="NPT", temperature_K=300.0, pressure_GPa=1.0, timestep_fs=1.0,
                       steps=400, seed=4, output=loupmd.Output(str(tmp_path / "npt"), thermo_every=20,
                                                               trajectory_every=200, restart_every=200))
    sim = result.simulation
    volume_400 = sim.atoms.get_volume()
    sim.close()
    again = loupmd.Simulation.resume(tmp_path / "npt", force_field=ff)
    again.run(steps=200)
    final = again.atoms.get_volume()
    again.close()
    header, rows = output.read_thermo(tmp_path / "npt")
    volumes = np.array([float(row[8]) for row in rows]) * len(at)
    pressures = np.array([float(row[9]) for row in rows])
    temperatures = np.array([float(row[4]) for row in rows])

    atoms = at.copy()
    dyn = ase_md.LangevinBAOAB(atoms, 1.0 * units.fs, temperature_K=300.0, externalstress=-1.0 / GPA,
                               hydrostatic=True, T_tau=50.0 * units.fs, model=ff, seed=4)
    dyn.run(200)
    print(f"lm.md(ensemble='NPT') at 300 K and 1 GPa from the compressed SrTiO3 3x3x3: volume {volumes[0]:.2f} -> "
          f"{volume_400:.2f} A^3 after 400 steps, {final:.2f} after 200 more from the restart; pressure "
          f"{pressures[0]:.2f} GPa at step 0, mean of steps 300 to 600 {pressures[15:].mean():.2f} GPa; temperature "
          f"mean of steps 300 to 600 {temperatures[15:].mean():.0f} K; the drop-in after 200 steps: "
          f"{atoms.get_volume():.2f} A^3")
    assert "NPT, Langevin BAOAB with a Langevin-Hoover barostat (experimental)" in result.summary
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS)
    assert [int(row[0]) for row in rows] == list(range(0, 601, 20))
    assert volumes[20] == pytest.approx(volume_400, rel=1e-12) and volumes[-1] == pytest.approx(final, rel=1e-12)
    assert volume_400 > at.get_volume() * 1.02 and atoms.get_volume() > at.get_volume() * 1.01
    assert pressures[0] > 5.0 and abs(pressures[15:].mean() - 1.0) < 1.5
    assert 240.0 < temperatures[15:].mean() < 360.0
