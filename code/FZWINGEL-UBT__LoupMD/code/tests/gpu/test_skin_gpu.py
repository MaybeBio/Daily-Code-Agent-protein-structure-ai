"""``skin="auto"`` on the GPU (owner's decision O17): the engine reports its largest per-step displacement, and
with the skin chosen from it liquid water runs in the pipelined loop, which it cannot at the default 0.5 A."""
from __future__ import annotations

import numpy as np
from ase import units
from ase.io import read
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from gpu_support import find_model, maxwell_velocities, srtio3

import loupmd
from loupmd import _core, integrators
from loupmd.bench import suites


def test_the_engine_reports_its_largest_step(sto_engine):
    eng = sto_engine
    at = srtio3(3)
    at.positions += np.random.default_rng(5).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    velocities = maxwell_velocities(at, 300.0, 5)
    eng.set_state(at.positions, velocities, at.cell.array)
    assert eng.step_displacement() == 0.0                           # nothing has moved yet
    eng.run(60, _core.integrator(_core.LOUP_NVE, 1.0))
    fastest = float(np.sqrt((velocities ** 2).sum(axis=1).max())) * units.fs
    measured = eng.step_displacement()
    print(f"largest step of 60 NVE steps: {measured:.4f} A; the fastest atom at the start moves {fastest:.4f} A a step")
    assert 0.6 * fastest < measured < 2.0 * fastest
    eng.set_state(at.positions, velocities, at.cell.array)
    assert eng.step_displacement() == 0.0                           # a new state starts the tracker anew


def test_auto_lets_water_run_in_the_pipelined_loop():
    model = find_model("MACE-OFF23_small.model")
    water = read(suites.find_file("water_216.extxyz", {}))          # the shipped box: 648 atoms
    MaxwellBoltzmannDistribution(water, temperature_K=300.0, rng=np.random.default_rng(3))
    record = integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01)

    def run(skin):
        sim = loupmd.Simulation(water, loupmd.load(model, trusted=True), integrator=record, seed=1, skin=skin)
        sim.run(steps=400)                                          # past the measurement of "auto"
        summary = sim.run(steps=800)
        sim.close()
        return sim, summary

    fixed_sim, fixed = run(0.5)
    auto_sim, auto = run("auto")
    record_ = auto_sim.skin_record
    print(f"water 216 at 300 K, 1 fs: skin 0.5 A: {fixed.pipelined_steps} of 800 steps pipelined, "
          f"{fixed.ms_per_step:.3f} ms/step; auto: estimated {record_['estimated_A']} A, largest step "
          f"{record_['measured_step_A']:.3f} A, skin {record_['skin_A']} A: {auto.pipelined_steps} of 800 pipelined, "
          f"{auto.ms_per_step:.3f} ms/step")
    assert record_["mode"] == "auto" and record_["measured_step_A"] > 0.05 and auto_sim.skin >= 0.8
    # Since the round6 merge every step is checked on the device and most rebuilds run there too, so the skin no
    # longer decides whether a step is pipelined; the larger automatic skin still rebuilds less often.
    assert auto.pipelined_steps > 600 and auto.rebuilds < fixed.rebuilds, (auto.rebuilds, fixed.rebuilds)
    assert auto.dangerous_builds == 0 and fixed.dangerous_builds == 0
