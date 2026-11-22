"""Events on ``Simulation`` (plan task S6-T01) on the real engine: a species change within the bundle gives the
energy of a fresh evaluation of the changed structure without an export, and its cost is printed (S6-T03 records
it). Skips when the model file is absent."""
from __future__ import annotations

import gc
import time

import numpy as np
import pytest
from gpu_support import find_model, maxwell_velocities, srtio3

import loupmd
from loupmd import integrators


@pytest.mark.full
def test_set_species_matches_a_fresh_evaluation_and_the_run_goes_on():
    at = srtio3(6)                                        # 1,080 atoms
    at.set_velocities(maxwell_velocities(at, 300.0, seed=2))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    sim = loupmd.Simulation(at, ff, integrator=integrators.NVE(timestep_fs=1.0), seed=1, capacity="whole")
    try:
        sim.run(steps=10)
        bundle = sim._bundle
        numbers = sim.atoms.numbers.copy()
        sr, ti = np.flatnonzero(numbers == 38)[0], np.flatnonzero(numbers == 22)[0]
        numbers[[sr, ti]] = numbers[[ti, sr]]             # a swap of two cations' species
        started = time.perf_counter()
        sim.set_species(numbers)
        event_ms = (time.perf_counter() - started) * 1e3
        changed = sim.atoms
        assert sim._bundle == bundle                      # no export, the same bundle
        e_event = changed.get_potential_energy()
        fresh = changed.copy()
        fresh.calc = loupmd.calc(ff)
        e_fresh = fresh.get_potential_energy()
        started = time.perf_counter()
        sim.run(steps=10)
        run_ms = (time.perf_counter() - started) * 1e3
        print(f"set_species on {len(at)} atoms: {event_ms:.1f} ms for the event, then 10 steps in {run_ms:.1f} ms "
              f"(with the re-capture); dE against a fresh evaluation {abs(e_event - e_fresh):.2e} eV")
        assert abs(e_event - e_fresh) <= 1e-6 * len(at)
        assert np.isfinite(sim.atoms.get_potential_energy())
    finally:
        sim.close()
        del sim
        gc.collect()


# ------------------------------------------------------------------------- Monte Carlo swaps (S6-T02)

def _cu3au(rep=4, seed=0):
    from ase.build import bulk

    at = bulk("Cu", "fcc", a=3.75, cubic=True).repeat((rep, rep, rep))
    rng = np.random.default_rng(seed)
    numbers = at.numbers.copy()
    numbers[rng.choice(len(at), len(at) // 4, replace=False)] = 79
    at.numbers = numbers
    at.positions += rng.normal(0.0, 0.03, at.positions.shape)
    return at


@pytest.mark.full
def test_swap_move_energies_agree_with_the_full_call_and_a_block_runs():
    """The energy-only pass of a swapped configuration against the full call's energy, to 0.01 k_B T at 300 K;
    then a block of swaps on a Simulation, whose run goes on. The time per attempt is printed."""
    from ase import units

    from loupmd import mc

    at = _cu3au()
    at.set_velocities(maxwell_velocities(at, 300.0, seed=4))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    sim = loupmd.Simulation(at, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=300.0,
                                                                    friction_per_fs=0.01),
                            seed=1, capacity="whole")
    try:
        sim.run(steps=10)
        engine = sim._engine
        positions, _, _, _ = engine.get_state()
        cell = at.cell.array
        cu, au = np.flatnonzero(at.numbers == 29), np.flatnonzero(at.numbers == 79)
        rng = np.random.default_rng(3)
        worst = 0.0
        for _ in range(10):
            i, j = rng.choice(cu), rng.choice(au)
            trial = positions.copy()
            trial[[i, j]] = positions[[j, i]]
            e_only = engine.evaluate_energy(trial, cell)
            e_full, _, _ = engine.evaluate(trial, cell, compute_stress=False)
            worst = max(worst, abs(e_only - e_full))
        kT = units.kB * 300.0
        engine.evaluate(positions, cell, compute_stress=False)      # the device positions back to the run's
        started = time.perf_counter()
        result = mc.swap(sim, mc.Swap(pairs=[("Cu", "Au")], attempts=200), seed=5)
        per_attempt_ms = (time.perf_counter() - started) * 1e3 / 200
        print(f"swap on {len(at)} atoms: move energies within {worst:.2e} eV of the full call ({worst / kT:.2e} kT); "
              f"200 attempts, {result.counters.accepted} accepted, {per_attempt_ms:.2f} ms per attempt")
        assert worst <= 0.01 * kT
        assert result.counters.attempted == 200
        sim.run(steps=10)
        assert np.isfinite(sim.atoms.get_potential_energy())
    finally:
        sim.close()
        del sim
        gc.collect()


@pytest.mark.full
def test_transmute_records_its_setup_cost_and_its_energy_matches_a_fresh_evaluation():
    """S6-T03: transmute attempts on Cu3Au set the engine's system per attempt; the re-setup time per attempt is
    printed, and the energy after the block is a fresh evaluation's."""
    from loupmd import mc

    at = _cu3au(seed=1)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=6))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    sim = loupmd.Simulation(at, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=300.0,
                                                                    friction_per_fs=0.01),
                            seed=1, capacity="whole")
    try:
        sim.run(steps=10)
        started = time.perf_counter()
        result = mc.transmute(sim, mc.Transmute(species=["Cu", "Au"], attempts=20), seed=2)
        wall_ms = (time.perf_counter() - started) * 1e3
        c = result.counters
        changed = sim.atoms
        fresh = changed.copy()
        fresh.calc = loupmd.calc(ff)
        e_fresh = fresh.get_potential_energy()
        print(f"transmute on {len(at)} atoms: {c.attempted} attempts, {c.accepted} accepted, "
              f"{c.setup_s * 1e3 / c.attempted:.1f} ms re-setup per attempt, {wall_ms / c.attempted:.1f} ms per "
              f"attempt in all; dE against a fresh evaluation {abs(result.energy_eV - e_fresh):.2e} eV")
        assert c.attempted == 20
        assert abs(result.energy_eV - e_fresh) <= 1e-6 * len(at)
        sim.run(steps=10)
        assert np.isfinite(sim.atoms.get_potential_energy())
    finally:
        sim.close()
        del sim
        gc.collect()
