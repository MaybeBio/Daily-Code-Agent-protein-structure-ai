"""The tiled mode in ``lm.Simulation`` and ``lm.md`` (plan task S5-T12): ``capacity="auto"`` plans the execution and
runs a cell that does not fit in tiles through ``TiledEngine``. On a fake engine whose tiled call is the spring
potential of ``fake_core``, so the tiled run can be compared with the whole one: ``TileSpringEngine`` has no device
loop (the host integrator runs), ``DeviceTileSpringEngine`` fakes ``loup_tiled_run`` (PLAN.md O31) with the same
arithmetic. Needs neither a GPU nor the library."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
from ase.build import bulk
from ase.constraints import FixAtoms
from fake_core import K, SpringEngine

import loupmd
from loupmd import _core, integrators, output, provenance, quick
from loupmd.errors import BackendError, PlanRefused
from loupmd.tiled_engine import TiledEngine


class TileSpringEngine(SpringEngine):
    """SpringEngine with the capacity calls: a system of more than ``tile_from`` atoms does not fit whole."""

    tile_from = 100
    shared_sites = {}

    def set_execution(self, mode, receivers=0, memory_fraction=0.9):
        self.execution = (mode, receivers, memory_fraction)

    def plan_execution(self, numbers, positions, cell, skin=0.5):
        n = len(numbers)
        tiled = n > self.tile_from or self.execution[0] in (_core.LOUP_EXEC_TILED, _core.LOUP_EXEC_WAVEFRONT)
        self.log.append("plan")
        return _core.MemoryPlan(1000 * n, 100 * n, 10 ** 6, 2 ** 34, 64 if tiled else 0,
                                _core.LOUP_EXEC_TILED if tiled else _core.LOUP_EXEC_WHOLE)

    def evaluate_tiled(self, numbers, positions, cell, receivers, skin=0.5, compute_stress=True):
        pos = np.asarray(positions, dtype=float)
        # the springs' sites: the first positions seen for this atom count, by any engine (a resumed run too)
        sites = TileSpringEngine.shared_sites.setdefault(len(numbers), pos.copy())
        self.tiled_calls = getattr(self, "tiled_calls", 0) + 1
        self.receivers_seen = receivers
        d = pos - sites
        cap = receivers or 64
        self.tiles = math.ceil(len(numbers) / cap)
        return 0.5 * K * float((d ** 2).sum()) - 3.0 * len(numbers), -K * d, np.zeros((3, 3)), self.tiles

    def last_execution(self):
        mode = _core.LOUP_EXEC_WAVEFRONT if self.execution[0] == _core.LOUP_EXEC_WAVEFRONT else _core.LOUP_EXEC_TILED
        return _core.Execution(mode, self.receivers_seen or 64, self.tiles, 2 ** 34, 10 ** 6, True, 1)


@pytest.fixture
def ff(tmp_path):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    TileSpringEngine.shared_sites = {}
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=TileSpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


class DeviceTileSpringEngine(TileSpringEngine):
    """TileSpringEngine with a fake device loop: velocity Verlet on the springs (every fixed-cell kind integrates as
    NVE here, and counts its steps in the state block's slot 0, so a restart's block can be checked)."""

    def has_tiled_md(self):
        return True

    def tiled_set_state(self, numbers, masses, positions, velocities, cell, fixed=None, receivers=0, skin=0.5,
                        noise_step=0, int_state=None, int_state_kind=-1):
        self.log.append("tiled_set_state" if positions is not None else "tiled_restart_count")
        if positions is None:
            self.dev["md_steps"] = 0
            return
        self.dev = {"z": np.array(numbers), "m": np.array(masses, dtype=float), "x": np.array(positions, dtype=float),
                    "v": np.array(velocities, dtype=float), "cell": np.array(cell, dtype=float), "f": None,
                    "fixed": None if fixed is None else np.asarray(fixed, dtype=bool), "receivers": receivers,
                    "step": int(noise_step), "md_steps": 0, "e": float("nan"),
                    "ist": np.zeros(64) if int_state is None else np.array(int_state, dtype=float),
                    "kind": int(int_state_kind)}
        if self.dev["fixed"] is not None:
            self.dev["v"][self.dev["fixed"]] = 0.0

    def _dev_forces(self):
        d = self.dev
        d["e"], d["f"], _, _ = self.evaluate_tiled(d["z"], d["x"], d["cell"], d["receivers"])

    def tiled_run(self, n_steps, it, max_rows=0):
        from ase import units

        d = self.dev
        if d["f"] is None:
            self._dev_forces()
        inv_m = 1.0 / d["m"][:, None]
        if d["fixed"] is not None:
            inv_m = np.where(d["fixed"][:, None], 0.0, inv_m)
        dt = it.dt_fs * units.fs
        if d["kind"] != it.kind and it.kind != _core.LOUP_NVE:
            d["ist"][:] = 0.0
            d["kind"] = it.kind
        rows, largest = [], 0.0
        for _ in range(n_steps):
            d["v"] += 0.5 * dt * d["f"] * inv_m
            step = dt * d["v"]
            d["x"] += step
            self._dev_forces()
            d["v"] += 0.5 * dt * d["f"] * inv_m
            d["md_steps"] += 1
            d["step"] += 1
            if it.kind != _core.LOUP_NVE:
                d["ist"][0] += 1.0
            largest = max(largest, float(np.sqrt((step * step).sum(axis=1).max())))
            if it.thermo_every and d["md_steps"] % it.thermo_every == 0 and len(rows) < max_rows:
                e_kin = 0.5 * float((d["m"][:, None] * d["v"] ** 2).sum())
                dof = 3 * len(d["m"])
                rows.append((d["md_steps"], d["e"], e_kin, 2 * e_kin / (dof * units.kB), 0.0,
                             abs(float(np.linalg.det(d["cell"]))), d["e"] + e_kin - d["ist"][0] * 0.0))
        e_kin = 0.5 * float((d["m"][:, None] * d["v"] ** 2).sum())
        st = _core.LoupMDStats()
        st.final_potential_energy_ev = d["e"]
        st.final_kinetic_energy_ev = e_kin
        st.final_temperature_k = 2 * e_kin / (3 * len(d["m"]) * units.kB)
        self.device_steps = getattr(self, "device_steps", 0) + n_steps
        return st, np.array(rows, dtype=_core.THERMO_DTYPE), largest

    def tiled_get_state(self):
        d = self.dev
        if d["f"] is None:
            self._dev_forces()
        self.log.append("tiled_get_state")
        return d["x"].copy(), d["v"].copy(), d["f"].copy(), d["e"], d["step"], d["ist"].copy(), d["kind"]


@pytest.fixture
def ff_dev(tmp_path):
    checkpoint = tmp_path / "dev.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    TileSpringEngine.shared_sites = {}
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=DeviceTileSpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


def _big():
    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((3, 3, 2))    # 144 atoms: tiled in the fake
    at.positions += np.random.default_rng(1).normal(scale=0.05, size=at.positions.shape)
    return at


def test_auto_runs_a_cell_that_does_not_fit_in_tiles_with_the_whole_runs_nve_trajectory(ff, tmp_path):
    nve = integrators.NVE(timestep_fs=1.0, fixcm=False)
    runs = {}
    for capacity in ("auto", "whole"):
        runs[capacity] = loupmd.md(_big(), model=ff, integrator=nve, steps=60, output=str(tmp_path / capacity),
                                   seed=2, initial_velocities=300.0, capacity=capacity)
    tiled, whole = runs["auto"].simulation, runs["whole"].simulation
    assert isinstance(tiled._engine, TiledEngine) and tiled.execution["mode"] == "tiled"
    assert not isinstance(whole._engine, TiledEngine) and whole.execution["mode"] == "whole"
    assert "plan" in tiled._engine._eng.log and "plan" not in whole._engine.log
    rows_t = output.read_thermo(tmp_path / "auto")[1]
    rows_w = output.read_thermo(tmp_path / "whole")[1]
    assert [int(r[0]) for r in rows_t] == [int(r[0]) for r in rows_w] and len(rows_t) >= 3
    assert [r[4:8] for r in rows_t] == [r[4:8] for r in rows_w]          # temperature and energies, as written
    assert np.allclose(tiled.atoms.positions, whole.atoms.positions, rtol=0, atol=1e-12)
    # one tiled call per step, plus the first: the thermo steps' state round trip repeats none
    assert tiled._engine._eng.tiled_calls == 61
    plan = runs["auto"].metadata["plan"]
    assert plan["execution"] == "tiled" and plan["receivers"] == 64 and plan["tiles"] == 3
    assert plan["memory"]["tiled_global_bytes"] == 14400
    assert provenance.validate(runs["auto"].metadata) == []
    summary = runs["auto"].summary
    assert "3 tiles of at most 64 atoms" in summary and "the integrator runs on the host" in summary
    assert "(the cell does not fit the card whole)" in summary              # auto chose the tiles
    assert "the whole system on" in runs["whole"].summary
    record = json.loads((tmp_path / "auto" / "simulation.json").read_text())
    assert record["capacity"] == {"mode": "tiled", "receivers": 64, "memory_fraction": 0.9}


def test_auto_keeps_a_cell_that_fits_whole(ff, tmp_path):
    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True)
    res = loupmd.md(at, model=ff, temperature_K=300, steps=10, output=str(tmp_path / "r"), seed=1,
                    initial_velocities="maxwell_boltzmann")
    assert res.simulation.execution["mode"] == "whole" and res.metadata["plan"]["execution"] == "whole"
    assert not isinstance(res.simulation._engine, TiledEngine)


def test_the_tiled_mode_refuses_the_integrators_it_does_not_run(ff, ff_dev, tmp_path):
    npt = integrators.Berendsen(timestep_fs=1.0, temperature_K=300, taut_fs=100.0, pressure_GPa=0.0, taup_fs=1000.0,
                                compressibility_per_GPa=0.01)
    at = _big()
    quick.draw_initial_velocities(at, 300.0, 1)
    # a barostat needs the device loop with the tiled barostats (LT6 (a)): not the host loop, not an older library
    for model in (ff, ff_dev):
        for capacity in ("tiled", "wavefront"):
            with pytest.raises(PlanRefused, match="the berendsen barostat in tiled mode") as caught:
                loupmd.Simulation(at, model, integrator=npt, capacity=capacity).run(steps=5)
            assert "keeps the cell fixed" in str(caught.value.why)
    eng = TiledEngine(DeviceTileSpringEngine("bundle"))
    eng.set_system(np.asarray(at.numbers), at.get_masses())
    eng.set_state(at.positions, at.get_velocities(), at.cell.array)
    with pytest.raises(PlanRefused, match="on the host loop"):
        eng.run(5, npt.to_config(seed=1).to_struct())
    # the host loop (a library without loup_tiled_run) runs NVE and Langevin only
    csvr = integrators.CSVR(timestep_fs=1.0, temperature_K=300, tau_fs=100.0)
    sim = loupmd.Simulation(at, ff, integrator=csvr)                         # auto: the plan says tiled
    with pytest.raises(PlanRefused, match="on the host loop"):
        sim.run(steps=5)


def test_the_device_loop_runs_the_host_loops_nve_trajectory(ff, ff_dev, tmp_path):
    """O31: the same NVE run through the fake device loop and the host loop: the same thermo rows, positions and
    velocities, one tiled call per step plus the first, and the state crosses to the host only where it is read."""
    nve = integrators.NVE(timestep_fs=1.0, fixcm=False)
    runs = {}
    for name, model in (("host", ff), ("device", ff_dev)):
        TileSpringEngine.shared_sites = {}
        runs[name] = loupmd.md(_big(), model=model, integrator=nve, steps=60, output=str(tmp_path / name), seed=2,
                               initial_velocities=300.0, capacity="tiled")
    host, dev = runs["host"].simulation, runs["device"].simulation
    eng = dev._engine._eng
    assert dev._engine.integrator_on == "device" and host._engine.integrator_on == "host"
    assert eng.device_steps == 60 and not hasattr(host._engine._eng, "device_steps")
    rows_h = output.read_thermo(tmp_path / "host")[1]
    rows_d = output.read_thermo(tmp_path / "device")[1]
    assert [int(r[0]) for r in rows_h] == [int(r[0]) for r in rows_d] and len(rows_d) >= 3
    assert [r[4:8] for r in rows_h] == [r[4:8] for r in rows_d]
    assert np.allclose(dev.atoms.positions, host.atoms.positions, rtol=0, atol=1e-12)
    assert np.allclose(dev.atoms.get_velocities(), host.atoms.get_velocities(), rtol=0, atol=1e-12)
    assert eng.tiled_calls == 61 + 1        # the start's evaluate, then the device's own first force call
    assert eng.log.count("tiled_set_state") == 1                     # the thermo steps' round trips keep the state
    assert runs["device"].metadata["plan"]["integrator_on"] == "device"
    assert "the integrator runs on the device" in runs["device"].summary


def test_the_device_loop_runs_the_thermostats_and_restarts_carry_their_state(ff_dev, tmp_path):
    csvr = integrators.CSVR(timestep_fs=1.0, temperature_K=300, tau_fs=100.0)
    at = _big()
    quick.draw_initial_velocities(at, 300.0, 1)
    sim = loupmd.Simulation(at, ff_dev, integrator=csvr, seed=4, output=loupmd.Output(str(tmp_path / "c")),
                            capacity="tiled")
    sim.run(steps=30)
    blob = sim._engine.export_state()
    pos, vel, frc, e, step, ist, kind = sim._engine._eng.tiled_get_state()
    assert kind == _core.LOUP_CSVR and ist[0] == 30 and step == 30
    sim.save_restart()
    sim.close()
    again = loupmd.Simulation.resume(tmp_path / "c", force_field=ff_dev)
    again.run(steps=10)
    _, _, _, _, step2, ist2, kind2 = again._engine._eng.tiled_get_state()
    assert kind2 == _core.LOUP_CSVR and ist2[0] == 40 and step2 == 40      # the block went through the restart
    eng = TiledEngine(DeviceTileSpringEngine("bundle"))
    eng.set_system(np.asarray(at.numbers), at.get_masses())
    eng.import_state(blob)                                              # version 2 with the block
    assert eng._int_kind == _core.LOUP_CSVR and eng._int_state[0] == 30


class DeviceNptTileSpringEngine(DeviceTileSpringEngine):
    """DeviceTileSpringEngine with the tiled barostats (LT6 (a)): a barostat's step scales the cell, the positions and
    the springs' sites by 1 + 1e-4, so the cell the Simulation reads can be checked against the device's."""

    def has_tiled_barostats(self):
        return True

    def set_reference_volume(self, volume):
        self.log.append(("reference volume", float(volume)))
        self.v0 = float(volume)

    def tiled_get_cell(self):
        return self.dev["cell"].copy()

    def tiled_run(self, n_steps, it, max_rows=0):
        if it.kind not in (_core.LOUP_BERENDSEN_NPT, _core.LOUP_BAOAB_NPT, _core.LOUP_MTK_NPT):
            return super().tiled_run(n_steps, it, max_rows)
        rows, done = [], None
        for _ in range(n_steps):
            d = self.dev
            d["cell"] *= 1.0 + 1e-4
            d["x"] *= 1.0 + 1e-4
            sites = TileSpringEngine.shared_sites[len(d["z"])]
            sites *= 1.0 + 1e-4
            d["f"] = None
            st, r, step = super().tiled_run(1, it, max_rows=1)
            done = (st, step)
            rows.extend(r.tolist())
        return done[0], np.array(rows, dtype=_core.THERMO_DTYPE), done[1]


@pytest.fixture
def ff_npt(tmp_path):
    checkpoint = tmp_path / "npt.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made, SpringEngine.poison_at = [], None
    TileSpringEngine.shared_sites = {}
    return loupmd.load(str(checkpoint), trusted=True, engine_factory=DeviceNptTileSpringEngine,
                       ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"), probe=lambda p: None)


def test_a_barostat_runs_on_the_tiled_device_loop_and_its_cell_reaches_rows_atoms_and_restarts(ff_npt, tmp_path):
    """LT6 (a): a tiled NPT run goes to the device loop; the device's cell is the run's (atoms, rows, restart). V0 is
    the volume of the state sent at a start (no set_reference_volume, as in the whole mode) and the first run's on a
    resume, which starts from the saved cell."""
    npt = integrators.MTK(timestep_fs=1.0, temperature_K=300.0, pressure_GPa=0.0, tdamp_fs=100.0, pdamp_fs=900.0)
    at = _big()
    quick.draw_initial_velocities(at, 300.0, 1)
    start = at.get_volume()
    sim = loupmd.Simulation(at, ff_npt, integrator=npt, seed=4, capacity="tiled",
                            output=loupmd.Output(str(tmp_path / "p"), thermo_every=10, restart_every=30))
    sim.run(steps=30)
    eng = sim._engine._eng
    assert sim._engine.integrator_on == "device" and eng.device_steps == 30
    grown = start * (1.0 + 1e-4) ** 90
    assert np.allclose(sim.atoms.cell.array, eng.tiled_get_cell(), rtol=0, atol=0)
    assert sim.atoms.get_volume() == pytest.approx(grown, rel=1e-12)
    assert eng.log.count("tiled_set_state") == 1
    assert not [e for e in eng.log if isinstance(e, tuple) and e[0] == "reference volume"]   # V0: the state's own
    header, rows = output.read_thermo(tmp_path / "p")
    assert header == list(output.THERMO_HEADER + output.NPT_COLUMNS)
    volumes = [float(r[8]) * len(at) for r in rows]
    assert [int(r[0]) for r in rows] == [0, 10, 20, 30] and volumes[0] == pytest.approx(start, rel=1e-12)
    assert volumes[-1] == pytest.approx(grown, rel=1e-12) and volumes[1] > volumes[0]
    sim.close()
    again = loupmd.Simulation.resume(tmp_path / "p", force_field=ff_npt)
    again.run(steps=10)
    eng2 = again._engine._eng
    assert ("reference volume", pytest.approx(start)) in eng2.log            # the run's V0, not the resumed cell's
    assert again.atoms.get_volume() == pytest.approx(grown * (1.0 + 1e-4) ** 30, rel=1e-12)


def test_a_version_1_state_block_is_still_read(ff):
    eng = TiledEngine(TileSpringEngine("bundle"))
    n = 4
    eng.set_system(np.full(n, 11), np.full(n, 23.0))
    import struct

    pos, vel, cell = np.arange(3 * n, dtype=float), np.ones(3 * n), np.eye(3).ravel() * 10
    eng.import_state(struct.pack("<8sIqq", b"LOUPTILE", 1, n, 7) + pos.tobytes() + vel.tobytes() + cell.tobytes())
    assert eng._noise_step == 7 and eng._int_kind == -1 and np.array_equal(eng._pos.ravel(), pos)


def test_dispersion_or_the_environment_sends_the_tiled_run_to_the_host_loop(ff_dev, monkeypatch):
    eng = TiledEngine(DeviceTileSpringEngine("bundle"))
    assert eng.integrator_on == "device"
    monkeypatch.setenv("LOUP_TILED_HOST_MD", "1")
    assert eng.integrator_on == "host"
    monkeypatch.delenv("LOUP_TILED_HOST_MD")
    eng.dispersion = object()
    assert eng.integrator_on == "host"


def test_the_wavefront_mode_runs_the_tiled_engine_and_the_report_says_so(ff, tmp_path):
    """S5-T08: capacity='wavefront' asks the engine for LOUP_EXEC_WAVEFRONT; the record and the report name it."""
    res = loupmd.md(_big(), model=ff, temperature_K=300, steps=10, output=str(tmp_path / "w"), seed=1,
                    initial_velocities="maxwell_boltzmann", capacity="wavefront")
    sim = res.simulation
    assert isinstance(sim._engine, TiledEngine) and sim._engine._eng.execution[0] == _core.LOUP_EXEC_WAVEFRONT
    assert sim.execution["mode"] == "wavefront" and sim._engine.wavefront
    plan = res.metadata["plan"]
    assert plan["execution"] == "tiled" and plan["wavefront"] is True
    assert "wavefront order" in res.summary
    assert "(capacity='wavefront' asked for tiles)" in res.summary          # not "does not fit": it was asked for
    assert provenance.validate(res.metadata) == []


def test_langevin_in_tiles_holds_its_target_and_its_fixed_atoms(ff):
    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((5, 5, 5))     # 1,000 atoms
    fixed = np.zeros(len(at), dtype=bool)
    fixed[:50] = True
    at.set_constraint(FixAtoms(mask=fixed))
    start = at.positions[fixed].copy()
    lang = integrators.Langevin(timestep_fs=2.0, temperature_K=300.0, friction_per_fs=0.02)
    sim = loupmd.Simulation(at, ff, integrator=lang, seed=5, output=None)
    sim.run(steps=400)
    temps = []
    for _ in range(20):
        temps.append(sim.run(steps=40).final_temperature_K)
    assert isinstance(sim._engine, TiledEngine)
    assert abs(np.mean(temps) / 300.0 - 1.0) < 0.05, np.mean(temps)
    assert np.array_equal(sim.atoms.positions[fixed], start)


def test_a_tiled_run_resumes_where_it_stopped(ff, tmp_path):
    lang = integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.02)
    full = loupmd.Simulation(_big(), ff, integrator=lang, seed=9, output=loupmd.Output(str(tmp_path / "full")))
    full.run(steps=40)
    half = loupmd.Simulation(_big(), ff, integrator=lang, seed=9, output=loupmd.Output(str(tmp_path / "half")))
    half.run(steps=20)
    half.save_restart()
    half.close()
    again = loupmd.Simulation.resume(tmp_path / "half", force_field=ff)
    assert isinstance(again._engine, TiledEngine) and again.step == 20
    again.run(steps=20)
    assert np.allclose(again.atoms.positions, full.atoms.positions, rtol=0, atol=1e-12)
    assert np.allclose(again.atoms.get_velocities(), full.atoms.get_velocities(), rtol=0, atol=1e-12)


def test_loupmd_md_capacity_auto_runs_a_cell_that_does_not_fit_in_tiles_and_says_so(ff, tmp_path, monkeypatch,
                                                                                     capsys):
    """S5-T12's acceptance on the fake engine (the GPU test runs it on a cell that does not fit the card)."""
    from ase.io import write

    from loupmd import simulation
    from loupmd.cli import main

    write(tmp_path / "salt.cif", bulk("NaCl", "rocksalt", a=5.64, cubic=True))
    monkeypatch.setattr(quick, "load", lambda *a, **k: ff)
    monkeypatch.setattr(simulation, "load", lambda *a, **k: ff)
    monkeypatch.chdir(tmp_path)
    base = ["md", "salt.cif", "--model", "m", "--temperature", "300", "--steps", "40", "--timestep", "1", "--seed",
            "3", "--initial-velocities", "maxwell_boltzmann", "--repeat", "3", "3", "2"]
    assert main([*base, "--capacity", "auto", "--output", "a"]) == 0
    out = capsys.readouterr().out
    assert "3 tiles of at most 64 atoms" in out and "the integrator runs on the host" in out
    metadata = json.loads((tmp_path / "a" / "metadata.json").read_text())
    assert metadata["plan"]["execution"] == "tiled" and metadata["arguments"]["capacity"] == "auto"
    assert main(["run", "--resume", "a", "--steps", "20"]) == 0
    assert "3 tiles of at most 64 atoms" in capsys.readouterr().out
    assert main([*base, "--capacity", "whole", "--output", "b"]) == 0
    assert "the whole system on" in capsys.readouterr().out


