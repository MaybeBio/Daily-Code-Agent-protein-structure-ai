"""Monte Carlo swaps (plan task S6-T02) on fake engines: the acceptance ratio of an ideal binary mixture (a
site-preference model without interactions) against its exact value, the Metropolis rule, the move's arguments and
the transaction around a block. Needs neither a GPU nor the library."""
from __future__ import annotations

import math

import numpy as np
import pytest
from ase import Atoms, units
from fake_core import SpringEngine

import loupmd
from loupmd import integrators, mc
from loupmd.errors import InputError, PlanRefused

A, B = 29, 79            # Cu, Au


class SiteEngine(SpringEngine):
    """``SpringEngine``'s dynamics with a site-preference energy instead of the springs': an A atom on a beta
    site costs ``delta`` eV. An atom is on the site nearest to it, so a swap (which exchanges two atoms'
    positions) moves the atoms between sites. ``evaluate_energy`` is the energy-only call."""

    delta = 0.0
    sites = None         # [n_sites, 3]
    beta = None          # [n_sites] bool

    def _energy(self):
        d = np.linalg.norm(self.pos[:, None, :] - SiteEngine.sites[None, :, :], axis=2)
        on_beta = SiteEngine.beta[d.argmin(axis=1)]
        return SiteEngine.delta * float(((self.numbers == A) & on_beta).sum())

    def evaluate_energy(self, positions, cell):
        self.pos = np.array(positions, dtype=float)       # as the real engine: the device positions are the trial's
        self.forces_current = False
        self.log.append("evaluate_energy")
        return self._energy()


def _mixture(m: int, seed: int):
    """``2 m`` sites on a line, the first ``m`` alpha and the rest beta; ``m`` A and ``m`` B atoms placed at
    random."""
    positions = np.array([[2.5 * k, 0.0, 0.0] for k in range(2 * m)])
    numbers = np.array([A] * m + [B] * m)
    np.random.default_rng(seed).shuffle(numbers)
    SiteEngine.sites, SiteEngine.beta = positions.copy(), np.arange(2 * m) >= m
    return Atoms(numbers=numbers, positions=positions, cell=[5.0 * m, 10.0, 10.0], pbc=True)


def _simulation(tmp_path, atoms, temperature_K=300.0):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made = []
    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=SiteEngine, probe=lambda p: None,
                     ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"))
    return loupmd.Simulation(atoms, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=temperature_K,
                                                                       friction_per_fs=0.01), seed=1)


def _exact_acceptance(m: int, x: float) -> float:
    """The site-preference mixture: with n A atoms on beta sites a configuration has weight x^n (x =
    exp(-delta / kT)) and there are C(m, n)^2 of them; a swap of a random A with a random B lowers n with
    probability (n/m)^2 (accepted), raises it with probability ((m - n)/m)^2 (accepted with x), else keeps it."""
    weights = [math.comb(m, n) ** 2 * x ** n for n in range(m + 1)]
    accept = [1.0 - ((m - n) / m) ** 2 * (1.0 - x) for n in range(m + 1)]
    return sum(w * a for w, a in zip(weights, accept)) / sum(weights)


@pytest.mark.parametrize("delta_kT", [0.0, 1.0, 2.5])
def test_the_acceptance_of_an_ideal_binary_mixture_matches_its_exact_value(tmp_path, delta_kT):
    m, temperature = 6, 300.0
    kT = units.kB * temperature
    SiteEngine.delta = delta_kT * kT
    sim = _simulation(tmp_path, _mixture(m, seed=5), temperature)
    move = mc.Swap(pairs=[("Cu", "Au")], attempts=500)
    accepted = []
    rng_seed = 11
    for block in range(60):
        result = mc.swap(sim, move, seed=rng_seed + block)
        accepted.append(result.counters.accepted / result.counters.attempted)
    blocks = np.array(accepted[10:])                       # the first blocks equilibrate
    mean, error = blocks.mean(), blocks.std(ddof=1) / math.sqrt(len(blocks))
    exact = _exact_acceptance(m, math.exp(-delta_kT))
    print(f"delta {delta_kT} kT: acceptance {mean:.4f} +- {error:.4f}, exact {exact:.4f}")
    assert abs(mean - exact) <= max(4.0 * error, 1e-12)
    assert sim.mc_counters["swap"].attempted == 60 * 500


