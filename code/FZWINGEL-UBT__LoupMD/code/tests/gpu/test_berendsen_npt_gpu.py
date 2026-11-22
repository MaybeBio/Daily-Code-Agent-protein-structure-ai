"""Berendsen NPT on the GPU (plan task S4-T07): ASE 3.27's ``NPTBerendsen`` and ``Inhomogeneous_NPTBerendsen``
in the variable-cell step. ASE's classes evaluate the forces twice per step (the cell scaling invalidates the
calculator's cache, so the first kick uses forces at the scaled cell); the engine makes one force call per step,
as FastMACE's port, and kicks with the forces of the previous step. The tests compare with ASE's class
reordered the same way, and record the distance from ASE's own."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, LoupEngine, _core

GPA = 160.21766208          # eV/A^3 in GPa
KAPPA = 1.0 / 170.0         # per GPa: about SrTiO3's compressibility


def _strained(strain=0.99, seed=5, temp=300.0):
    """SrTiO3 3x3x3 with every length scaled: 0.99 puts this model's cell about 2% below its own lattice
    constant, so the pressure starts near +10 GPa and the barostat lets the cell grow."""
    at = srtio3(3)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    at.set_cell(at.cell.array * strain, scale_atoms=True)
    at.set_velocities(maxwell_velocities(at, temp, seed + 1))
    return at


def _start(eng, at):
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, at.get_velocities(), at.cell.array)


def _npt(taup_fs=100.0, taut_fs=50.0, pressure_gpa=0.0, temp_k=300.0, mask=None, **fields):
    if mask is not None:
        fields.update(cell_mode=_core.LOUP_CELL_FULL, cell_mask=tuple(mask))
    return _core.integrator(_core.LOUP_BERENDSEN_NPT, 1.0, temp_k=temp_k, tau_t_fs=taut_fs, pressure_gpa=pressure_gpa,
                            tau_p_fs=taup_fs, compressibility_per_gpa=KAPPA, **fields)


def _ase_classes():
    from ase.md.nptberendsen import Inhomogeneous_NPTBerendsen, NPTBerendsen

    def one_call(base):
        class OneCall(base):
            """ASE's step with the first kick taken from the forces of the last call (the cell before the scaling)."""

            def step(self, forces=None):
                atoms = self.atoms
                forces = atoms.get_forces(md=True)
                self.scale_velocities()
                self.scale_positions_and_cell()
                p = atoms.get_momenta() + 0.5 * self.dt * forces
                atoms.set_positions(atoms.get_positions() + self.dt * p / atoms.get_masses()[:, np.newaxis])
                atoms.set_momenta(p)
                forces = atoms.get_forces(md=True)
                atoms.set_momenta(atoms.get_momenta() + 0.5 * self.dt * forces)
                return forces

        return OneCall

    return NPTBerendsen, Inhomogeneous_NPTBerendsen, one_call


def _ase_run(cls, at, model_path, steps, taup_fs=100.0, taut_fs=50.0, **extra):
    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    dyn = cls(ref, 1.0 * units.fs, temperature_K=300.0, pressure_au=0.0, taut=taut_fs * units.fs,
              taup=taup_fs * units.fs, compressibility_au=KAPPA * GPA, fixcm=False, **extra)
    dyn.run(steps)
    return ref


def test_the_volume_is_ase_s(sto_bundle, model_path):
    """The plan's criterion: the volume agrees with ASE's ``NPTBerendsen`` to 1e-6 relative after 200 steps."""
    npt, _, one_call = _ase_classes()
    at, steps = _strained(), 200
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    eng.run(steps, _npt(thermo_every=50))
    rows = eng.read_thermo()
    cell = eng.get_cell()
    positions = eng.get_state()[0]
    volume = abs(np.linalg.det(cell))

    same_order = _ase_run(one_call(npt), at, model_path, steps)
    ase_own = _ase_run(npt, at, model_path, steps)
    rel = abs(volume / same_order.get_volume() - 1.0)
    rel_own = abs(volume / ase_own.get_volume() - 1.0)
    worst = np.abs(positions - same_order.positions).max()
    print(f"Berendsen NPT, 200 steps from a compressed cell (taup 100 fs): volume {at.get_volume():.2f} -> "
          f"{volume:.3f} A^3; against ASE's class with one force call per step: relative {rel:.1e}, positions within "
          f"{worst:.1e} A; against ASE's own class (two force calls per step): relative {rel_own:.1e}; pressure "
          f"{rows['pressure_gpa'][0]:.2f} GPa at step 50, {rows['pressure_gpa'][-1]:.2f} GPa at step 200")
    assert rel < 1e-6 and worst < 1e-4
    # ASE's own class kicks with forces of the scaled cell (a second force call per step); the distance is of
    # the order dt kappa |P0 - P| / taup per step (PLAN.md D48).
    assert rel_own < 1e-4
    assert volume > at.get_volume() * 1.001                        # the compressed cell has grown
    assert np.allclose(rows["volume_a3"][-1], volume, rtol=1e-12)
    assert np.allclose(cell, cell[0, 0] * np.eye(3), rtol=0, atol=1e-9 * cell[0, 0])    # its shape is kept


