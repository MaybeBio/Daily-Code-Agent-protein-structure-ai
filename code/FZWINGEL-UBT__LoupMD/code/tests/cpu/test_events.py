"""Events on ``Simulation`` (plan task S6-T01): positions, momenta, masses, species, the total charge and the friction
as transactions between two ``run`` calls, on the fake engine of ``fake_core.py``. A rejected event leaves the run as
it was and usable. Needs neither a GPU nor the library."""
from __future__ import annotations

import numpy as np
import pytest
from ase.build import bulk
from ase.data import atomic_masses
from fake_core import SpringEngine

import loupmd
from loupmd import integrators, output
from loupmd.config import Output
from loupmd.errors import BackendError, InputError, PlanRefused


@pytest.fixture
def setup(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    exported = []

    def ensure_bundle(model_path, numbers, head=None, charge=None, spin_multiplicity=None, environ=None):
        exported.append((tuple(numbers), charge, spin_multiplicity))
        return model_path.with_name("bundle.loup")

    def force_field():
        return loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine, ensure_bundle=ensure_bundle,
                           probe=lambda p: None)

    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 1, 1))          # 16 atoms
    atoms.set_velocities(np.random.default_rng(3).normal(0.0, 0.02, atoms.positions.shape))

    def make(directory=None, integrator=None, **more):
        out = Output(str(tmp_path / directory), **more) if directory else None
        return loupmd.Simulation(atoms, force_field(), integrator=integrator or integrators.NVE(timestep_fs=1.0),
                                 output=out, seed=7)

    make.atoms, make.exported, make.tmp_path = atoms, exported, tmp_path
    return make


def test_set_positions_moves_the_atoms_and_keeps_the_momenta(setup):
    sim = setup("run", thermo_every=10)
    sim.run(steps=15)
    before = sim.atoms
    moved = before.positions + 0.01
    sim.set_positions(moved)
    after = sim.atoms
    assert np.allclose(after.positions, moved) and np.allclose(after.get_momenta(), before.get_momenta())
    assert sim.step == 15
    sim.run(steps=15)
    sim.close()
    steps = [int(row[0]) for row in output.read_thermo(setup.tmp_path / "run")[1]]
    assert steps == [0, 10, 20, 30]                       # the rows stay on their cadence across the event


def test_set_masses_keeps_the_momenta_as_ase_does(setup):
    sim = setup()
    sim.run(steps=5)
    before = sim.atoms
    masses = before.get_masses() * 2.0
    sim.set_masses(masses)
    after = sim.atoms
    assert np.allclose(after.get_masses(), masses)
    assert np.allclose(after.get_momenta(), before.get_momenta())
    assert np.allclose(after.get_velocities(), before.get_velocities() / 2.0)
    engine, = SpringEngine.made
    assert np.allclose(engine.masses, masses)


def test_set_species_within_the_bundle_exports_nothing_and_reaches_the_output(setup):
    sim = setup("run", thermo_every=5, trajectory_every=5)
    sim.run(steps=5)
    exports = len(setup.exported)
    before = sim.atoms
    numbers = before.numbers.copy()
    numbers[0] = 17                                       # a sodium becomes a chlorine
    sim.set_species(numbers)
    after = sim.atoms
    assert len(setup.exported) == exports and len(SpringEngine.made) == 1
    assert after.numbers[0] == 17 and after.get_masses()[0] == pytest.approx(atomic_masses[17])
    assert after.get_masses()[1:] == pytest.approx(before.get_masses()[1:])
    assert np.allclose(after.get_momenta(), before.get_momenta())
    sim.set_species(["Na" if z == 11 else "Cl" for z in setup.atoms.numbers])     # symbols, and back
    assert np.array_equal(sim.atoms.numbers, setup.atoms.numbers)
    sim.set_species(numbers)
    sim.run(steps=5)
    path = sim.save_restart()
    sim.close()
    frames = output.read_frames(setup.tmp_path / "run")
    assert frames[0].numbers[0] == 11 and frames[-1].numbers[0] == 17
    with np.load(path) as data:
        assert data["numbers"][0] == 17


def test_a_rejected_event_leaves_the_run_as_it_was(setup, monkeypatch):
    sim = setup()
    sim.run(steps=5)
    before = sim.atoms
    numbers = before.numbers.copy()
    numbers[0] = 26                                       # iron is not in the bundle
    with pytest.raises(PlanRefused, match="the run's bundle does not have"):
        sim.set_species(numbers)
    with pytest.raises(InputError, match="positions must be finite"):
        sim.set_positions(np.full((len(before), 3), np.nan))
    with pytest.raises(InputError, match="shape"):
        sim.set_masses(np.ones(3))
    engine, = SpringEngine.made

    def broken(positions, cell, compute_stress=True):     # the engine refuses the new state
        raise BackendError("loup_evaluate: non-finite energy, forces or stress", call="loup_evaluate")

    monkeypatch.setattr(engine, "evaluate", broken)
    with pytest.raises(BackendError):
        sim.update(positions=before.positions + 0.02, masses=before.get_masses() * 3.0)
    monkeypatch.undo()
    after = sim.atoms
    assert np.allclose(after.positions, before.positions) and np.allclose(after.get_momenta(), before.get_momenta())
    assert np.allclose(after.get_masses(), before.get_masses()) and np.allclose(engine.masses, before.get_masses())
    sim.run(steps=5)                                      # usable
    assert sim.step == 10


def test_set_friction_changes_the_thermostat_and_is_refused_without_one(setup):
    sim = setup(integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01))
    sim.run(steps=5)
    sim.set_friction(0.05)
    assert sim.config.friction_per_fs == 0.05
    with pytest.raises(InputError):
        sim.set_friction(-1.0)
    assert sim.config.friction_per_fs == 0.05
    nve = setup()
    with pytest.raises(InputError, match="no friction to change"):
        nve.set_friction(0.05)


def test_set_charges_loads_the_model_again_and_refuses_per_atom_charges(setup):
    sim = setup("run")
    sim.run(steps=5)
    before = sim.atoms
    with pytest.raises(PlanRefused, match="per-atom charges"):
        sim.set_charges(np.zeros(len(before)))
    sim.set_charges(total_charge=1, spin_multiplicity=2)
    assert sim.force_field.charge == 1 and sim.force_field.spin_multiplicity == 2
    assert setup.exported[-1][1:] == (1, 2) and len(SpringEngine.made) == 2
    assert np.allclose(sim.atoms.positions, before.positions)
    sim.run(steps=5)
    sim.close()
    import json

    record = json.loads((setup.tmp_path / "run" / "simulation.json").read_text())
    assert record["model"]["charge"] == 1 and record["model"]["spin_multiplicity"] == 2


def test_events_before_the_first_step_change_the_starting_structure(setup):
    sim = setup()
    numbers = setup.atoms.numbers.copy()
    numbers[:2] = 26                                      # before the start any element of the model is fine
    sim.set_species(numbers)
    sim.set_positions(setup.atoms.positions + 0.01)
    sim.run(steps=2)
    assert setup.exported[-1][0] == (11, 17, 26)
    assert sim.atoms.numbers[0] == 26


def test_events_are_refused_on_a_closed_simulation(setup):
    sim = setup()
    sim.run(steps=2)
    sim.close()
    with pytest.raises(InputError, match="closed"):
        sim.set_positions(setup.atoms.positions)
