"""Tiled MD (plan task S5-T06): the tiled call keeps its plan, tile lists and state between calls until an atom has
moved skin/2, and a constant-energy run on the tiled call conserves energy. Every test creates engines and skips
when its model file is absent."""
from __future__ import annotations

import gc

import numpy as np
import pytest
from gpu_support import find_model, maxwell_velocities, srtio3, unfolded

from loupmd import LoupEngine, _core, capacity, ensure_loup_bundle
from loupmd.config import CapacityConfig

SKIN = 0.5


def _bundle():
    return ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])


def _whole(bundle, at, positions, cell=None):
    eng = LoupEngine(bundle)
    try:
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=SKIN)
        return eng.evaluate(positions, at.cell.array if cell is None else cell)
    finally:
        del eng
        gc.collect()


@pytest.mark.full
def test_kept_lists_give_the_whole_system_result_until_an_atom_moves_half_the_skin(monkeypatch):
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")     # the plan's bounds against the whole-system call (D60)
    at = srtio3(8)
    rng = np.random.default_rng(8)
    at.positions += rng.normal(scale=0.03, size=at.positions.shape)
    bundle = _bundle()
    n, z, cell = len(at), at.numbers, at.cell.array
    moved = at.positions + rng.uniform(-0.06, 0.06, size=at.positions.shape)        # under skin/2 for every atom
    jumped = moved.copy()
    jumped[17] += [0.2, 0.2, 0.0]                                                     # 0.28 A: over skin/2
    eng = LoupEngine(bundle)
    try:
        eng.evaluate_tiled(z, at.positions, cell, 1000, skin=SKIN)
        first = eng.last_execution()
        e1, f1, s1, tiles = eng.evaluate_tiled(z, moved, cell, 1000, skin=SKIN)
        kept = eng.last_execution()
        e2, f2, s2, _ = eng.evaluate_tiled(z, jumped, cell, 0, skin=SKIN)              # 0: the kept cap
        rebuilt = eng.last_execution()
    finally:
        del eng
        gc.collect()
    assert tiles >= 3 and not first.lists_kept
    assert kept.lists_kept and kept.list_builds == first.list_builds
    assert not rebuilt.lists_kept and rebuilt.list_builds == first.list_builds + 1 and rebuilt.receivers == 1000
    for (e, f, s), pos in (((e1, f1, s1), moved), ((e2, f2, s2), jumped)):
        with unfolded():                          # the tiles run without the skip-chain fold (gpu_support.unfolded)
            e0, f0, s0 = _whole(bundle, at, pos)
        assert abs(e - e0) / n <= 1e-7
        assert np.abs(f - f0).max() <= 1e-5
        assert np.abs(s - s0).max() <= 1e-8


def _tiled_md_engine(bundle, at, cap):
    eng = LoupEngine(bundle)
    eng.set_execution(_core.LOUP_EXEC_TILED, cap, 0.9)
    eng.tiled_set_state(at.numbers, at.get_masses(), at.positions, at.get_velocities(), at.cell.array, receivers=cap,
                        skin=SKIN)
    return eng


