"""CSVR, Bussi's stochastic velocity rescaling, on the GPU (plan task S4-T03): the engine's steps are ASE 3.27's
``Bussi`` steps for the same noise, the kinetic energy is canonical, the conserved quantity holds, the target can
ramp, and the energy the thermostat transferred travels in the state block."""
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
    velocities = (maxwell_velocities(at, temp, seed) if temp > 0 else np.zeros((len(at), 3))) + drift
    eng.set_state(at.positions, velocities, at.cell.array)
    at.set_velocities(velocities)
    return at


def _csvr(tau_fs=50.0, temp_k=300.0, seed=3, dt_fs=1.0, **fields):
    return _core.integrator(_core.LOUP_CSVR, dt_fs, temp_k=temp_k, tau_t_fs=tau_fs, seed=seed, **fields)


def _transferred(rows):
    """The energy the thermostat has put in, from the rows: conserved = e_pot + e_kin - transferred."""
    return rows["e_pot"] + rows["e_kin"] - rows["conserved"]


# ---------------------------------------------------------------------------------------------- the noise

@pytest.mark.parametrize("ndof", [2, 3, 4, 405, 15_000])
def test_the_noise_is_a_standard_normal_and_a_chi_square(sto_engine, ndof):
    """Equation A7 takes R1 ~ N(0, 1) and the sum of ndof - 1 squared normals, which is chi-square distributed.
    The draws are a function of seed, step and ndof alone, so these p-values never change."""
    from scipy import stats

    normal, chi2 = sto_engine.debug_csvr_noise(seed=11, first_step=0, n_steps=20_000, ndof=ndof)
    p_normal = stats.kstest(normal, "norm").pvalue
    p_chi2 = stats.kstest(chi2, "chi2", args=(ndof - 1,)).pvalue
    print(f"ndof {ndof}: Kolmogorov-Smirnov p = {p_normal:.3f} (normal), {p_chi2:.3f} (chi-square of {ndof - 1})")
    assert p_normal > 0.01 and p_chi2 > 0.01
    assert abs(np.corrcoef(normal, chi2)[0, 1]) < 0.03 and abs(np.corrcoef(chi2[:-1], chi2[1:])[0, 1]) < 0.03


def test_the_noise_of_a_step_depends_on_seed_and_step_only(sto_engine):
    eng = sto_engine
    whole = eng.debug_csvr_noise(seed=7, first_step=0, n_steps=64, ndof=405)
    part = eng.debug_csvr_noise(seed=7, first_step=40, n_steps=8, ndof=405)
    assert np.array_equal(part[0], whole[0][40:48]) and np.array_equal(part[1], whole[1][40:48])
    other = eng.debug_csvr_noise(seed=8, first_step=0, n_steps=64, ndof=405)
    assert not np.any(other[0] == whole[0]) and not np.any(other[1] == whole[1])
    one = eng.debug_csvr_noise(seed=7, first_step=0, n_steps=64, ndof=1)       # no further degrees of freedom
    assert np.array_equal(one[0], whole[0]) and not one[1].any()


# ------------------------------------------------------------------------------------- against ASE's Bussi

class EngineNoise:
    """ASE's ``rng`` argument, giving the engine's draws in ASE's order: a normal, then a gamma variate."""

    def __init__(self, normal, chi2):
        self.normal, self.chi2, self.step = normal, chi2, 0

    def standard_normal(self, size=None):
        # numpy 2.5 refuses None as a shape (numpy 2.2 took it for a scalar)
        return np.full(() if size is None else size, self.normal[self.step])

    def standard_gamma(self, shape):
        value = 0.5 * self.chi2[self.step]                 # ASE doubles it: 2 standard_gamma(n / 2) is chi2(n)
        self.step += 1
        return value


def test_the_engine_takes_ase_bussi_s_steps_for_the_same_noise(sto_engine, model_path):
    from ase.md.bussi import Bussi

    eng, steps, tau_fs = sto_engine, 200, 50.0
    at = _start(eng)
    eng.run(steps, _csvr(tau_fs=tau_fs, thermo_every=steps))
    positions, velocities, _, _ = eng.get_state()
    row = eng.read_thermo()[-1]

    ref = at.copy()
    ref.calc = loupmd.calc(model_path, trusted=True)
    noise = EngineNoise(*eng.debug_csvr_noise(seed=3, first_step=0, n_steps=steps, ndof=3 * len(at)))
    dyn = Bussi(ref, 1.0 * units.fs, temperature_K=300.0, taut=tau_fs * units.fs, rng=noise)
    dyn.run(steps)
    assert noise.step == steps
    worst = np.abs(positions - ref.positions).max()
    transferred = float(_transferred(row))
    print(f"CSVR against ASE's Bussi with the same noise, {steps} steps: positions within {worst:.1e} A, "
          f"velocities within {np.abs(velocities - ref.get_velocities()).max():.1e}, transferred energy "
          f"{transferred:.6f} eV against {dyn.transferred_energy:.6f} eV")
    assert worst < 1e-4
    assert abs(transferred) > 1e-3 and transferred == pytest.approx(dyn.transferred_energy, abs=2e-5)
    assert float(row["e_kin"]) == pytest.approx(ref.get_kinetic_energy(), rel=1e-5)