def test_a_swap_exchanges_positions_and_velocities_and_the_engine_keeps_the_last_state(tmp_path):
    at = _mixture(4, seed=2)
    at.set_velocities(np.random.default_rng(1).normal(0.0, 0.01, (8, 3)))
    SiteEngine.delta = -1.0                                # every A wants a beta site: downhill swaps are taken
    sim = _simulation(tmp_path, at)
    sim.run(steps=1)
    before = sim.atoms
    result = mc.swap(sim, mc.Swap(pairs=[(A, B)], attempts=40), seed=3)
    after = sim.atoms
    assert result.counters.accepted >= 1
    assert np.array_equal(after.numbers, before.numbers)                  # labels and elements stay
    moved = np.flatnonzero(np.abs(after.positions - before.positions).max(axis=1) > 1e-9)
    assert len(moved) >= 2
    # every atom sits on a site that some atom occupied before, with the velocity it had
    old = {np.round(p, 6).tobytes(): v for p, v in zip(before.positions, before.get_velocities())}
    for p, v in zip(after.positions, after.get_velocities()):
        assert np.round(p, 6).tobytes() in old
    assert sorted(map(tuple, np.round(after.get_velocities(), 12))) == sorted(map(tuple, np.round(before.get_velocities(), 12)))
    assert result.energy_eV == pytest.approx(after.get_potential_energy())
    engine, = SpringEngine.made
    assert engine.log[-1] == "set_state"
    sim.run(steps=2)                                                     # the run goes on from it
    assert sim.step == 3


def test_a_block_with_nothing_accepted_puts_the_state_block_back(tmp_path):
    SiteEngine.delta = 1e6                                 # nothing uphill is ever taken
    at = _mixture(3, seed=0)
    at.numbers = np.array([A, A, A, B, B, B])              # every A on alpha: each swap is uphill
    sim = _simulation(tmp_path, at)
    sim.run(steps=1)
    before = sim.atoms
    result = mc.swap(sim, mc.Swap(pairs=[(A, B)], attempts=20), seed=1)
    assert result.counters.accepted == 0 and result.counters.attempted == 20
    engine, = SpringEngine.made
    assert engine.log[-1] == "import_state"
    assert np.allclose(sim.atoms.positions, before.positions)


def test_non_finite_trial_energies_are_rejected_and_counted(tmp_path, monkeypatch):
    SiteEngine.delta = 0.0
    sim = _simulation(tmp_path, _mixture(3, seed=1))
    sim.run(steps=1)
    engine, = SpringEngine.made
    monkeypatch.setattr(engine, "evaluate_energy", lambda positions, cell: float("nan"))
    result = mc.swap(sim, mc.Swap(pairs=[(A, B)], attempts=5), seed=1)
    assert result.counters.rejected_nonfinite == 5 and result.counters.accepted == 0


def test_fixed_atoms_are_never_chosen(tmp_path):
    from ase.constraints import FixAtoms

    SiteEngine.delta = 0.0
    at = _mixture(3, seed=4)
    a_atoms = np.flatnonzero(at.numbers == A)
    at.set_constraint(FixAtoms(indices=a_atoms[:2]))
    sim = _simulation(tmp_path, at)
    sim.run(steps=1)
    before = sim.atoms.positions
    mc.swap(sim, mc.Swap(pairs=[(A, B)], attempts=50), seed=2)
    assert np.allclose(sim.atoms.positions[a_atoms[:2]], before[a_atoms[:2]])


