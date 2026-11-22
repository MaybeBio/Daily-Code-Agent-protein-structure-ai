"""``lm.optimize`` (plan task S4-T10) against ASE's own optimisers on ASE's EMT potential: the same positions step
by step and the same number of steps. Needs neither a GPU nor the library."""
from __future__ import annotations

import numpy as np
import pytest
from ase.build import bulk
from ase.calculators.emt import EMT
from ase.constraints import FixAtoms, FixBondLength
from ase.optimize import FIRE as AseFIRE
from ase.optimize import LBFGS as AseLBFGS

from loupmd import optimize
from loupmd.errors import InputError, NonFiniteError, PlanRefused


class EMTField:
    """Stands in for a ForceField: ASE's EMT in float64."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, atoms, stress=False, skin=0.5):
        self.calls += 1
        at = atoms.copy()
        at.set_constraint()                            # the raw forces, as the engine gives them
        at.calc = EMT()
        return at.get_potential_energy(), at.get_forces(), at.get_stress(voigt=False) if stress else None


def _rattled(seed=3, rep=(2, 2, 2)):
    at = bulk("Cu", "fcc", a=3.6, cubic=True).repeat(rep)
    at.positions += np.random.default_rng(seed).normal(0.0, 0.08, at.positions.shape)
    return at


def _ase_trajectory(optimizer_class, atoms, fmax, **options):
    at = atoms.copy()
    at.calc = EMT()
    positions = [at.positions.copy()]
    opt = optimizer_class(at, logfile=None, **options)
    opt.attach(lambda: positions.append(at.positions.copy()))
    opt.run(fmax=fmax)
    return opt.get_number_of_steps(), positions[1:] if len(positions) > 1 else positions, at


@pytest.mark.parametrize("record,ase_class,options", [
    (optimize.LBFGS(), AseLBFGS, {}),
    (optimize.LBFGS(maxstep_A=0.05, memory=4, damping=0.8, alpha=40.0), AseLBFGS,
     {"maxstep": 0.05, "memory": 4, "damping": 0.8, "alpha": 40.0}),
    (optimize.FIRE(), AseFIRE, {}),
    (optimize.FIRE(dt=0.05, maxstep_A=0.1, dtmax=0.5, Nmin=3, finc=1.2, fdec=0.4, astart=0.2, fa=0.95, a=0.2),
     AseFIRE, {"dt": 0.05, "maxstep": 0.1, "dtmax": 0.5, "Nmin": 3, "finc": 1.2, "fdec": 0.4, "astart": 0.2,
               "fa": 0.95, "a": 0.2}),
])
def test_the_steps_are_ase_s(record, ase_class, options):
    atoms = _rattled()
    steps, ase_positions, ase_atoms = _ase_trajectory(ase_class, atoms, 0.02, **options)
    seen = []
    result = optimize.relax(EMTField(), atoms, record, fmax=0.02,
                            callback=lambda step, positions, energy, largest: seen.append(positions.copy()))
    assert result.steps == steps and result.converged and result.max_force < 0.02
    assert result.force_calls == steps + 1 and len(seen) == steps + 1
    # ASE's observers are called at step 0 and after every step: the same positions each time.
    for mine, theirs in zip(seen, ase_positions):
        assert np.abs(mine - theirs).max() < 1e-9
    assert np.abs(result.atoms.positions - ase_atoms.positions).max() < 1e-9
    assert result.energy == pytest.approx(ase_atoms.get_potential_energy(), abs=1e-9)
    assert np.array_equal(atoms.positions, _rattled().positions)        # the caller's atoms are untouched
    assert result.atoms.get_potential_energy() == result.energy
    assert "converged after" in str(result)


def test_the_history_drops_its_oldest_pair():
    """A memory shorter than the run: still ASE's steps."""
    atoms = _rattled(seed=5)
    steps, _, ase_atoms = _ase_trajectory(AseLBFGS, atoms, 0.005, memory=3)
    result = optimize.relax(EMTField(), atoms, optimize.LBFGS(memory=3), fmax=0.005)
    assert steps > 6 and result.steps == steps
    assert np.abs(result.atoms.positions - ase_atoms.positions).max() < 1e-8


def test_fixed_atoms_do_not_move_and_do_not_count_for_convergence():
    atoms = _rattled()
    atoms.set_constraint(FixAtoms(indices=[0, 5, 9]))
    steps, _, ase_atoms = _ase_trajectory(AseLBFGS, atoms, 0.02)
    result = optimize.relax(EMTField(), atoms, fmax=0.02)
    assert result.steps == steps and np.array_equal(result.atoms.positions[[0, 5, 9]], atoms.positions[[0, 5, 9]])
    assert np.abs(result.atoms.positions - ase_atoms.positions).max() < 1e-9
    assert not np.abs(result.atoms.get_forces()[[0, 5, 9]]).any()
    other = _rattled()
    other.set_constraint(FixBondLength(0, 1))
    with pytest.raises(PlanRefused, match="FixBondLengths"):
        optimize.relax(EMTField(), other)