def test_the_mask_frees_single_axes(sto_bundle, model_path):
    """``Inhomogeneous_NPTBerendsen`` with mask (1, 1, 0): x and y follow their own stress, z stays."""
    _, inhomogeneous, one_call = _ase_classes()
    at, steps = _strained(), 200
    eng = LoupEngine(sto_bundle)
    _start(eng, at)
    eng.run(steps, _npt(mask=(1, 1, 0)))
    cell = eng.get_cell()
    ref = _ase_run(one_call(inhomogeneous), at, model_path, steps, mask=(1, 1, 0))
    rel = np.abs(np.diag(cell) / np.diag(ref.cell.array) - 1.0)
    print(f"Inhomogeneous Berendsen NPT, mask (1, 1, 0), 200 steps: cell lengths {np.round(np.diag(cell), 5)} A from "
          f"{at.cell.array[0, 0]:.5f}; against ASE's class with one force call per step: relative {rel.max():.1e}")
    assert rel.max() < 1e-6
    assert cell[2, 2] == at.cell.array[2, 2] and cell[0, 0] > at.cell.array[0, 0] * 1.0005
    assert abs(cell[0, 0] - cell[1, 1]) > 1e-9                     # each axis has its own factor
    assert np.abs(cell - np.diag(np.diag(cell))).max() < 1e-9      # the angles stay


def test_the_pressure_goes_to_the_target_and_calls_continue(sto_bundle):
    at = _strained()
    whole = LoupEngine(sto_bundle)
    _start(whole, at)
    whole.run(800, _npt(taup_fs=50.0, thermo_every=10))
    rows = whole.read_thermo()
    late = rows["pressure_gpa"][-20:]

    parts = LoupEngine(sto_bundle)
    _start(parts, at)
    for _ in range(8):
        parts.run(100, _npt(taup_fs=50.0))
    rel = abs(np.linalg.det(parts.get_cell()) / np.linalg.det(whole.get_cell()) - 1.0)
    print(f"Berendsen NPT to 0 GPa, taup 50 fs: pressure {rows['pressure_gpa'][0]:.2f} GPa at step 10, mean of the "
          f"last 200 steps {late.mean():.3f} GPa (scatter {late.std():.2f}); volume {rows['volume_a3'][-1]:.2f} A^3 "
          f"from {at.get_volume():.2f}; eight calls of 100 steps against one of 800: volume relative {rel:.1e}")
    assert rows["pressure_gpa"][0] > 2.0 and abs(late.mean()) < 1.0
    assert rel < 1e-6

    target = LoupEngine(sto_bundle)                                 # another target pressure: a smaller cell
    _start(target, at)
    target.run(800, _npt(taup_fs=50.0, pressure_gpa=5.0))
    assert np.linalg.det(target.get_cell()) < 0.99 * np.linalg.det(whole.get_cell())


