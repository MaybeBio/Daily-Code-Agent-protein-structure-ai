"""The Nose-Hoover chain on the GPU (plan task S4-T04): the engine's steps are ASE 3.27's ``NoseHooverChainNVT``
steps, the conserved quantity holds, the target can ramp while the thermostat masses stay, and the chain's
variables travel in the state block."""
from __future__ import annotations

import numpy as np
import pytest
from ase import units
from gpu_support import maxwell_velocities, srtio3

import loupmd
from loupmd import BackendError, LoupEngine, _core


def _start(eng, temp=300.0, seed=5, drift=0.0):
    at = srtio3(3)                                                   # 135 atoms, three masses
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    velocities = maxwell_velocities(at, temp, seed) + drift
    eng.set_state(at.positions, velocities, at.cell.array)
    at.set_velocities(velocities)
    return at


def _nhc(tdamp_fs=50.0, temp_k=300.0, tchain=3, tloop=1, dt_fs=1.0, **fields):
    return _core.integrator(_core.LOUP_NHC, dt_fs, temp_k=temp_k, tau_t_fs=tdamp_fs, chain_length=tchain,
                            chain_loops=tloop, **fields)


@pytest.mark.parametrize("tchain,tloop", [(3, 1), (1, 1), (5, 2)], ids=["ase-defaults", "one-thermostat", "5x2"])
def test_the_engine_takes_ase_s_steps(sto_engine, model_path, tchain, tloop):
    """The plan's criterion: positions within 1e-4 A of ASE's ``NoseHooverChainNVT`` driven by ``lm.calc`` after
    200 steps from the same state. The conserved quantity is ASE's ``get_conserved_energy``."""
    from ase.md.nose_hoover_chain import NoseHooverChainNVT

    eng, steps, tdamp_fs = sto_engine, 200, 50.0
    at = _start(eng)
    eng.run(steps, _nhc(tdamp_fs=tdamp_fs, tchain=tchain, tloop=tloop, thermo_every=steps))
    positions, velocities, _, _ = eng.get_state()
    row = eng.read_thermo()[-1]

    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    dyn = NoseHooverChainNVT(ref, 1.0 * units.fs, temperature_K=300.0, tdamp=tdamp_fs * units.fs, tchain=tchain,
                             tloop=tloop)
    dyn.run(steps)
    worst = np.abs(positions - ref.positions).max()
    conserved = dyn.get_conserved_energy()
    chain = float(row["conserved"]) - float(row["e_pot"]) - float(row["e_kin"])
    chain_ase = conserved - ref.get_potential_energy() - ref.get_kinetic_energy()
    print(f"Nose-Hoover chain {tchain} x {tloop} against ASE, {steps} steps: positions within {worst:.1e} A, "
          f"velocities within {np.abs(velocities - ref.get_velocities()).max():.1e}; the chain's energy "
          f"{chain:.6f} eV against {chain_ase:.6f} eV; conserved quantity {float(row['conserved']):.6f} eV against "
          f"{conserved:.6f} eV")
    assert worst < 1e-4
    assert chain == pytest.approx(chain_ase, abs=2e-5) and abs(chain) > 1e-3       # the chain holds energy
    # The totals carry each engine's float32 potential energy (two engines differ by up to 1e-6 eV/atom, PLAN D16).
    assert float(row["conserved"]) == pytest.approx(conserved, abs=3e-6 * len(at))
    assert float(row["e_kin"]) == pytest.approx(ref.get_kinetic_energy(), rel=1e-5)