@pytest.mark.full
def test_an_output_evaluation_between_tiled_run_blocks_keeps_the_lists_and_the_trajectory():
    """LAMMPS's run style in tiled mode (LAMMPS_TILED_PLAN.md LD6) evaluates with stress at an output step between
    two blocks of loup_tiled_run (loup_evaluate_tiled on the device's positions, with the run's cap) and sends the
    state again at the next run command (loup_tiled_set_state, same positions): neither builds tile lists, the
    evaluation gives the run's own energy and forces, and the trajectory is that of the unbroken run."""
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    bundle, cap, n = _bundle(), 2000, len(at)
    csvr = _core.integrator(_core.LOUP_CSVR, 1.0, temp_k=300.0, tau_t_fs=50.0, seed=5)
    eng = _tiled_md_engine(bundle, at, cap)
    try:
        eng.tiled_run(20, csvr)
        x_ref = eng.tiled_get_state()[0]
        builds_ref = eng.last_execution().list_builds
    finally:
        del eng
        gc.collect()
    eng = _tiled_md_engine(bundle, at, cap)
    try:
        eng.tiled_run(10, csvr)
        builds = eng.last_execution().list_builds
        pos, vel, frc, e_md, step, ist, kind = eng.tiled_get_state()
        e, f, s, tiles = eng.evaluate_tiled(at.numbers, pos, at.cell.array, cap, skin=SKIN)
        out = eng.last_execution()
        eng.tiled_set_state(at.numbers, at.get_masses(), pos, vel, at.cell.array, receivers=cap, skin=SKIN,
                            noise_step=step, int_state=ist, int_state_kind=kind)
        eng.tiled_run(10, csvr)
        x = eng.tiled_get_state()[0]
        after = eng.last_execution()
    finally:
        del eng
        gc.collect()
    dx = np.abs(x - x_ref).max()
    print(f"tiled CSVR, output evaluation and state sent again after 10 of 20 steps: {tiles} tiles, dx {dx:.2e} A, "
          f"list builds {after.list_builds} (unbroken {builds_ref})")
    assert tiles >= 3 and s is not None and out.receivers == cap
    assert out.lists_kept and out.list_builds == builds
    assert abs(e - e_md) / n <= 1e-7 and np.abs(f - frc).max() <= 1e-5
    assert after.list_builds == builds_ref
    assert dx <= 1e-6


@pytest.mark.full
def test_a_strained_cell_keeps_the_tile_lists_and_gives_the_whole_systems_result(monkeypatch):
    """LAMMPS_TILED_PLAN.md LT6 (a): a cell change keeps the tile lists while the strain since their build leaves
    room for the atoms' moves (the strained displacement test, which ignores a uniform translation: LAMMPS's fix npt
    dilates about the box centre), and the results are the whole call's at the new cell. Beyond that room the lists
    are built again, with the cap passed."""
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = srtio3(8)
    rng = np.random.default_rng(21)
    at.positions += rng.normal(scale=0.03, size=at.positions.shape)
    bundle = _bundle()
    n, z, cell = len(at), at.numbers, at.cell.array
    shear = np.eye(3) + np.array([[0.002, 0.001, 0.0], [0.0, -0.001, 0.0], [0.0015, 0.0, 0.001]])
    shift = np.array([0.4, -0.3, 0.25])
    cases = {}
    eng = LoupEngine(bundle)
    try:
        eng.evaluate_tiled(z, at.positions, cell, 1000, skin=SKIN)
        first = eng.last_execution()
        for name, f in (("dilated", np.eye(3) * 1.003), ("sheared", shear)):   # both against the lists' build
            pos = at.positions @ f + shift + rng.uniform(-0.04, 0.04, size=at.positions.shape)
            e, frc, s, tiles = eng.evaluate_tiled(z, pos, cell @ f, 1000, skin=SKIN)
            cases[name] = (pos, cell @ f, e, frc, s, eng.last_execution())
        eng.evaluate_tiled(z, at.positions * 1.05, cell * 1.05, 1000, skin=SKIN)
        rebuilt = eng.last_execution()
    finally:
        del eng
        gc.collect()
    assert tiles >= 3 and not first.lists_kept
    for name, (pos, c, e, frc, s, done) in cases.items():
        with unfolded():
            e0, f0, s0 = _whole(bundle, at, pos, c)
        print(f"{name} cell, kept lists: dE {abs(e - e0) / n:.2e} eV/atom, dF {np.abs(frc - f0).max():.2e} eV/A, "
              f"dS {np.abs(s - s0).max():.2e}")
        assert done.lists_kept and done.list_builds == first.list_builds and done.receivers == 1000
        assert abs(e - e0) / n <= 1e-7
        assert np.abs(frc - f0).max() <= 1e-5
        assert np.abs(s - s0).max() <= 1e-8
    assert not rebuilt.lists_kept and rebuilt.list_builds == first.list_builds + 1 and rebuilt.receivers == 1000