# ------------------------------------------------------------------------------- the ensemble it samples

def test_the_kinetic_energy_is_canonical_and_the_conserved_quantity_holds(sto_engine):
    """The plan's criteria: the kinetic energy over 20,000 steps on 135 atoms follows the canonical distribution,
    K ~ Gamma(ndof / 2, kT) (Kolmogorov-Smirnov p > 0.01), and the conserved quantity drifts by less than
    0.05 meV/atom/ps. Samples are 100 fs apart, ten thermostat time constants. The trajectory is chaotic, so p
    differs from run to run: the assertion is p > 0.001, and the printed value is what is reported."""
    from scipy import stats

    eng, every, temp = sto_engine, 100, 300.0
    at = _start(eng, temp=temp)
    rows = []
    for _ in range(10):
        eng.run(2_000, _csvr(tau_fs=10.0, temp_k=temp, thermo_every=every))
        rows.append(eng.read_thermo())
    rows = np.concatenate(rows)
    assert rows["step"].tolist() == list(range(every, 20_001, every))
    ndof = 3 * len(at)
    kinetic = rows["e_kin"][10:]                                     # the first picosecond: equipartition
    p = stats.kstest(kinetic, "gamma", args=(0.5 * ndof, 0.0, units.kB * temp)).pvalue
    time_ps = rows["step"] * 1e-3
    drift = np.polyfit(time_ps, rows["conserved"] / len(at) * 1e3, 1)[0]
    spread = np.ptp(rows["conserved"]) / len(at) * 1e3
    moved = np.ptp(_transferred(rows)) / len(at) * 1e3
    print(f"CSVR, 20,000 steps of 1 fs, tau 10 fs: mean temperature {rows['temp_k'][10:].mean():.1f} K, "
          f"Kolmogorov-Smirnov p = {p:.3f} over {len(kinetic)} samples; conserved quantity: drift {drift:+.4f} "
          f"meV/atom/ps, range {spread:.3f} meV/atom while the thermostat moved {moved:.1f} meV/atom")
    assert p > 1e-3
    assert abs(drift) < 0.05
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (ndof * units.kB), rtol=1e-12)


def test_the_target_ramps_and_a_structure_at_rest_is_heated(sto_engine):
    eng = sto_engine
    _start(eng, temp=100.0)
    eng.run(2_000, _csvr(tau_fs=20.0, temp_k=100.0, temp_rate_k_per_step=0.2, thermo_every=100))      # to 500 K
    ramp = eng.read_thermo()["temp_k"]
    eng.run(1_000, _csvr(tau_fs=20.0, temp_k=500.0, thermo_every=100))
    hold = eng.read_thermo()["temp_k"]
    print(f"CSVR ramp 100 to 500 K in 2 ps: {ramp[4]:.0f} K at 0.5 ps, {ramp[9]:.0f} K at 1 ps, {ramp[-1]:.0f} K "
          f"at the end; then held at 500 K: mean {hold.mean():.0f} K")
    assert 130 < ramp[4] < 270 and 230 < ramp[9] < 370 and 400 < ramp[-1] < 600 and 430 < hold.mean() < 570
    # At rest there is nothing to scale: the first step is a velocity-Verlet step, and the thermostat takes over
    # from the motion the forces start.
    _start(eng, temp=0.0)
    stats = eng.run(1_000, _csvr(tau_fs=20.0, temp_k=300.0))
    assert 200 < stats.final_temperature_k < 400


def test_fix_com_and_fixed_atoms(sto_engine):
    eng = sto_engine
    at = _start(eng, drift=0.02)
    masses = at.get_masses()[:, None]
    before = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    eng.run(300, _csvr(fix_com=1, thermo_every=100))
    after = np.abs((masses * eng.get_state()[1]).sum(axis=0)).max()
    rows = eng.read_thermo()
    assert before > 1.0 and after < 1e-7 * before
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (402 * units.kB), rtol=1e-12)      # 3N - 3

    at = _start(eng)
    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True                                                # the 27 Sr atoms
    eng.set_fixed_atoms(fixed)
    start = eng.get_state()[0]
    stats = eng.run(300, _csvr(thermo_every=100))
    positions, velocities, _, _ = eng.get_state()
    rows = eng.read_thermo()
    assert np.array_equal(positions[fixed], start[fixed]) and not velocities[fixed].any()
    assert np.abs(positions[~fixed] - start[~fixed]).max() > 0.05
    assert np.allclose(rows["temp_k"], 2 * rows["e_kin"] / (3 * 108 * units.kB), rtol=1e-12)
    assert 150 < stats.final_temperature_k < 450


# ------------------------------------------------------------------------------ state, graphs, refusals