def test_the_conserved_quantity_holds_and_the_temperature_is_the_target(sto_engine):
    eng, temp = sto_engine, 300.0
    at = _start(eng, temp=temp)
    rows = []
    for _ in range(10):
        eng.run(2_000, _nhc(tdamp_fs=100.0, temp_k=temp, thermo_every=100))
        rows.append(eng.read_thermo())
    rows = np.concatenate(rows)
    drift = np.polyfit(rows["step"] * 1e-3, rows["conserved"] / len(at) * 1e3, 1)[0]
    mean = rows["temp_k"][20:].mean()
    print(f"Nose-Hoover chain, 20,000 steps of 1 fs, tdamp 100 fs: mean temperature {mean:.1f} K; conserved "
          f"quantity: drift {drift:+.4f} meV/atom/ps, range {np.ptp(rows['conserved']) / len(at) * 1e3:.3f} meV/atom "
          f"while potential plus kinetic moved {np.ptp(rows['e_pot'] + rows['e_kin']) / len(at) * 1e3:.1f} meV/atom")
    assert abs(drift) < 0.05 and abs(mean - temp) < 15.0
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (3 * len(at) * units.kB), rtol=1e-12)


def test_a_ramp_moves_the_target_and_not_the_masses(sto_bundle, capfd, monkeypatch):
    eng = LoupEngine(sto_bundle)
    _start(eng, temp=100.0)
    eng.run(40, _nhc(tdamp_fs=25.0, temp_k=100.0, mass_temp_k=300.0))
    eng.run(2_000, _nhc(tdamp_fs=25.0, temp_k=100.0, mass_temp_k=300.0, temp_rate_k_per_step=0.2, thermo_every=100))
    ramp = eng.read_thermo()["temp_k"]
    eng.run(1_000, _nhc(tdamp_fs=25.0, temp_k=500.0, mass_temp_k=300.0, thermo_every=100))
    hold = eng.read_thermo()["temp_k"]
    assert 110 < ramp[4] < 290 and 210 < ramp[9] < 390 and 380 < ramp[-1] < 620 and 420 < hold.mean() < 580

    # As tests/test_md_graph_reuse.py: a graph is captured the first time its loop variant is used (and again when
    # the edge count leaves its bucket, which a ramp over 400 K does), so the captures of short calls whose target
    # changes with every call are compared with those of a constant target.
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    # The generic layers' conv variants are timed at an engine's first MD rebuild, and a faster one drops the graphs
    # (ledger S64). On 135 atoms they are near ties, so whether an engine captures once more would be chance.
    monkeypatch.setenv("LOUP_CONV_TUNE", "0")

    def captures(temperatures, rate):
        eng = LoupEngine(sto_bundle)
        _start(eng)
        capfd.readouterr()
        for temp_k in temperatures:
            eng.run(6, _nhc(tdamp_fs=25.0, temp_k=temp_k, mass_temp_k=300.0))
        eng.run(6, _nhc(tdamp_fs=25.0, temp_k=300.0, mass_temp_k=300.0, temp_rate_k_per_step=rate))
        before = capfd.readouterr().err.count("loupmd: MD graph capture")
        eng.run(6, _nhc(tdamp_fs=25.0, temp_k=300.0, mass_temp_k=500.0))
        return before, capfd.readouterr().err.count("loupmd: MD graph capture")

    constant = captures([300.0] * 8, 0.0)
    varied = captures([300.0, 300.5, 299.5, 300.2, 299.8, 300.4, 299.6, 300.0], 0.05)
    print(f"Nose-Hoover ramp 100 to 500 K in 2 ps: {ramp[4]:.0f} K at 0.5 ps, {ramp[9]:.0f} K at 1 ps, "
          f"{ramp[-1]:.0f} K at the end; then held at 500 K: mean {hold.mean():.0f} K")
    assert varied[0] == constant[0], (constant, varied)
    assert constant[1] >= 2 and varied[1] >= 2               # other thermostat masses are another captured step