@pytest.mark.full
def test_a_tiled_call_after_a_cell_change_keeps_a_passed_cap_and_plans_on_zero():
    """A cell change within the lists' room keeps them and their cap, whatever receivers says (LT6 (a)). Beyond it a
    passed cap stays and receivers 0 plans again (LAMMPS_TILED_PLAN.md LD3), so a caller whose cell changes much
    passes its cap."""
    at = srtio3(10)
    bundle, cap = _bundle(), 2000
    z, cell = at.numbers, at.cell.array
    eng = LoupEngine(bundle)
    try:
        eng.evaluate_tiled(z, at.positions, cell, cap, skin=SKIN)
        first = eng.last_execution()
        eng.evaluate_tiled(z, at.positions * 1.002, cell * 1.002, 0, skin=SKIN)
        strained = eng.last_execution()
        eng.evaluate_tiled(z, at.positions * 1.05, cell * 1.05, cap, skin=SKIN)
        passed = eng.last_execution()
        eng.evaluate_tiled(z, at.positions * 1.10, cell * 1.10, 0, skin=SKIN)
        planned = eng.last_execution()
        eng.evaluate_tiled(z, at.positions * 1.10 + 0.01, cell * 1.10, 0, skin=SKIN)
        kept = eng.last_execution()
    finally:
        del eng
        gc.collect()
    print(f"caps: first {first.receivers}, strained {strained.receivers}, after a large cell change passed "
          f"{passed.receivers}, zero {planned.receivers}")
    assert strained.lists_kept and strained.receivers == cap and strained.list_builds == first.list_builds
    assert first.receivers == passed.receivers == cap and passed.tiles >= 3 and not passed.lists_kept
    assert planned.receivers >= 4096 and not planned.lists_kept
    assert kept.lists_kept and kept.receivers == planned.receivers


@pytest.mark.full
def test_a_tiled_constant_energy_run_conserves_energy():
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=4))
    eng = LoupEngine(_bundle())
    try:
        res = capacity.run_nve(eng, at, n_steps=400, dt_fs=1.0,
                               config=CapacityConfig(mode="tiled", receivers=2000), skin=SKIN, every=10)
    finally:
        del eng
        gc.collect()
    drift = res.drift_mev_per_atom_ps(len(at))
    print(f"tiled NVE: {len(at)} atoms, {res.tiles} tiles of <= {res.receivers}, {res.list_builds} list builds in "
          f"400 steps, {res.seconds_per_step * 1e3:.1f} ms per step, drift {drift:.4f} meV/atom/ps, total energy "
          f"spread {np.ptp(res.total) / len(at) * 1e3:.4f} meV/atom")
    assert res.mode == "tiled" and res.tiles >= 3
    assert res.list_builds >= 2               # 300 K moves some atom skin/2 within 0.4 ps
    assert abs(drift) < 0.05


# ------------------------------------------------------------------------- the front end (plan task S5-T12)

@pytest.mark.full
def test_a_tiled_simulation_follows_the_whole_systems_nve_trajectory(monkeypatch):
    """lm.Simulation with capacity 'tiled' (TiledEngine, its device loop) against the device loop on the whole
    system, without hybrids: 20 steps of 1 fs from 300 K stay together to float32 force rounding."""
    import loupmd
    from loupmd import integrators

    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=6))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    nve = integrators.NVE(timestep_fs=1.0, fixcm=False)
    sims = {}
    for name, cap in (("whole", "whole"), ("tiled", CapacityConfig(mode="tiled", receivers=2000))):
        sim = loupmd.Simulation(at, ff, integrator=nve, seed=1, skin=SKIN, capacity=cap)
        sim.run(steps=20)
        sims[name] = (sim.execution["mode"], sim.atoms)
        sim.close()
        del sim
        gc.collect()
    (mode_w, whole), (mode_t, tiled) = sims["whole"], sims["tiled"]
    dx = np.abs(tiled.positions - whole.positions).max()
    de = abs(tiled.get_potential_energy() - whole.get_potential_energy()) / len(at)
    print(f"tiled Simulation vs whole, 20 NVE steps: dx {dx:.2e} A, dE {de:.2e} eV/atom")
    assert (mode_w, mode_t) == ("whole", "tiled")
    assert dx <= 1e-5 and de <= 1e-6