def test_the_moves_arguments_are_checked():
    assert mc.Swap(pairs=[("Cu", "Au")]).pairs == ((29, 79),)
    for bad in ("CuAu", [("Cu",)], [("Cu", "Cu")], [("Cu", "Xx")], []):
        with pytest.raises(InputError):
            mc.Swap(pairs=bad)
    with pytest.raises(InputError, match="attempts"):
        mc.Swap(pairs=[("Cu", "Au")], attempts=0)
    with pytest.raises(PlanRefused, match="rescale"):
        mc.Swap(pairs=[("Cu", "Au")], velocities="rescale")


def test_a_swap_needs_a_temperature_and_both_species(tmp_path):
    SiteEngine.delta = 0.0
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"x")
    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=SiteEngine, probe=lambda p: None,
                     ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"))
    sim = loupmd.Simulation(_mixture(2, seed=0), ff, integrator=integrators.NVE(timestep_fs=1.0), seed=1)
    with pytest.raises(InputError, match="needs a temperature"):
        mc.swap(sim, mc.Swap(pairs=[(A, B)]))
    with pytest.raises(InputError, match="no pair"):
        mc.swap(sim, mc.Swap(pairs=[(A, 26)]), temperature_K=300.0)


# ------------------------------------------------------------------------------ transmute (S6-T03)

class ElementEngine(SpringEngine):
    """An ideal solution: each atom's energy depends on its element only (``eps`` eV by atomic number)."""

    eps = {}

    def _energy(self):
        return float(sum(ElementEngine.eps.get(int(z), 0.0) for z in self.numbers))

    def evaluate_energy(self, positions, cell):
        self.pos = np.array(positions, dtype=float)
        self.log.append("evaluate_energy")
        return self._energy()


def _transmute_sim(tmp_path, atoms, elements=None, temperature_K=300.0):
    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made = []
    exported = []

    def ensure_bundle(path, numbers, **kw):
        exported.append(tuple(numbers))
        return path.with_name("bundle.loup")

    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=ElementEngine, probe=lambda p: None,
                     ensure_bundle=ensure_bundle)
    sim = loupmd.Simulation(atoms, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=temperature_K,
                                                                       friction_per_fs=0.01), seed=1, elements=elements)
    sim.exported = exported
    return sim


def _row(n, spacing=2.5):
    return Atoms(numbers=[A] * n, positions=[[spacing * k, 0, 0] for k in range(n)], cell=[spacing * n, 10, 10],
                 pbc=True)


@pytest.mark.parametrize("dmu_kT", [0.0, 1.0])
def test_transmute_composition_follows_the_chemical_potential(tmp_path, dmu_kT):
    """Ideal solution with equal element energies: x_Au = 1 / (1 + exp(-dmu / kT)), 0.5 at dmu = 0."""
    kT = units.kB * 300.0
    ElementEngine.eps = {A: -3.0, B: -3.0}
    sim = _transmute_sim(tmp_path, _row(12), elements=["Au"])
    move = mc.Transmute(species=["Cu", "Au"], attempts=200, mu={"Au": dmu_kT * kT})
    fractions = []
    for block in range(40):
        mc.transmute(sim, move, seed=100 + block)
        fractions.append(float((sim.atoms.numbers == B).mean()))
    blocks = np.array(fractions[5:])
    mean, error = blocks.mean(), blocks.std(ddof=1) / math.sqrt(len(blocks))
    exact = 1.0 / (1.0 + math.exp(-dmu_kT))
    print(f"dmu {dmu_kT} kT: x_Au {mean:.4f} +- {error:.4f}, exact {exact:.4f}")
    assert abs(mean - exact) <= 4.0 * error
    assert sim.exported == [(A, B)]                      # one bundle, with the element named up front