def test_the_chain_travels_in_the_state_block(sto_bundle):
    def engine(start=True):
        eng = LoupEngine(sto_bundle)
        at = _start(eng) if start else srtio3(3)
        if not start:
            eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
        return eng

    whole = engine()
    whole.run(100, _nhc(thermo_every=100))
    whole.run(100, _nhc(thermo_every=100))
    reference = whole.read_thermo()

    first = engine()
    first.run(100, _nhc(thermo_every=100))
    blob = first.export_state()
    pos, vel, _, _ = first.get_state()
    resumed = engine(start=False)
    resumed.import_state(blob)
    resumed.run(100, _nhc(thermo_every=100))
    row = resumed.read_thermo()[-1]

    def chain(thermo_row):
        return float(thermo_row["conserved"]) - float(thermo_row["e_pot"]) - float(thermo_row["e_kin"])

    assert chain(row) == pytest.approx(chain(reference[1]), abs=1e-5) and abs(chain(row)) > 1e-3
    # The totals carry each engine's float32 potential energy (two engines differ by up to 1e-6 eV/atom, PLAN D16).
    assert float(row["conserved"]) == pytest.approx(float(reference[1]["conserved"]), abs=3e-6 * 135)
    assert np.abs(resumed.get_state()[0] - whole.get_state()[0]).max() < 1e-5

    fresh = engine(start=False)                              # the same positions and velocities, an empty chain
    fresh.set_state(pos, vel, srtio3(3).cell.array)
    fresh.run(100, _nhc(thermo_every=100))
    assert np.abs(fresh.get_state()[0] - whole.get_state()[0]).max() > 1e-4


def test_degrees_of_freedom_fixed_atoms_and_refusals(sto_engine):
    eng = sto_engine
    at = _start(eng, drift=0.02)
    masses = at.get_masses()[:, None]
    before = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    eng.run(300, _nhc(fix_com=1, thermo_every=100))
    after = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    rows = eng.read_thermo()
    assert before > 1.0 and after < 1e-7 * before
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (402 * units.kB), rtol=1e-12)      # 3N - 3

    at = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_fixed_atoms(fixed)
    start = eng.get_state()[0]
    stats = eng.run(300, _nhc(thermo_every=100))
    positions, velocities, _, _ = eng.get_state()
    assert np.array_equal(positions[fixed], start[fixed]) and not velocities[fixed].any()
    assert 150 < stats.final_temperature_k < 450
    eng.set_fixed_atoms(None)

    _start(eng)
    for fields, reason in ((dict(tdamp_fs=0.0), "tau_t_fs must be finite and positive, got 0 fs"),
                           (dict(tchain=0), "chain_length must be from 1 to 16 thermostats, got 0"),
                           (dict(tchain=17), "chain_length must be from 1 to 16 thermostats, got 17"),
                           (dict(tloop=-1), "chain_loops must be from 0 .one. to 100 sub-steps, got -1"),
                           (dict(temp_k=0.0), "need a temperature above 0 K: mass_temp_k is 0 K and temp_k 0 K"),
                           (dict(temp_k=-5.0), "temp_k must be finite and not negative, got -5 K")):
        with pytest.raises(BackendError, match="loup_run: .*" + reason):
            eng.run(10, _nhc(**fields))
    assert np.isfinite(eng.run(10, _nhc(temp_k=0.0, mass_temp_k=300.0)).final_temperature_k)   # a target of 0 K


@pytest.mark.full
def test_what_the_chain_costs(model_path):
    """Two kinetic-energy sums, two single-thread kernels and one scaling per step beside velocity Verlet; no noise
    per atom. Against Langevin at the same temperature: 5,000 atoms, a b b a twice."""
    from loupmd import integrators

    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    records = {"nhc": integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=300.0, tdamp_fs=100.0, fixcm=False),
               "langevin": integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01,
                                                fixcm=False)}
    runs = {name: loupmd.Simulation(at, loupmd.load(model_path, trusted=True), seed=1, integrator=record)
            for name, record in records.items()}
    for run in runs.values():
        run.run(steps=300)
    times = {"nhc": [], "langevin": []}
    for name in ("langevin", "nhc", "nhc", "langevin") * 2:
        times[name].append(runs[name].run(steps=400).ms_per_step)
    ratio = float(np.median(times["nhc"]) / np.median(times["langevin"]))
    print(f"Nose-Hoover chain against Langevin, 5,000 atoms at 300 K: ms/step {np.round(times['nhc'], 3)} against "
          f"{np.round(times['langevin'], 3)}, ratio of the medians {ratio:.4f}")
    assert ratio < 1.03                    # single runs of 400 steps scatter by about 2% on this card
    for run in runs.values():
        run.close()