def test_a_structure_at_its_minimum_takes_no_step_and_steps_bounds_the_run():
    field = EMTField()
    relaxed = optimize.relax(field, bulk("Cu", "fcc", a=3.6, cubic=True).repeat((2, 2, 2)))
    assert relaxed.steps == 0 and relaxed.converged and field.calls == 1
    short = optimize.relax(EMTField(), _rattled(), optimize.FIRE(), fmax=1e-4, steps=3)
    assert short.steps == 3 and not short.converged and short.force_calls == 4 and "not converged" in str(short)


def test_arguments_are_checked():
    atoms = _rattled()
    for bad, message in ((dict(optimizer="lbfgs"), "optimizer must be an lm.optimize record"),
                         (dict(fmax=0.0), "fmax must be positive"), (dict(steps=-1), "steps must be a whole number")):
        with pytest.raises(InputError, match=message):
            optimize.relax(EMTField(), atoms, **bad)
    with pytest.raises(InputError, match="LBFGS.memory must be an int of at least 1"):
        optimize.LBFGS(memory=0)
    with pytest.raises(InputError, match="too large"):
        optimize.LBFGS(maxstep_A=1.5)
    with pytest.raises(InputError, match="FIRE.dt must be positive"):
        optimize.FIRE(dt=0.0)
    with pytest.raises(PlanRefused, match="downhill_check is not in this version"):
        optimize.FIRE(downhill_check=True)
    with pytest.raises(InputError, match="cell_filter must be lm.optimize.FrechetCell or None"):
        optimize.LBFGS(cell_filter=object())
    with pytest.raises(InputError, match="FrechetCell.mask must be six Voigt"):
        optimize.FrechetCell(mask=(1, 1, 0))
    with pytest.raises(InputError, match="FrechetCell.hydrostatic_strain must be a bool"):
        optimize.FrechetCell(hydrostatic_strain=1)


def test_a_non_finite_force_stops_the_relaxation():
    class Broken(EMTField):
        def evaluate(self, atoms, stress=False, skin=0.5):
            energy, forces, _ = super().evaluate(atoms)
            if self.calls == 3:
                forces[0, 0] = float("nan")
            return energy, forces, None

    with pytest.raises(NonFiniteError, match="non-finite energy or forces during the relaxation"):
        optimize.relax(Broken(), _rattled())


# ------------------------------------------------------------------------- Simulation.relax and the command

def _spring_field(tmp_path):
    from fake_core import SpringEngine

    import loupmd

    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made = []
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


class _EMTForceField(EMTField):
    """EMTField with what relax_file's loader returns."""


def test_simulation_relax_moves_the_starting_structure_once(tmp_path):
    import loupmd
    from loupmd import integrators

    atoms = _rattled()
    sim = loupmd.Simulation(atoms, _spring_field(tmp_path), integrator=integrators.NVE(timestep_fs=1.0))
    sim.force_field.evaluate = EMTField().evaluate                     # relax on EMT, run on the fake engine
    with pytest.raises(InputError, match="relaxes at fixed cell"):    # its cell would be dropped
        sim.relax(loupmd.optimize.FIRE(cell_filter=loupmd.optimize.FrechetCell()))
    result = sim.relax(fmax=0.02)
    assert result.converged and sim.relaxation is result
    assert np.array_equal(sim.atoms.positions, result.atoms.positions) and not np.array_equal(
        sim.atoms.positions, atoms.positions)
    sim.run(steps=5)
    with pytest.raises(InputError, match="this run has started"):
        sim.relax()


def test_the_relax_command_writes_what_the_python_call_gives(tmp_path, monkeypatch, capsys):
    from ase.io import read, write

    from loupmd.cli import main
    from loupmd.cli import relax as cli_relax

    atoms = _rattled(rep=(1, 1, 1))
    write(tmp_path / "cu.cif", atoms)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_relax, "load", lambda model, head=None, **options: EMTField())
    assert main(["relax", "cu.cif", "--model", "anything", "--fmax", "0.02", "--repeat", "2", "2", "2"]) == 0
    out = capsys.readouterr().out
    assert "converged after" in out and "written to cu.relaxed.extxyz" in out
    written = read(tmp_path / "cu.relaxed.extxyz")
    expected = optimize.relax(EMTField(), read(tmp_path / "cu.cif").repeat((2, 2, 2)), fmax=0.02)
    assert np.abs(written.positions - expected.atoms.positions).max() < 1e-7
    assert written.get_potential_energy() == pytest.approx(expected.energy, abs=1e-7)
    assert np.abs(written.get_forces() - expected.atoms.get_forces()).max() < 1e-7
    # Not converged within the steps allowed: exit code 1, the structure is still written.
    assert main(["relax", "cu.cif", "--model", "anything", "--optimizer", "fire", "--fmax", "1e-6", "--steps", "2",
                 "--repeat", "2", "2", "2", "--output", "short.extxyz"]) == 1
    assert "not converged after 2 steps" in capsys.readouterr().out and (tmp_path / "short.extxyz").is_file()
    assert main(["relax", "absent.cif", "--model", "anything"]) == 1


