"""The ASE drop-in classes of ``loupmd.ase`` (plan task S4-T13, the part the engine has): ASE's arguments and
units, observers, atoms updated in place. Fake engine and EMT; needs neither a GPU nor the library."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from ase.build import bulk
from ase.calculators.emt import EMT
from ase.optimize import LBFGS as AseLBFGS
from fake_core import SpringEngine

import loupmd
from loupmd import _core, integrators, optimize
from loupmd.ase import md as ase_md
from loupmd.ase import optimize as ase_optimize
from loupmd.errors import InputError, PlanRefused


@pytest.fixture
def ff(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


def _moving():
    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    atoms.set_velocities(np.random.default_rng(3).normal(0.0, 0.02, atoms.positions.shape))
    return atoms


def test_langevin_takes_ase_s_units_and_updates_the_atoms_in_place(ff):
    atoms = _moving()
    start = atoms.positions.copy()
    dyn = ase_md.Langevin(atoms, 2.0 * units.fs, temperature_K=350, friction=0.02 / units.fs, fixcm=False, model=ff,
                          seed=4)
    seen = []
    dyn.attach(lambda: seen.append((dyn.get_number_of_steps(), atoms.positions.copy(), atoms.get_potential_energy())),
               interval=10)
    assert dyn.run(40) is True and dyn.get_number_of_steps() == 40
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 10, _core.LOUP_LANGEVIN, 0)] * 4
    config = dyn.simulation.config
    assert (config.timestep_fs, config.temperature_K, config.seed) == (pytest.approx(2.0), 350.0, 4)
    assert config.friction_per_fs == pytest.approx(0.02)
    assert [step for step, _, _ in seen] == [0, 10, 20, 30, 40] and np.array_equal(seen[0][1], start)
    assert np.array_equal(atoms.positions, engine.pos) and np.array_equal(seen[-1][1], engine.pos)
    assert np.allclose(atoms.get_velocities(), engine.vel) and atoms.get_potential_energy() == engine._energy()
    assert np.array_equal(atoms.get_forces(), engine._forces())
    dyn.run(5)                                             # goes on from where it is; the next observer call at 50
    assert dyn.get_number_of_steps() == 45 and len(seen) == 5


def test_velocity_verlet_and_observers_of_different_intervals(ff):
    atoms = _moving()
    dyn = ase_md.VelocityVerlet(atoms, 1.0 * units.fs, model=ff)
    calls = {"a": [], "b": []}
    dyn.attach(lambda: calls["a"].append(dyn.nsteps), interval=4)
    dyn.attach(lambda: calls["b"].append(dyn.nsteps), interval=6)
    dyn.run(12)
    assert calls == {"a": [0, 4, 8, 12], "b": [0, 6, 12]}
    assert [e[1] for e in SpringEngine.made[0].log if isinstance(e, tuple) and e[0] == "run"] == [2] * 6
    assert dyn.simulation.config.scheme == "nve"


def test_what_is_refused(ff):
    atoms = _moving()
    assert ase_md.Langevin(atoms, units.fs, temperature_K=300, friction=0.01 / units.fs,
                           model=ff).simulation.config.fixcm is True                       # ASE's default
    with pytest.raises(InputError, match="needs model="):
        ase_md.VelocityVerlet(atoms, units.fs)
    with pytest.raises(InputError, match="needs temperature_K and friction"):
        ase_md.Langevin(atoms, units.fs, fixcm=False, model=ff)
    with pytest.raises(TypeError, match="unexpected keyword arguments nonsense"):
        ase_md.VelocityVerlet(atoms, units.fs, model=ff, nonsense="md.traj")
    with pytest.raises(InputError, match="already loaded"):
        ase_md.VelocityVerlet(atoms, units.fs, model=ff, head="x")
    with pytest.raises(InputError, match="VelocityVerlet: rng= is not taken"):
        ase_md.VelocityVerlet(atoms, units.fs, model=ff, rng=np.random.default_rng(1))
    with pytest.raises(TypeError, match="temperature .in eV. or temperature_K, not both"):
        ase_md.Langevin(atoms, units.fs, 0.025, 0.01 / units.fs, temperature_K=300, model=ff)
    for name in ("Langevin", "LangevinBAOAB", "VelocityVerlet", "Bussi", "NoseHooverChainNVT", "IsotropicMTKNPT",
                 "MTKNPT", "NVTBerendsen", "NPTBerendsen", "Inhomogeneous_NPTBerendsen"):
        assert isinstance(getattr(ase_md, name), type), name                 # every MD class of the plan is there
    with pytest.raises(AttributeError):
        ase_md.Nonsense
    assert SpringEngine.made == []


class EMTField:
    def evaluate(self, atoms, stress=False, skin=0.5):
        at = atoms.copy()
        at.set_constraint()
        at.calc = EMT()
        return at.get_potential_energy(), at.get_forces(), at.get_stress(voigt=False) if stress else None


def _rattled_copper():
    at = bulk("Cu", "fcc", a=3.6, cubic=True).repeat((2, 2, 2))
    at.positions += np.random.default_rng(3).normal(0.0, 0.08, at.positions.shape)
    return at


@pytest.mark.parametrize("cls", [ase_optimize.LBFGS, ase_optimize.FIRE])
def test_the_optimisers_relax_in_place_and_count_ase_s_steps(cls, monkeypatch):
    from ase.optimize import FIRE as AseFIRE

    monkeypatch.setattr(ase_optimize, "force_field_of", lambda model, head, options, what: EMTField())
    atoms = _rattled_copper()
    reference = atoms.copy()
    reference.calc = EMT()
    ase_optimizer = (AseLBFGS if cls is ase_optimize.LBFGS else AseFIRE)(reference, logfile=None)
    ase_optimizer.run(fmax=0.02)
    opt = cls(atoms, model="anything")
    steps = []
    opt.attach(lambda: steps.append(opt.get_number_of_steps()))
    assert opt.run(fmax=0.02) is True
    assert opt.get_number_of_steps() == ase_optimizer.get_number_of_steps() == steps[-1] and steps[0] == 0
    assert np.abs(atoms.positions - reference.positions).max() < 1e-9          # the caller's atoms, relaxed
    assert atoms.get_potential_energy() == pytest.approx(reference.get_potential_energy(), abs=1e-9)
    assert opt.run(fmax=0.02) is True and opt.get_number_of_steps() == 0       # already there


def test_a_cell_filter_and_refusals_of_the_optimisers(monkeypatch):
    from ase.filters import FrechetCellFilter

    monkeypatch.setattr(ase_optimize, "force_field_of", lambda model, head, options, what: EMTField())
    atoms = _rattled_copper()
    atoms.set_cell(atoms.cell.array * 1.03, scale_atoms=True)
    reference = atoms.copy()
    reference.calc = EMT()
    AseLBFGS(FrechetCellFilter(reference), logfile=None).run(fmax=0.02, steps=50)
    opt = ase_optimize.LBFGS(atoms, cell_filter=optimize.FrechetCell(), model="anything")
    opt.run(fmax=0.02, steps=50)
    assert np.abs(atoms.cell.array - reference.cell.array).max() < 1e-8
    assert np.abs(atoms.positions - reference.positions).max() < 1e-8
    with pytest.raises(InputError, match="takes an ase.Atoms or an ase.filters.FrechetCellFilter, got str"):
        ase_optimize.LBFGS("atoms", model="anything")
    with pytest.raises(InputError, match="use_line_search=True is not offered"):
        ase_optimize.LBFGS(atoms, use_line_search=True, model="anything")
    with pytest.raises(InputError, match="LBFGS: restart= is not offered"):
        ase_optimize.LBFGS(atoms, "history.json", model="anything")
    with pytest.raises(InputError, match="FIRE: position_reset_callback= is not offered"):
        ase_optimize.FIRE(atoms, position_reset_callback=print, model="anything")


def test_ase_s_filter_object_and_its_settings_are_taken(monkeypatch):
    from ase.filters import FrechetCellFilter, UnitCellFilter

    monkeypatch.setattr(ase_optimize, "force_field_of", lambda model, head, options, what: EMTField())
    settings = dict(mask=[1, 1, 1, 0, 0, 0], scalar_pressure=0.02)
    atoms = _rattled_copper()
    atoms.set_cell(atoms.cell.array * 1.03, scale_atoms=True)
    reference = atoms.copy()
    reference.calc = EMT()
    AseLBFGS(FrechetCellFilter(reference, **settings), logfile=None).run(fmax=0.02, steps=40)
    opt = ase_optimize.LBFGS(FrechetCellFilter(atoms, **settings), logfile=None, model="anything")
    assert opt.record.cell_filter == optimize.FrechetCell(
        scalar_pressure_GPa=0.02 / units.GPa, mask=((1, 0, 0), (0, 1, 0), (0, 0, 1)), exp_cell_factor=32.0)
    opt.run(fmax=0.02, steps=40)
    assert np.abs(atoms.cell.array - reference.cell.array).max() < 1e-8          # the caller's atoms, in place
    assert np.abs(atoms.positions - reference.positions).max() < 1e-8
    assert atoms.get_stress().shape == (6,)
    with pytest.raises(PlanRefused, match="got ASE's UnitCellFilter, which is not supported"):
        ase_optimize.LBFGS(UnitCellFilter(atoms), model="anything")
    with pytest.raises(InputError, match="a FrechetCellFilter and cell_filter=; one of the two"):
        ase_optimize.LBFGS(FrechetCellFilter(atoms), cell_filter=optimize.FrechetCell(), model="anything")


def test_the_optimisers_write_ase_s_log_and_trajectory(monkeypatch, tmp_path, capsys):
    from ase.io import read

    monkeypatch.setattr(ase_optimize, "force_field_of", lambda model, head, options, what: EMTField())
    atoms = _rattled_copper()
    reference = atoms.copy()
    reference.calc = EMT()
    AseLBFGS(reference, logfile=str(tmp_path / "ase.log"), trajectory=str(tmp_path / "ase.traj")).run(fmax=0.02)
    with ase_optimize.LBFGS(atoms, logfile=str(tmp_path / "own.log"), trajectory=str(tmp_path / "own.traj"),
                            model="anything") as opt:
        opt.run(fmax=0.02)

    def columns(path):                                   # everything but the wall-clock time
        return [(line.split()[0], line.split()[1], line.split()[3:]) for line in path.read_text().splitlines()]

    ours, theirs = columns(tmp_path / "own.log"), columns(tmp_path / "ase.log")
    assert [row[:2] for row in ours] == [row[:2] for row in theirs] and ours[0] == theirs[0]
    assert np.allclose([[float(x) for x in row[2]] for row in ours[1:]],
                       [[float(x) for x in row[2]] for row in theirs[1:]], atol=2e-6)
    frames, expected = read(tmp_path / "own.traj", ":"), read(tmp_path / "ase.traj", ":")
    assert len(frames) == len(expected) == opt.get_number_of_steps() + 1
    assert np.abs(frames[-1].positions - expected[-1].positions).max() < 1e-9
    assert frames[3].get_potential_energy() == pytest.approx(expected[3].get_potential_energy(), abs=1e-9)
    assert np.allclose(frames[3].get_forces(), expected[3].get_forces(), atol=1e-9)
    ase_optimize.FIRE(_rattled_copper(), model="anything").run(fmax=0.5, steps=2)          # ASE's default: stdout
    printed = capsys.readouterr().out.splitlines()
    assert printed[0].split() == ["Step", "Time", "Energy", "fmax"] and printed[1].startswith("FIRE:    0 ")


def test_bussi_takes_ase_s_arguments(ff):
    atoms = _moving()
    dyn = ase_md.Bussi(atoms, 2.0 * units.fs, 350, 100 * units.fs, model=ff, seed=4)
    config = dyn.simulation.config
    assert (config.scheme, config.temperature_K, config.seed, config.fixcm) == ("csvr", 350.0, 4, False)
    assert (config.timestep_fs, config.tau_fs) == (pytest.approx(2.0), pytest.approx(100.0))
    assert dyn.run(20) is True and dyn.get_time() == pytest.approx(40 * units.fs)
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 20, _core.LOUP_CSVR, 0)]
    with pytest.raises(InputError, match="Bussi: rng= is not taken"):
        ase_md.Bussi(atoms, units.fs, 300, 100 * units.fs, rng=np.random.default_rng(1), model=ff)
    at_rest = atoms.copy()
    at_rest.set_velocities(np.zeros((len(atoms), 3)))
    with pytest.raises(InputError, match="the structure is at rest, and CSVR rescales the velocities"):
        ase_md.Bussi(at_rest, units.fs, 300, 100 * units.fs, model=ff)
    assert integrators.CSVR(timestep_fs=1.0, temperature_K=300, tau_fs=100).to_config(seed=1).fixcm is True


def test_ase_s_trajectory_and_logfile_mean_what_they_mean_in_ase(ff, tmp_path):
    from ase.io import read

    atoms = _moving()
    with ase_md.Langevin(atoms, 1.0 * units.fs, temperature_K=300, friction=0.01 / units.fs, model=ff, seed=2,
                         trajectory=str(tmp_path / "md.traj"), logfile=str(tmp_path / "md.log"),
                         loginterval=5) as dyn:
        dyn.run(20)
    frames = read(tmp_path / "md.traj", ":")
    assert len(frames) == 5                                          # steps 0, 5, 10, 15, 20
    assert np.array_equal(frames[-1].positions, atoms.positions)
    assert frames[-1].get_potential_energy() == atoms.get_potential_energy()
    lines = (tmp_path / "md.log").read_text().splitlines()
    assert lines[0].split()[:2] == ["Time[ps]", "Etot[eV]"] and len(lines) == 6
    assert [float(line.split()[0]) for line in lines[1:]] == pytest.approx([0.0, 0.005, 0.010, 0.015, 0.020])
    assert float(lines[-1].split()[2]) == pytest.approx(atoms.get_potential_energy(), abs=1e-3)
    engine, = SpringEngine.made
    assert [e[1] for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [5, 5, 5, 5]


def test_the_nose_hoover_chain_takes_ase_s_arguments(ff):
    atoms = _moving()
    dyn = ase_md.NoseHooverChainNVT(atoms, 2.0 * units.fs, 350, 100 * units.fs, tchain=4, model=ff)
    config = dyn.simulation.config
    assert (config.scheme, config.temperature_K, config.mass_temperature_K, config.tchain, config.tloop,
            config.fixcm) == ("nose_hoover", 350.0, 350.0, 4, 1, False)
    assert (config.timestep_fs, config.tau_fs) == (pytest.approx(2.0), pytest.approx(100.0))
    assert dyn.run(20) is True
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 20, _core.LOUP_NHC, 0)]
    record = integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=300, tdamp_fs=100)
    assert record.to_config(seed=1).fixcm is True and record.to_config(seed=1, fixed_atoms=True).fixcm is False
    assert integrators.from_data({"type": "NoseHooverChain", "tdamp_fs": 100.0}, timestep_fs=1.0,
                                 temperature_K=300) == record
    with pytest.raises(InputError, match="NoseHooverChain.temperature_K must be above 0 K"):
        integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=0.0, tdamp_fs=100)


def test_the_berendsen_thermostat_takes_ase_s_arguments(ff):
    atoms = _moving()
    dyn = ase_md.NVTBerendsen(atoms, 2.0 * units.fs, temperature_K=350, taut=100 * units.fs, model=ff)
    config = dyn.simulation.config
    assert (config.scheme, config.temperature_K, config.fixcm) == ("berendsen", 350.0, True)
    assert (config.timestep_fs, config.tau_fs) == (pytest.approx(2.0), pytest.approx(100.0))
    assert dyn.run(20) is True
    engine, = SpringEngine.made
    assert [e for e in engine.log if isinstance(e, tuple) and e[0] == "run"] == [("run", 20, _core.LOUP_BERENDSEN_NVT, 0)]
    old = ase_md.NVTBerendsen(atoms, units.fs, 300 * units.kB, 100 * units.fs, False, model=ff)   # ASE's order
    assert old.simulation.config.temperature_K == pytest.approx(300.0) and old.simulation.config.fixcm is False
    with pytest.raises(InputError, match="NVTBerendsen needs temperature_K and taut"):
        ase_md.NVTBerendsen(atoms, units.fs, temperature_K=300, model=ff)
    with pytest.raises(InputError, match="the Berendsen barostat needs compressibility_per_GPa"):
        integrators.Berendsen(timestep_fs=1.0, temperature_K=300, taut_fs=100, pressure_GPa=0.0, taup_fs=1000.0)
    assert integrators.from_data({"type": "Berendsen", "taut_fs": 100.0}, timestep_fs=1.0, temperature_K=300) == \
        integrators.Berendsen(timestep_fs=1.0, temperature_K=300, taut_fs=100.0)


def test_fastmace_s_ase_example_runs_with_its_import_line_changed(ff, tmp_path):
    """docs/guide/ase.md of FastMACE, "Level 1: change the import": ``from fastmace.ase import Langevin`` becomes
    ``from loupmd.ase import Langevin``; ``model=`` here is the loaded fake."""
    from ase.io import read

    from loupmd.ase import Langevin

    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    atoms.set_velocities(np.random.default_rng(2).normal(0.0, 0.02, atoms.positions.shape))
    energies = []

    def print_energy():
        energies.append(atoms.get_potential_energy())

    dyn = Langevin(atoms, 0.5 * units.fs, temperature_K=300, friction=0.02 / units.fs, model=ff,
                   trajectory=str(tmp_path / "run.traj"), logfile=str(tmp_path / "run.log"), loginterval=20)
    dyn.attach(print_energy, interval=100)
    dyn.run(200)
    summary = dyn.summary
    assert "NVT, Langevin, timestep 0.5 fs" in summary and "200 steps" in summary
    assert len(energies) == 3 and len(read(tmp_path / "run.traj", index=":")) == 11
    assert len((tmp_path / "run.log").read_text().splitlines()) == 12            # ASE's header and 11 rows
    import loupmd.ase

    assert set(loupmd.ase.__all__) >= {"Langevin", "LangevinBAOAB", "MTKNPT", "NPTBerendsen", "LBFGS", "FIRE"}
    assert loupmd.ase.LBFGS is ase_optimize.LBFGS and loupmd.ase.MTKNPT is ase_md.MTKNPT

