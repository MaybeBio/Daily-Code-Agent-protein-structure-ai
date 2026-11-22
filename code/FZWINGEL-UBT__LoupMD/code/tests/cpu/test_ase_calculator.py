"""The ASE calculator ``lm.calc`` (plan task S2-T10) against a fake engine: what it computes, when it reuses the
engine and what it refuses. Needs neither a GPU nor the library; ``test_ase_calculator_gpu.py`` has the real runs."""
from __future__ import annotations

import numpy as np
import pytest
from ase import Atoms
from ase.build import bulk

import loupmd
from loupmd.ase import calculator as module
from loupmd.errors import CheckpointTrustError, InputError, PlanRefused

K = 0.5      # eV/A^2 of the fake engine's springs


class SpringEngine:
    """Every atom on a spring to the origin: E = K/2 sum r^2, F = -K r, and a made-up symmetric stress."""

    made = []

    def __init__(self, bundle, device_id=0):
        self.bundle, self.device_id, self.calls = bundle, device_id, []
        SpringEngine.made.append(self)

    def set_system(self, numbers, masses, skin=0.5):
        self.calls.append(("set_system", tuple(int(z) for z in numbers), skin))
        self.n = len(numbers)

    def evaluate(self, positions, cell, compute_stress=True):
        positions = np.asarray(positions, dtype=float)
        assert positions.shape == (self.n, 3)
        self.calls.append(("evaluate", bool(compute_stress)))
        stress = np.array([[1.0, 0.4, 0.5], [0.4, 2.0, 0.6], [0.5, 0.6, 3.0]]) * 1e-3 if compute_stress else None
        return 0.5 * K * float((positions ** 2).sum()), -K * positions, stress

    def evaluate_per_atom(self, positions, cell, compute_stress=False):
        energy, forces, stress = self.evaluate(positions, cell, compute_stress)
        self.calls[-1] = ("evaluate_per_atom", bool(compute_stress))
        return energy, forces, stress, 0.5 * K * (np.asarray(positions, dtype=float) ** 2).sum(axis=1)


@pytest.fixture
def checkpoint(tmp_path):
    path = tmp_path / "some.model"
    path.write_bytes(b"never unpickled here")
    return path


@pytest.fixture
def make(checkpoint):
    SpringEngine.made = []
    exported = []

    def ensure_bundle(model_path, numbers, head=None, charge=None, spin_multiplicity=None, environ=None):
        exported.append((model_path.name, tuple(numbers), head, charge, spin_multiplicity))
        return model_path.with_name("bundle-" + "-".join(map(str, numbers)) + ".loup")

    def build(**options):
        options.setdefault("trusted", True)
        options.setdefault("probe", lambda path: None)          # a file outside the table, and no torch to read it
        return loupmd.calc(str(checkpoint), engine_factory=SpringEngine, ensure_bundle=ensure_bundle, **options)

    build.exported = exported
    return build


def _nacl():
    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    at.positions += np.random.default_rng(3).normal(0.0, 0.05, at.positions.shape)
    return at


def test_energy_forces_and_voigt_stress(make):
    at = _nacl()
    at.calc = make()
    assert isinstance(at.calc, module.LoupCalculator)
    assert at.get_potential_energy() == pytest.approx(0.5 * K * (at.positions ** 2).sum())
    assert at.get_potential_energy(force_consistent=True) == at.get_potential_energy()      # free energy
    assert np.allclose(at.get_forces(), -K * at.positions)
    assert np.allclose(at.get_stress(), np.array([1.0, 2.0, 3.0, 0.6, 0.5, 0.4]) * 1e-3)   # xx yy zz yz xz xy
    assert at.get_stress(voigt=False).shape == (3, 3)
    assert set(at.calc.implemented_properties) == {"energy", "free_energy", "forces", "stress", "energies"}


def test_per_atom_energies_come_from_the_per_atom_call_only_when_asked_for(make):
    """S6-T08: get_potential_energies asks the engine for its per-atom call; energy and forces alone do not."""
    at = _nacl()
    at.calc = make()
    at.get_forces()
    energies = at.get_potential_energies()
    engine, = SpringEngine.made
    assert [c[0] for c in engine.calls if c[0].startswith("evaluate")] == ["evaluate", "evaluate_per_atom"]
    assert energies.shape == (len(at),)
    assert energies.sum() == pytest.approx(at.get_potential_energy())