def test_transmute_keeps_the_kinetic_energy_and_the_engine_holds_the_last_composition(tmp_path):
    from ase.data import atomic_masses

    ElementEngine.eps = {A: 0.0, B: -10.0}                # Au is much lower: transmutes to it are taken
    at = _row(6)
    at.set_velocities(np.random.default_rng(2).normal(0.0, 0.01, (6, 3)))
    sim = _transmute_sim(tmp_path, at, elements=[B])
    sim.run(steps=1)
    before = sim.atoms
    result = mc.transmute(sim, mc.Transmute(species=[A, B], attempts=30), seed=4)
    after = sim.atoms
    assert result.counters.accepted >= 1 and (after.numbers == B).sum() >= 1
    engine, = SpringEngine.made
    assert np.array_equal(engine.numbers, after.numbers)
    assert np.allclose(engine.masses, after.get_masses())
    assert after.get_masses()[after.numbers == B] == pytest.approx(atomic_masses[B])
    ke_before = 0.5 * before.get_masses() * (before.get_velocities() ** 2).sum(axis=1)
    ke_after = 0.5 * after.get_masses() * (after.get_velocities() ** 2).sum(axis=1)
    assert ke_after == pytest.approx(ke_before)
    sim.run(steps=1)


def test_transmute_to_an_element_outside_the_bundle_is_refused_and_nothing_changes(tmp_path):
    ElementEngine.eps = {}
    sim = _transmute_sim(tmp_path, _row(4))
    sim.run(steps=1)
    with pytest.raises(PlanRefused, match="elements="):
        mc.transmute(sim, mc.Transmute(species=[A, B]), seed=1)
    assert (sim.atoms.numbers == A).all()


def test_a_rejected_transmute_block_puts_back_the_composition_and_the_state(tmp_path):
    ElementEngine.eps = {A: -10.0, B: 0.0}                # every transmute is uphill by 10 eV
    sim = _transmute_sim(tmp_path, _row(4), elements=[B])
    sim.run(steps=1)
    before = sim.atoms
    result = mc.transmute(sim, mc.Transmute(species=[A, B], attempts=5), seed=1)
    assert result.counters.accepted == 0
    engine, = SpringEngine.made
    assert (engine.numbers == A).all() and engine.log[-1] == "import_state"
    assert np.allclose(sim.atoms.positions, before.positions)


def test_the_transmute_arguments_are_checked():
    assert mc.Transmute(species=["Cu", "Au"], mu={"Au": 0.1}).mu == ((79, 0.1),)
    for bad in ("CuAu", ["Cu"], ["Cu", "Cu"]):
        with pytest.raises(InputError):
            mc.Transmute(species=bad)
    with pytest.raises(InputError, match="not in Transmute.species"):
        mc.Transmute(species=["Cu", "Au"], mu={"Ag": 0.1})
    with pytest.raises(PlanRefused, match="redraw"):
        mc.Transmute(species=["Cu", "Au"], velocities="redraw")


# ------------------------------------------------------------------- displace and run(mc=...) (S6-T04)

def _spring_sim(tmp_path, directory=None, temperature_K=300.0, n=8, **output):
    from loupmd.config import Output

    checkpoint = tmp_path / "some.model"
    checkpoint.write_bytes(b"never unpickled here")
    SpringEngine.made = []
    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine, probe=lambda p: None,
                     ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"))
    at = Atoms("Cu" * n, positions=[[3.0 * k, 0, 0] for k in range(n)], cell=[3.0 * n, 10, 10], pbc=True)
    out = Output(str(tmp_path / directory), **output) if directory else None
    return loupmd.Simulation(at, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=temperature_K,
                                                                     friction_per_fs=0.01), seed=9, output=out)