def test_refusals(sto_bundle):
    eng = LoupEngine(sto_bundle)
    at = _strained()
    _start(eng, at)
    for fields, reason in (
            (dict(taup_fs=0.0), "tau_p_fs must be finite and positive, got 0 fs"),
            (dict(taup_fs=float("nan")), "tau_p_fs must be finite and positive"),
            (dict(pressure_gpa=float("inf")), "pressure_gpa must be finite"),
            (dict(taut_fs=0.5), "tau_t_fs must be at least the timestep for the Berendsen thermostat"),
            (dict(mask=(0, 0, 0)), "cell_mask frees no axis"),
            (dict(mask=(1, 2, 0)), "cell_mask entries must be 0 or 1")):
        with pytest.raises(BackendError, match="loup_run: " + reason):
            eng.run(10, _npt(**fields))
    with pytest.raises(BackendError, match="loup_run: compressibility_per_gpa must be finite and positive"):
        eng.run(10, _core.integrator(_core.LOUP_BERENDSEN_NPT, 1.0, temp_k=300.0, tau_t_fs=50.0, tau_p_fs=100.0))
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_fixed_atoms(fixed)
    with pytest.raises(BackendError, match="loup_run: a barostat with fixed atoms"):
        eng.run(10, _npt())
    eng.set_fixed_atoms(None)
    assert eng.run(10, _npt()).final_temperature_k > 100.0


def test_a_simulation_with_the_barostat_writes_resumes_and_matches_the_engine(sto_bundle, model_path, tmp_path):
    """``lm.Simulation`` with ``lm.integrators.Berendsen(pressure_GPa=...)``: the rows carry volume and pressure,
    the frames their cell, a resumed run goes on from the restart's cell, and the ASE drop-in ends where the
    engine's own call does."""
    from loupmd import integrators, output
    from loupmd.ase import md as ase_md

    at = _strained()
    record = integrators.Berendsen(timestep_fs=1.0, temperature_K=300.0, taut_fs=50.0, pressure_GPa=0.0,
                                   taup_fs=100.0, compressibility_per_GPa=KAPPA, fixcm=False)
    ff = loupmd.load(model_path, trusted=True)
    sim = loupmd.Simulation(at, ff, integrator=record, seed=3,
                            output=loupmd.Output(str(tmp_path / "npt"), thermo_every=20, trajectory_every=100,
                                                 restart_every=200))
    sim.run(steps=200)
    volume_200 = sim.atoms.get_volume()
    sim.close()
    again = loupmd.Simulation.resume(tmp_path / "npt", force_field=ff)
    again.run(steps=100)
    final = again.atoms
    again.close()
    header, rows = output.read_thermo(tmp_path / "npt")
    volumes = np.array([float(row[8]) for row in rows]) * len(at)
    pressures = np.array([float(row[9]) for row in rows])
    frames = output.read_frames(tmp_path / "npt")

    eng = LoupEngine(sto_bundle)                                  # the same 200 steps as one engine call
    _start(eng, at)
    eng.run(200, _npt())
    direct = abs(np.linalg.det(eng.get_cell()))

    atoms = at.copy()
    dyn = ase_md.NPTBerendsen(atoms, 1.0 * units.fs, temperature_K=300.0, pressure_au=0.0, taut=50.0 * units.fs,
                              taup=100.0 * units.fs, compressibility_au=KAPPA * GPA, fixcm=False, model=ff)
    dyn.run(200)
    print(f"lm.Simulation with Berendsen NPT: volume {volumes[0]:.2f} -> {volume_200:.3f} A^3 after 200 steps (one "
          f"engine call: relative {abs(volume_200 / direct - 1):.1e}; the ASE drop-in: "
          f"{abs(atoms.get_volume() / direct - 1):.1e}), {final.get_volume():.3f} after 100 more from the restart; "
          f"pressure {pressures[0]:.2f} GPa at step 0, {pressures[10]:.2f} at step 200, {pressures[-1]:.2f} at 300")
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS)
    assert [int(row[0]) for row in rows] == list(range(0, 301, 20))
    assert volumes[0] == pytest.approx(at.get_volume(), rel=1e-12) and volumes[10] == pytest.approx(volume_200, rel=1e-12)
    assert volumes[-1] == pytest.approx(final.get_volume(), rel=1e-12)
    assert abs(volume_200 / direct - 1) < 1e-6 and abs(atoms.get_volume() / direct - 1) < 1e-6
    assert pressures[0] > 5.0 and abs(pressures[-1]) < abs(pressures[0]) / 3
    assert [frame.get_volume() for frame in frames] == pytest.approx([volumes[0], volumes[5], volumes[10], volumes[15]],
                                                                    rel=1e-9)
    assert final.get_volume() > volume_200 > at.get_volume()