@pytest.mark.full
def test_a_wavefront_simulation_follows_the_whole_systems_nve_trajectory(monkeypatch):
    """S5-T08: lm.Simulation with capacity 'wavefront' on a rod (13 layers of tiles), without hybrids: 20 steps of
    1 fs from 300 K stay with the whole-system device loop to float32 force rounding, and the wavefront ran."""
    import loupmd
    from loupmd import integrators

    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = srtio3(1).repeat((64, 6, 6))                 # 11,520 atoms
    at.set_velocities(maxwell_velocities(at, 300.0, seed=7))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    nve = integrators.NVE(timestep_fs=1.0, fixcm=False)
    sims = {}
    for name, cap in (("whole", "whole"), ("wavefront", CapacityConfig(mode="wavefront", receivers=600))):
        sim = loupmd.Simulation(at, ff, integrator=nve, seed=1, skin=SKIN, capacity=cap)
        sim.run(steps=20)
        sims[name] = (sim.execution["mode"], getattr(sim._engine, "wavefront", False),
                      getattr(sim._engine, "tiles", 1), sim.atoms)
        sim.close()
        del sim
        gc.collect()
    (_, _, _, whole), (mode, ran, tiles, wave) = sims["whole"], sims["wavefront"]
    dx = np.abs(wave.positions - whole.positions).max()
    de = abs(wave.get_potential_energy() - whole.get_potential_energy()) / len(at)
    print(f"wavefront Simulation vs whole, 20 NVE steps: {tiles} tiles, dx {dx:.2e} A, dE {de:.2e} eV/atom")
    assert mode == "wavefront" and ran and tiles >= 13
    assert dx <= 1e-5 and de <= 1e-6


@pytest.mark.full
def test_tiled_langevin_heats_toward_its_target():
    import loupmd
    from loupmd import integrators

    at = srtio3(10)                                   # 5,000 atoms at rest, 3 tiles
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    lang = integrators.Langevin(timestep_fs=2.0, temperature_K=300.0, friction_per_fs=0.05)
    sim = loupmd.Simulation(at, ff, integrator=lang, seed=3, skin=SKIN,
                            capacity=CapacityConfig(mode="tiled", receivers=2000))
    try:
        summary = sim.run(steps=200)
        tiles = sim._engine.tiles
    finally:
        sim.close()
        del sim
        gc.collect()
    print(f"tiled Langevin: {tiles} tiles, {summary.ms_per_step:.1f} ms per step, final {summary.final_temperature_K:.1f} K")
    assert tiles >= 3 and 200.0 <= summary.final_temperature_K <= 400.0


@pytest.mark.full
def test_loupmd_md_capacity_auto_tiles_a_cell_that_does_not_fit_and_says_so(tmp_path, monkeypatch, capsys):
    """S5-T12's acceptance: `loupmd md --capacity auto` on 320,000 atoms (32 GiB whole on the plan's count) runs in
    tiles on a 16 GB card and the report says so."""
    from ase.io import write

    from loupmd.cli import main

    big = srtio3(40)
    write(tmp_path / "big.extxyz", big)
    monkeypatch.chdir(tmp_path)
    code = main(["md", "big.extxyz", "--model", find_model("mace-omat-0-medium.model"), "--trusted",
                 "--temperature", "300", "--steps", "10", "--timestep", "1", "--seed", "1", "--initial-velocities",
                 "maxwell_boltzmann", "--skin", str(SKIN), "--capacity", "auto", "--thermo-every", "5",
                 "--trajectory-every", "0", "--output", "run"])
    out = capsys.readouterr().out
    print(out)
    import json

    plan = json.loads((tmp_path / "run" / "metadata.json").read_text())["plan"]
    if plan["execution"] == "whole":
        pytest.skip("this GPU runs 320,000 atoms whole")
    assert code == 0
    assert plan["execution"] == "tiled" and 4096 <= plan["receivers"] <= 65536
    assert "tiles of at most" in out and "the integrator runs on the device" in out