def test_displace_samples_the_boltzmann_distribution_of_a_harmonic_core(tmp_path):
    """Detailed balance on the springs of the fake core (K = 2 eV/A^2): pure displace moves give each coordinate
    the variance kT / K."""
    from fake_core import K

    kT = units.kB * 300.0
    sim = _spring_sim(tmp_path)
    sim.start()
    engine, = SpringEngine.made
    sites = engine.sites.copy()
    move = mc.Displace(delta_A=0.2, attempts=400)
    samples = []
    for block in range(80):
        mc.displace(sim, move, seed=block)
        samples.append(((sim.atoms.positions - sites) ** 2).mean())
    blocks = np.array(samples[10:])
    mean, error = blocks.mean(), blocks.std(ddof=1) / math.sqrt(len(blocks))
    acceptance = sim.mc_counters["displace"].acceptance
    print(f"displace: <dx^2> {mean:.5f} +- {error:.5f} A^2, exact {kT / K:.5f}; acceptance {acceptance:.3f}")
    assert abs(mean - kT / K) <= 4.0 * error
    assert 0.2 < acceptance < 0.95


def test_run_with_mc_makes_the_moves_every_few_steps_and_records_them(tmp_path):
    from loupmd import provenance

    sim = _spring_sim(tmp_path, "run", thermo_every=5)
    sim.run(steps=20, mc=[mc.Displace(delta_A=0.05, every=5, attempts=3)])
    counters = sim.mc_counters["displace"]
    assert counters.attempted == 4 * 3                     # after steps 5, 10, 15 and 20
    record = provenance.collect(sim)
    assert record["mc"]["counters"]["displace"]["attempted"] == 12
    assert record["mc"]["moves"] == [{"move": "displace", "delta_A": 0.05, "every": 5, "attempts": 3,
                                      "adaptive": False}]
    steps = [int(row[0]) for row in __import__("loupmd").output.read_thermo(tmp_path / "run")[1]]
    assert steps == [0, 5, 10, 15, 20]
    sim.close()


def test_mc_counters_survive_a_resume_and_the_resumed_run_makes_the_same_attempts(tmp_path):
    move = mc.Displace(delta_A=0.05, every=4, attempts=5)
    straight = _spring_sim(tmp_path, "a", thermo_every=4, restart_every=8)
    straight.run(steps=16, mc=move)
    final = straight.atoms.positions
    counters = straight.mc_counters["displace"].as_dict()
    straight.close()

    first = _spring_sim(tmp_path, "b", thermo_every=4, restart_every=8)
    first.run(steps=8, mc=move)
    first.close()
    resumed = loupmd.Simulation.resume(tmp_path / "b", force_field=first.force_field)
    assert resumed.mc_counters["displace"].attempted == 10
    resumed.run(steps=8, mc=move)
    assert resumed.mc_counters["displace"].as_dict() == counters
    assert np.allclose(resumed.atoms.positions, final)
    resumed.close()


def test_run_with_mc_is_refused_without_a_thermostat_and_for_other_objects(tmp_path):
    from loupmd.config import Output  # noqa: F401

    sim = _spring_sim(tmp_path)
    with pytest.raises(InputError, match="Swap, Transmute or Displace"):
        sim.run(steps=2, mc="swap")
    checkpoint = tmp_path / "some.model"
    ff = loupmd.load(str(checkpoint), trusted=True, engine_factory=SpringEngine, probe=lambda p: None,
                     ensure_bundle=lambda path, numbers, **kw: path.with_name("bundle.loup"))
    nve = loupmd.Simulation(sim._atoms, ff, integrator=integrators.NVE(timestep_fs=1.0), seed=1)
    with pytest.raises(InputError, match="NVE has none"):
        nve.run(steps=2, mc=mc.Displace(delta_A=0.1))


def test_the_displace_arguments_are_checked():
    for bad in (0.0, -1.0, float("nan"), True):
        with pytest.raises(InputError):
            mc.Displace(delta_A=bad)
    with pytest.raises(PlanRefused, match="adaptive"):
        mc.Displace(delta_A=0.1, adaptive=True)