# ----------------------------------------------------------------------------------------- the cell filter

def _strained(seed=4):
    atoms = _rattled(seed=seed)
    atoms.set_cell(atoms.cell.array @ np.array([[1.03, 0.01, 0.0], [0.0, 0.98, 0.02], [0.0, 0.0, 1.01]]),
                   scale_atoms=True)
    return atoms


@pytest.mark.parametrize("record,ase_class,cell,ase_cell", [
    (optimize.LBFGS, AseLBFGS, {}, {}),
    (optimize.FIRE, AseFIRE, {}, {}),
    (optimize.LBFGS, AseLBFGS, {"scalar_pressure_GPa": 2.0}, {"scalar_pressure": 2.0 * 0.006241509074460763}),
    (optimize.LBFGS, AseLBFGS, {"hydrostatic_strain": True}, {"hydrostatic_strain": True}),
    (optimize.LBFGS, AseLBFGS, {"constant_volume": True}, {"constant_volume": True}),
    (optimize.LBFGS, AseLBFGS, {"mask": (1, 1, 0, 0, 0, 1), "exp_cell_factor": 10.0},
     {"mask": [1, 1, 0, 0, 0, 1], "exp_cell_factor": 10.0}),
], ids=["lbfgs", "fire", "pressure", "hydrostatic", "constant-volume", "mask"])
def test_the_cell_filter_takes_ase_s_steps(record, ase_class, cell, ase_cell):
    from ase.filters import FrechetCellFilter

    atoms = _strained()
    reference = atoms.copy()
    reference.calc = EMT()
    ase_optimizer = ase_class(FrechetCellFilter(reference, **ase_cell), logfile=None)
    ase_optimizer.run(fmax=0.02, steps=60)
    result = optimize.relax(EMTField(), atoms, record(cell_filter=optimize.FrechetCell(**cell)), fmax=0.02, steps=60)
    assert result.steps == ase_optimizer.get_number_of_steps() and result.steps > 3
    assert np.abs(result.atoms.cell.array - reference.cell.array).max() < 1e-8
    assert np.abs(result.atoms.positions - reference.positions).max() < 1e-8
    assert result.energy == pytest.approx(reference.get_potential_energy(), abs=1e-8)
    assert np.abs(result.atoms.get_stress() - reference.get_stress()).max() < 1e-9
    assert not np.array_equal(result.atoms.cell.array, atoms.cell.array)
    if "constant_volume" in cell:
        assert result.atoms.get_volume() == pytest.approx(atoms.get_volume(), rel=1e-9)


def test_the_cell_filter_is_refused_with_fixed_atoms_and_for_long_range_models():
    atoms = _strained()
    atoms.set_constraint(FixAtoms(indices=[0]))
    with pytest.raises(PlanRefused, match="the cell cannot be relaxed while atoms are fixed"):
        optimize.relax(EMTField(), atoms, optimize.LBFGS(cell_filter=optimize.FrechetCell()))

    class Polar(EMTField):
        long_range, name = True, "polar1-s"

    with pytest.raises(PlanRefused, match="the cell cannot be relaxed with polar1-s"):
        optimize.relax(Polar(), _strained(), optimize.LBFGS(cell_filter=optimize.FrechetCell()))


def test_relax_puts_exactly_its_own_dispersion_term_on_the_shared_engine(tmp_path):
    """The force field's engine is shared with lm.calc: a term a calculator set must not leak into a relaxation,
    and dispersion= adds one (as FastMACE's relax --dispersion)."""
    import loupmd

    ff = _spring_field(tmp_path)
    ff.evaluate = EMTField().evaluate                                  # forces from EMT, the engine for the term
    atoms = _rattled()
    d3 = {"preset": "d3bj", "functional": "pbe"}
    ff.engine_for(atoms).set_dispersion(optimize._dispersion_record(ff, d3))   # as an lm.calc with D3 leaves it
    assert ff.engine.dispersion is not None and loupmd.calc is not None
    optimize.relax(ff, atoms, steps=2)
    assert ff.engine.dispersion is None                                # none asked for: none used
    optimize.relax(ff, atoms, steps=2, dispersion=d3)
    assert ff.engine.dispersion.damping == "bj" and ff.engine.dispersion.functional == "pbe"
    with pytest.raises(InputError, match="not a preset"):
        optimize.relax(ff, atoms, dispersion="d3nonsense")
    with pytest.raises(PlanRefused, match="dispersion with this force field"):
        optimize.relax(EMTField(), atoms, dispersion=d3)