# ------------------------------------------------------------------------- the device loop (PLAN.md O31)

def _pair(at, integrator, steps, caps, env=None, monkeypatch=None):
    """The same run under each capacity of ``caps`` (name -> (capacity, environment)); positions, velocities,
    potential energy and the engine's integrator place of each."""
    import loupmd

    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    out = {}
    for name, (cap, extra) in caps.items():
        for k, v in (extra or {}).items():
            monkeypatch.setenv(k, v)
        sim = loupmd.Simulation(at, ff, integrator=integrator, seed=5, skin=SKIN, capacity=cap)
        sim.run(steps=steps)
        out[name] = (sim.atoms.positions.copy(), sim.atoms.get_velocities().copy(),
                     sim.atoms.get_potential_energy(), getattr(sim._engine, "integrator_on", "whole"))
        sim.close()
        del sim
        gc.collect()
        for k in (extra or {}):
            monkeypatch.delenv(k)
    return out


@pytest.mark.full
def test_the_tiled_device_loop_follows_the_whole_systems_thermostat_trajectories(monkeypatch):
    """The device loop of the tiled mode runs the whole-system kernels. CSVR (one global noise draw per step, the
    same stream), the Nose-Hoover chain and Berendsen follow the whole system's trajectory to float32 force rounding.
    (Langevin draws per device row, and the whole system's rows are sorted by species: same statistics, another
    trajectory; see the next test.)"""
    from loupmd import integrators

    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=6))
    tiled = CapacityConfig(mode="tiled", receivers=2000)
    for it in (integrators.CSVR(timestep_fs=1.0, temperature_K=300.0, tau_fs=50.0),
               integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=300.0, tdamp_fs=50.0),
               integrators.Berendsen(timestep_fs=1.0, temperature_K=300.0, taut_fs=50.0)):
        runs = _pair(at, it, 20, {"whole": ("whole", None), "tiled": (tiled, None)}, monkeypatch=monkeypatch)
        (xw, vw, ew, _), (xt, vt, et, on) = runs["whole"], runs["tiled"]
        dx, dv = np.abs(xt - xw).max(), np.abs(vt - vw).max()
        de = abs(et - ew) / len(at)
        print(f"tiled device loop vs whole, {type(it).__name__} 20 steps: dx {dx:.2e} A, dv {dv:.2e}, "
              f"dE {de:.2e} eV/atom")
        assert on == "device"
        assert dx <= 1e-5 and de <= 1e-6


@pytest.mark.full
def test_the_tiled_device_loop_and_the_host_loop_agree_on_nve(monkeypatch):
    from loupmd import integrators

    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=8))
    tiled = CapacityConfig(mode="tiled", receivers=2000)
    runs = _pair(at, integrators.NVE(timestep_fs=1.0, fixcm=False), 20,
                 {"device": (tiled, None), "host": (tiled, {"LOUP_TILED_HOST_MD": "1"})}, monkeypatch=monkeypatch)
    (xd, _, ed, on_d), (xh, _, eh, on_h) = runs["device"], runs["host"]
    print(f"tiled NVE device vs host loop, 20 steps: dx {np.abs(xd - xh).max():.2e} A")
    assert (on_d, on_h) == ("device", "host")
    assert np.abs(xd - xh).max() <= 1e-6 and abs(ed - eh) / len(at) <= 1e-7     # summation order only