def test_a_state_block_of_the_other_engine_is_refused():
    eng = TiledEngine(TileSpringEngine("bundle"))
    eng.set_system(np.full(4, 11), np.full(4, 23.0))
    with pytest.raises(BackendError, match="not a tiled-mode state block"):
        eng.import_state(b"x" * 400)


def test_the_report_names_what_the_plan_keeps_in_host_memory():
    """The memory line of a tiled plan: nothing about the host when everything is on the device, the tile lists when
    only they are in pinned host memory, the lists and the layer state when the plan moved both (PLAN.md O31, O32)."""
    from loupmd import report

    def line(**host):
        memory = {"whole_bytes": 32 << 30, "free_bytes": 13 << 30, "tiled_global_bytes": 1 << 30,
                  "tile_workspace_bytes": 7 << 30, **host}
        plan = {"execution": "tiled", "receivers": 65536, "tiles": 27, "kernels": None, "memory": memory,
                "precision": provenance.PRECISION}
        return next(text for text in report._plan_lines({"plan": plan, "gpu": None}) if text.startswith("memory:"))

    assert line(host_bytes=0).endswith("tiled 8.00 GiB planned, 13.00 GiB free on the card")
    assert line(host_bytes=2 << 30, host_lists=True).endswith(
        "; the tile lists' edges in pinned host memory (2.00 GiB)")
    assert line(host_bytes=6 << 30, host_lists=True, host_state=True).endswith(
        "; the tile lists' edges and the layer state in pinned host memory (6.00 GiB)")
    assert line(host_bytes=2 << 30).endswith("the tile lists' edges in pinned host memory (2.00 GiB)")  # older record
