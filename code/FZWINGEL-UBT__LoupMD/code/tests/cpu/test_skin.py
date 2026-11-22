"""``skin="auto"`` (owner's decision O17): the skin from how far atoms move per step, estimated before the run and
corrected once from the engine's measurement. Fake engine; needs neither a GPU nor the library."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from ase.build import bulk, molecule
from fake_core import SpringEngine

import loupmd
from loupmd import integrators, output, protocols, skin
from loupmd.config import Output
from loupmd.errors import InputError


@pytest.fixture
def ff(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at, SpringEngine.step_disp = [], None, 0.01
    yield loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine,
                      ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)
    SpringEngine.step_disp = 0.01


def _salt(temperature=300.0):
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    atoms = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 1, 1))
    if temperature:
        MaxwellBoltzmannDistribution(atoms, temperature_K=temperature, rng=np.random.default_rng(2))
    return atoms


LANGEVIN = integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01)


def test_the_skin_of_a_step_size():
    assert [skin.skin_for_step(d) for d in (0.0, 0.02, 0.05, 0.051, 0.08, 0.11, 0.3)] == [
        0.5, 0.5, 0.5, 0.55, 0.8, 1.1, 1.5]                     # 10 x the step on a 0.05 A grid, within [0.5, 1.5]
    assert skin.adjusted(0.5, 0.04) is None and skin.adjusted(0.5, 0.055) == 0.55      # grows as soon as needed
    assert skin.adjusted(0.9, 0.08) is None and skin.adjusted(0.9, 0.07) == 0.7        # shrinks for 0.2 A or more


def test_the_estimate_before_the_run():
    water = molecule("H2O")
    # 5 sqrt(kT / m_H) dt: hydrogen at 300 K moves about 0.08 A in a 1 fs step, oxygen a quarter of that.
    assert skin.estimate_step_A(water, 1.0, 300.0) == pytest.approx(
        5.0 * np.sqrt(units.kB * 300.0 / 1.008) * units.fs, rel=1e-12)
    assert skin.estimate_step_A(water, 1.0, 300.0) == pytest.approx(0.0786, abs=2e-4)
    assert skin.estimate_step_A(water, 0.5, 300.0) == pytest.approx(0.0393, abs=1e-4)
    fixed = np.array([False, True, True])                      # only the oxygen moves
    assert skin.estimate_step_A(water, 1.0, 300.0, fixed) == pytest.approx(0.0786 * np.sqrt(1.008 / 15.999), abs=2e-4)
    assert skin.estimate_step_A(water, 1.0, None) == 0.0       # at rest and no target
    water.set_velocities([[0.0, 0.0, 2.0], [0, 0, 0], [0, 0, 0]])
    assert skin.estimate_step_A(water, 1.0, 300.0) == pytest.approx(2.0 * units.fs)   # the fastest atom now


def test_a_fixed_skin_is_the_default_of_a_simulation_and_is_checked(ff):
    sim = loupmd.Simulation(_salt(), ff, integrator=LANGEVIN)
    assert sim.skin == 0.5 and sim.skin_record == {"mode": "fixed", "skin_A": 0.5}
    sim.run(steps=400)
    assert SpringEngine.made[0].skins == [0.5]
    for bad in (-0.1, "wide", True, float("nan")):
        with pytest.raises(InputError, match="skin must be a length in A .0 or more. or 'auto'"):
            loupmd.Simulation(_salt(), ff, integrator=LANGEVIN, skin=bad)


def test_auto_estimates_then_corrects_once_from_the_measurement(ff, tmp_path):
    SpringEngine.step_disp = 0.11                              # the engine has seen steps of 0.11 A
    sim = loupmd.Simulation(_salt(), ff, integrator=LANGEVIN, skin="auto", seed=1,
                            output=Output(str(tmp_path / "run"), thermo_every=20, trajectory_every=None))
    assert sim.skin == 0.5 and sim.skin_record == {"mode": "auto", "estimated_A": 0.5, "measured_step_A": None,
                                                   "skin_A": 0.5}
    sim.run(steps=190)
    engine, = SpringEngine.made
    assert engine.skins == [0.5] and sim.skin_record["measured_step_A"] is None       # too few steps
    sim.run(steps=30)                                          # 220: past 200, and a thermo step
    assert engine.skins == [0.5, 1.1] and sim.skin == 1.1
    assert sim.skin_record == {"mode": "auto", "estimated_A": 0.5, "measured_step_A": 0.11, "measured_at_step": 220,
                               "skin_A": 1.1}
    assert engine.log[-1] == "import_state" and engine.total_steps == 220
    SpringEngine.step_disp = 0.3
    sim.run(steps=400)                                         # one correction only
    assert engine.skins == [0.5, 1.1] and engine.total_steps == 620
    rows = output.read_thermo(tmp_path / "run")[1]
    assert [int(row[0]) for row in rows] == list(range(0, 621, 20))               # rows stayed on the cadence


def test_a_measurement_that_fits_changes_nothing_and_fixed_atoms_stay_fixed(ff):
    from ase.constraints import FixAtoms

    SpringEngine.step_disp = 0.03
    atoms = _salt()
    atoms.set_constraint(FixAtoms(indices=[0, 1]))
    sim = loupmd.Simulation(atoms, ff, integrator=LANGEVIN, skin="auto")
    sim.run(steps=300)
    engine, = SpringEngine.made
    assert engine.skins == [0.5] and sim.skin_record["measured_step_A"] == 0.03 and "import_state" not in engine.log
    SpringEngine.made, SpringEngine.step_disp = [], 0.09
    sim = loupmd.Simulation(atoms, ff, integrator=LANGEVIN, skin="auto")
    sim.run(steps=300)
    engine, = SpringEngine.made
    assert engine.skins == [0.5, 0.9] and engine.log.count(("fixed", 2)) == 2          # set again with the system


def test_a_heating_schedule_is_estimated_at_its_highest_target_and_measured_there(ff):
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    hydrogen = _salt(temperature=None)
    hydrogen.set_masses([1.008] * len(hydrogen))               # light atoms, so that the estimate matters
    MaxwellBoltzmannDistribution(hydrogen, temperature_K=10.0, rng=np.random.default_rng(2))
    record = integrators.Langevin(timestep_fs=1.0, temperature_K=10.0, friction_per_fs=0.01)
    sim = loupmd.Simulation(hydrogen, ff, integrator=record, skin="auto")
    assert sim.skin == 0.5                                     # at 10 K
    SpringEngine.step_disp = 0.02                              # what a cold start measures
    sim.run(schedule=protocols.ramp(10, 600, ps=0.4) + protocols.hold(600, ps=0.3))
    engine, = SpringEngine.made
    # 5 sqrt(k 600 K / m_H) x 1 fs = 0.111 A: 1.15 A from the start. The measurement waited for 480 K (step 319).
    assert engine.skins[0] == 1.15 and sim.skin_record["estimated_A"] == 1.15
    assert sim.skin_record["measured_at_step"] >= 319 and engine.skins == [1.15, 0.5]


def test_lm_md_and_the_drop_ins_choose_the_skin_themselves(ff, tmp_path):
    SpringEngine.step_disp = 0.07
    result = loupmd.md(_salt(), model=ff, temperature_K=300, steps=240, timestep_fs=1.0, seed=3,
                       output=str(tmp_path / "run"))
    assert result.metadata["skin_A"] == 0.7 and result.metadata["arguments"]["skin"] == "auto"
    assert result.metadata["skin"] == {"mode": "auto", "estimated_A": 0.5, "measured_step_A": 0.07,
                                       "measured_at_step": 200, "skin_A": 0.7}      # the first chunk end past 200
    assert "neighbour skin 0.7 A (auto: largest step measured 0.070 A)" in result.summary
    short = loupmd.md(_salt(), model=ff, temperature_K=300, steps=40, timestep_fs=1.0, output=str(tmp_path / "short"))
    assert "neighbour skin 0.5 A (auto: estimated; too few steps for a measurement)" in short.summary
    fixed = loupmd.md(_salt(), model=ff, temperature_K=300, steps=240, timestep_fs=1.0, skin=0.8,
                      output=str(tmp_path / "fixed"))
    assert fixed.metadata["skin"] == {"mode": "fixed", "skin_A": 0.8} and "neighbour skin" not in fixed.summary
    with pytest.raises(InputError, match="skin must be a length in A"):
        loupmd.md(_salt(), model=ff, temperature_K=300, steps=10, skin="wide")
    from loupmd.ase import md as ase_md

    dyn = ase_md.Langevin(_salt(), units.fs, temperature_K=300, friction=0.01 / units.fs, model=ff)
    assert dyn.simulation.skin_record["mode"] == "auto"