@pytest.mark.full
def test_tiled_device_langevin_holds_the_centre_of_mass_and_its_target():
    import loupmd
    from loupmd import integrators

    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=3))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    lang = integrators.Langevin(timestep_fs=2.0, temperature_K=300.0, friction_per_fs=0.05, fixcm=True)
    sim = loupmd.Simulation(at, ff, integrator=lang, seed=4, skin=SKIN,
                            capacity=CapacityConfig(mode="tiled", receivers=2000))
    try:
        sim.run(steps=100)
        temps = [sim.run(steps=20).final_temperature_K for _ in range(10)]
        p = (sim.atoms.get_masses()[:, None] * sim.atoms.get_velocities()).sum(axis=0)
        on = sim._engine.integrator_on
    finally:
        sim.close()
        del sim
        gc.collect()
    print(f"tiled device Langevin: mean {np.mean(temps):.1f} K, total momentum {np.abs(p).max():.2e}")
    assert on == "device"
    assert abs(np.mean(temps) / 300.0 - 1.0) < 0.05 and np.abs(p).max() < 1e-8


@pytest.mark.full
def test_a_tiled_device_run_resumes_where_it_stopped(tmp_path):
    """A CSVR run in tiles stopped and resumed (state block v2: the thermostat's energy and the noise step) ends
    where the unbroken run ends."""
    import loupmd
    from loupmd import integrators

    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=9))
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    csvr = integrators.CSVR(timestep_fs=1.0, temperature_K=300.0, tau_fs=50.0)
    tiled = CapacityConfig(mode="tiled", receivers=2000)
    full = loupmd.Simulation(at, ff, integrator=csvr, seed=2, skin=SKIN, capacity=tiled,
                             output=loupmd.Output(str(tmp_path / "full")))
    full.run(steps=30)
    x_full = full.atoms.positions.copy()
    full.close()
    half = loupmd.Simulation(at, ff, integrator=csvr, seed=2, skin=SKIN, capacity=tiled,
                             output=loupmd.Output(str(tmp_path / "half")))
    half.run(steps=15)
    half.save_restart()
    half.close()
    again = loupmd.Simulation.resume(tmp_path / "half", force_field=ff)
    again.run(steps=15)
    dx = np.abs(again.atoms.positions - x_full).max()
    again.close()
    gc.collect()
    print(f"tiled CSVR resumed vs unbroken: dx {dx:.2e} A")
    assert dx <= 1e-6        # the resumed engine rebuilds its tile lists: float32 summation order only


# ------------------------------------------------------------------------- barostats (LAMMPS_TILED_PLAN.md LT6 (a))

def _npt_records():
    from loupmd import integrators

    return (integrators.MTK(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=2.0, tdamp_fs=50.0, pdamp_fs=200.0),
            integrators.LangevinBAOAB(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.02, pressure_GPa=2.0,
                                      barostat_tau_fs=200.0, cell_mode="full"),
            integrators.Berendsen(timestep_fs=1.0, temperature_K=300.0, taut_fs=50.0, pressure_GPa=2.0, taup_fs=50.0,
                                  compressibility_per_GPa=0.01))


def _sorted_srtio3():
    """SrTiO3 10 x 10 x 10 (5,000 atoms) with its atoms in species order: the whole system's rows are sorted by
    species, and the device loop's noise is drawn per row, so in this order Langevin BAOAB draws the same noise in
    both modes."""
    at = srtio3(10)
    at = at[np.argsort(at.numbers, kind="stable")]
    at.set_velocities(maxwell_velocities(at, 300.0, seed=14))
    return at