def test_the_transferred_energy_travels_in_the_state_block(sto_bundle):
    def engine(start=True):
        eng = LoupEngine(sto_bundle)
        at = _start(eng) if start else srtio3(3)
        if not start:
            eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
        return eng

    whole = engine()
    whole.run(100, _csvr(thermo_every=100))
    whole.run(100, _csvr(thermo_every=100))
    reference = whole.read_thermo()

    first = engine()
    first.run(100, _csvr(thermo_every=100))
    blob = first.export_state()
    pos, vel, _, _ = first.get_state()
    resumed = engine(start=False)
    resumed.import_state(blob)
    resumed.run(100, _csvr(thermo_every=100))
    row = resumed.read_thermo()[-1]
    so_far, total = float(_transferred(reference[0])), float(_transferred(reference[1]))
    print(f"transferred energy: {so_far:.5f} eV after 100 steps, {total:.5f} eV after 200; resumed run "
          f"{float(_transferred(row)):.5f} eV")
    assert abs(so_far) > 1e-3
    assert float(_transferred(row)) == pytest.approx(total, abs=1e-5)
    assert np.abs(resumed.get_state()[0] - whole.get_state()[0]).max() < 1e-5

    # New positions and velocities are a new run: the transferred energy starts at zero. On the same handle the
    # noise goes on from step 100, so these 100 steps are the uninterrupted run's second hundred.
    first.set_state(pos, vel, srtio3(3).cell.array)
    first.run(100, _csvr(thermo_every=100))
    assert float(_transferred(first.read_thermo()[-1])) == pytest.approx(total - so_far, abs=1e-5)


def test_a_changed_target_keeps_the_captured_step_and_a_changed_time_constant_does_not(sto_bundle, capfd,
                                                                                         monkeypatch):
    """As tests/test_md_graph_reuse.py: a graph is captured the first time its loop variant is used, so the
    captures of a run whose target changes with every call are compared with those of a constant one."""
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    # The generic layers' conv variants are timed at an engine's first MD rebuild, and a faster one drops the graphs
    # (ledger S64). On 135 atoms they are near ties, so whether an engine captures once more would be chance.
    monkeypatch.setenv("LOUP_CONV_TUNE", "0")

    def captures(temperatures, rate, tau_fs=50.0):
        eng = LoupEngine(sto_bundle)
        _start(eng)
        capfd.readouterr()
        for temp_k in temperatures:
            eng.run(6, _csvr(temp_k=temp_k, tau_fs=tau_fs))
        eng.run(6, _csvr(temp_k=300.0, temp_rate_k_per_step=rate, tau_fs=tau_fs))
        before = capfd.readouterr().err.count("loupmd: MD graph capture")
        eng.run(6, _csvr(temp_k=300.0, tau_fs=25.0))
        return before, capfd.readouterr().err.count("loupmd: MD graph capture")

    constant = captures([300.0] * 8, 0.0)
    varied = captures([300.0, 300.5, 299.5, 300.2, 299.8, 300.4, 299.6, 300.0], 0.05)
    assert varied[0] == constant[0], (constant, varied)
    assert constant[1] >= 2 and varied[1] >= 2                       # another time constant is another graph


@pytest.mark.parametrize("fields,reason", [
    (dict(tau_fs=0.0), "loup_run: tau_t_fs must be finite and positive, got 0 fs"),
    (dict(tau_fs=float("nan")), "loup_run: tau_t_fs must be finite and positive, got nan fs"),
    (dict(temp_k=-1.0), "loup_run: temp_k must be finite and not negative, got -1 K"),
    (dict(temp_k=100.0, temp_rate_k_per_step=-20.0), "must not take the target below 0 K"),
])
def test_refusals(sto_engine, fields, reason):
    eng = sto_engine
    _start(eng)
    with pytest.raises(BackendError, match=reason):
        eng.run(10, _csvr(**fields))
    assert np.isfinite(eng.run(10, _csvr()).final_temperature_k)


@pytest.mark.full
def test_what_the_thermostat_costs(model_path):
    """CSVR adds a kinetic-energy sum and one thread's noise to a velocity-Verlet step, and draws no noise per
    atom. Compared with Langevin at the same temperature (NVE from the same start is 150 K colder and rebuilds
    its neighbour list less often): 5,000 atoms, a b b a."""
    from loupmd import integrators

    at = srtio3(10)
    at.set_velocities(maxwell_velocities(at, 300.0, seed=11))
    records = {"csvr": integrators.CSVR(timestep_fs=1.0, temperature_K=300.0, tau_fs=100.0, fixcm=False),
               "langevin": integrators.Langevin(timestep_fs=1.0, temperature_K=300.0, friction_per_fs=0.01,
                                                fixcm=False)}
    runs = {name: loupmd.Simulation(at, loupmd.load(model_path, trusted=True), seed=1, integrator=record)
            for name, record in records.items()}
    for run in runs.values():
        run.run(steps=300)
    times = {"csvr": [], "langevin": []}
    for name in ("langevin", "csvr", "csvr", "langevin"):
        times[name].append(runs[name].run(steps=400).ms_per_step)
    ratio = sum(times["csvr"]) / sum(times["langevin"])
    print(f"CSVR against Langevin, 5,000 atoms at 300 K: ms/step {times['csvr']} against {times['langevin']}, "
          f"ratio {ratio:.4f}")
    assert ratio < 1.02
    for run in runs.values():
        run.close()