def test_the_stress_is_computed_only_when_it_is_asked_for(make):
    at = _nacl()
    at.calc = make()
    at.get_forces()
    at.get_potential_energy()                       # same state: no second evaluation
    engine, = SpringEngine.made
    assert [c for c in engine.calls if c[0] == "evaluate"] == [("evaluate", False)]
    at.get_stress()
    assert [c for c in engine.calls if c[0] == "evaluate"] == [("evaluate", False), ("evaluate", True)]
    at.get_forces()                                 # the stress call also gave the forces
    assert len([c for c in engine.calls if c[0] == "evaluate"]) == 2


def test_the_engine_is_reused_while_species_and_atom_count_stay(make):
    at = _nacl()
    at.calc = calc = make(skin=0.4, device=1)
    at.get_forces()
    at.positions += 0.01
    at.get_forces()
    at.set_cell(at.cell.array * 1.01, scale_atoms=True)
    at.get_forces()
    engine, = SpringEngine.made
    assert engine.device_id == 1 and engine.bundle.name == "bundle-11-17.loup"
    assert [c for c in engine.calls if c[0] == "set_system"] == [("set_system", tuple(at.numbers), 0.4)]
    assert len([c for c in engine.calls if c[0] == "evaluate"]) == 3
    assert make.exported == [("some.model", (11, 17), None, None, None)]
    assert calc.engine is engine


def test_a_changed_order_or_count_sets_the_system_again_on_the_same_engine(make):
    at = _nacl()
    calc = make()
    at.calc = calc
    at.get_forces()
    bigger = at.repeat((2, 1, 1))
    bigger.calc = calc
    bigger.get_forces()
    swapped = bigger[::-1]
    swapped.calc = calc
    swapped.get_forces()
    engine, = SpringEngine.made                                   # the element set stayed: one bundle, one engine
    assert [len(c[1]) for c in engine.calls if c[0] == "set_system"] == [8, 16, 16]
    assert len(make.exported) == 1


def test_a_new_element_gets_a_new_bundle_and_engine(make):
    at = _nacl()
    calc = make()
    at.calc = calc
    at.get_forces()
    doped = at.copy()
    doped.numbers[0] = 19                                          # K on a Na site
    doped.calc = calc
    doped.get_forces()
    assert [e.bundle.name for e in SpringEngine.made] == ["bundle-11-17.loup", "bundle-11-17-19.loup"]
    assert calc.engine is SpringEngine.made[1]
    # Back to NaCl: the element set {11, 17} is inside the loaded bundle's, so nothing is exported again.
    at.calc = calc
    at.positions += 0.01
    at.get_forces()
    assert len(SpringEngine.made) == 2 and len(make.exported) == 2


def test_charge_spin_and_head_reach_the_exporter(make):
    at = _nacl()
    at.calc = make(head="omol", charge=-1, spin_multiplicity=2)
    at.get_forces()
    assert make.exported == [("some.model", (11, 17), "omol", -1, 2)]


def test_a_cell_that_is_not_periodic_in_three_directions_is_refused_before_any_export(make):
    slab = _nacl()
    slab.pbc = (True, True, False)
    slab.calc = make()
    with pytest.raises(PlanRefused) as caught:
        slab.get_forces()
    assert "pbc=(True, True, False)" in str(caught.value) and "vacuum" in str(caught.value)
    molecule = Atoms("H2", positions=[[0, 0, 0], [0, 0, 0.74]])
    molecule.calc = make()
    with pytest.raises(PlanRefused, match="periodic"):
        molecule.get_potential_energy()
    assert make.exported == [] and SpringEngine.made == []


def test_an_untrusted_file_is_refused_when_the_calculator_is_made(make, checkpoint):
    with pytest.raises(CheckpointTrustError):
        make(trusted=False)
    with pytest.raises(InputError, match="neither a model label nor an existing checkpoint"):
        loupmd.calc(str(checkpoint) + ".missing", trusted=True)
    assert make.exported == [] and SpringEngine.made == []


def test_unknown_options_are_refused_by_name(checkpoint):
    with pytest.raises(TypeError, match="precision"):
        loupmd.calc(str(checkpoint), trusted=True, precision="float64")


def test_velocity_verlet_runs_on_the_calculator(make):
    """ASE's integrator drives the calculator: on springs the total energy stays to rounding."""
    from ase import units
    from ase.md.verlet import VelocityVerlet

    at = _nacl()
    at.calc = make()
    at.set_velocities(np.random.default_rng(5).normal(0.0, 0.01, at.positions.shape))
    start = at.get_total_energy()
    VelocityVerlet(at, timestep=0.5 * units.fs).run(50)
    assert at.get_total_energy() == pytest.approx(start, rel=1e-3)
    assert len(SpringEngine.made) == 1 and len([c for c in SpringEngine.made[0].calls if c[0] == "set_system"]) == 1