@pytest.mark.full
def test_the_tiled_barostats_follow_the_whole_systems_trajectories(monkeypatch):
    """lm.Simulation in tiles (the device loop) against the whole system for MTK, Langevin BAOAB (full cell) and
    Berendsen NPT, without hybrids: 20 steps of 1 fs at 2 GPa move the cell, and positions, cell and energy stay
    with the whole system's to float32 force rounding."""
    import loupmd

    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    at = _sorted_srtio3()
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    tiled = CapacityConfig(mode="tiled", receivers=2000)
    for it in _npt_records():
        out = {}
        for name, cap in (("whole", "whole"), ("tiled", tiled)):
            sim = loupmd.Simulation(at, ff, integrator=it, seed=5, skin=SKIN, capacity=cap)
            sim.run(steps=20)
            got = sim.atoms
            out[name] = (got.positions.copy(), got.cell.array.copy(), got.get_potential_energy(),
                         getattr(sim._engine, "integrator_on", "whole"), getattr(sim._engine, "tiles", 1))
            sim.close()
            del sim
            gc.collect()
        (xw, cw, ew, _, _), (xt, ct, et, on, tiles) = out["whole"], out["tiled"]
        dx, dc, de = np.abs(xt - xw).max(), np.abs(ct - cw).max(), abs(et - ew) / len(at)
        moved = np.abs(cw - at.cell.array).max()
        print(f"tiled vs whole, {type(it).__name__} 20 steps at 2 GPa: {tiles} tiles, cell moved {moved:.2e} A, "
              f"dx {dx:.2e} A, dcell {dc:.2e} A, dE {de:.2e} eV/atom")
        assert on == "device" and tiles >= 3
        assert moved > 1e-4
        assert dx <= 1e-5 and dc <= 1e-6 and de <= 1e-6


@pytest.mark.full
def test_a_tiled_barostat_run_in_blocks_and_resumed_ends_where_the_unbroken_run_ends(tmp_path):
    """MTK in tiles: 30 steps in one block, in blocks of 10 (the device keeps the virial and the barostat's variables
    between blocks), and 15 steps resumed from a restart after 15 (state block: cell, chains, cell velocity; the
    run's V0) end at the same positions and cell."""
    import loupmd

    at = _sorted_srtio3()
    ff = loupmd.load(find_model("mace-omat-0-medium.model"), trusted=True)
    mtk = _npt_records()[0]
    tiled = CapacityConfig(mode="tiled", receivers=2000)

    def end(sim):
        got = sim.atoms
        out = got.positions.copy(), got.cell.array.copy()
        sim.close()
        gc.collect()
        return out

    full = loupmd.Simulation(at, ff, integrator=mtk, seed=2, skin=SKIN, capacity=tiled)
    full.run(steps=30)
    x_full, c_full = end(full)
    blocks = loupmd.Simulation(at, ff, integrator=mtk, seed=2, skin=SKIN, capacity=tiled)
    for _ in range(3):
        blocks.run(steps=10)
    x_blocks, c_blocks = end(blocks)
    half = loupmd.Simulation(at, ff, integrator=mtk, seed=2, skin=SKIN, capacity=tiled,
                             output=loupmd.Output(str(tmp_path / "half")))
    half.run(steps=15)
    half.save_restart()
    half.close()
    again = loupmd.Simulation.resume(tmp_path / "half", force_field=ff)
    again.run(steps=15)
    x_again, c_again = end(again)
    for name, x, c in (("blocks", x_blocks, c_blocks), ("resumed", x_again, c_again)):
        print(f"tiled MTK {name} vs unbroken: dx {np.abs(x - x_full).max():.2e} A, "
              f"dcell {np.abs(c - c_full).max():.2e} A")
        # the force sums' order differs from call to call (atomics), and a resumed state rebuilds its tile lists
        assert np.abs(c - c_full).max() <= 1e-6
        assert np.abs(x - x_full).max() <= 1e-6
    assert np.abs(c_full - at.cell.array).max() > 1e-4


@pytest.mark.full
def test_a_tiled_barostat_stops_at_the_volume_limits():
    """A Berendsen barostat driven far past the limits [V0 / 20, 20 V0] stops the tiled run with the reason."""
    from loupmd import BackendError

    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=12))
    eng = _tiled_md_engine(_bundle(), at, 2000)
    blow_up = _core.integrator(_core.LOUP_BERENDSEN_NPT, 1.0, temp_k=300.0, tau_t_fs=50.0, pressure_gpa=-1000.0,
                               tau_p_fs=1.0, compressibility_per_gpa=1.0)
    try:
        with pytest.raises(BackendError, match=r"the cell diverged: its volume is .* outside \[V0 / 20, 20 V0\]"):
            eng.tiled_run(5, blow_up)
    finally:
        del eng
        gc.collect()
