"""``lm.optimize`` on the GPU (plan task S4-T10): the step counts of ASE's own optimisers driven by ``lm.calc``,
and what the optimiser's arithmetic costs beside the force calls at 5,000 atoms. LBFGS at fixed cell runs inside
the engine (``loup_minimize``, owner's decision O15); FIRE and cell relaxations run on host arrays."""
from __future__ import annotations

import numpy as np
import pytest
from ase.optimize import FIRE as AseFIRE
from ase.optimize import LBFGS as AseLBFGS
from gpu_support import srtio3

import loupmd
from loupmd import BackendError, LoupEngine, optimize


def _rattled(rep, seed=9, sigma=0.04):
    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(scale=sigma, size=at.positions.shape)
    return at


@pytest.mark.parametrize("record,ase_class", [(optimize.LBFGS(), AseLBFGS), (optimize.FIRE(), AseFIRE)],
                         ids=["lbfgs", "fire"])
def test_the_step_count_is_ase_s_within_two(model_path, record, ase_class):
    atoms = _rattled(3)                                              # 135 atoms
    force_field = loupmd.load(model_path, trusted=True)
    result = optimize.relax(force_field, atoms, record, fmax=0.05)
    reference = atoms.copy()
    reference.calc = loupmd.calc(model_path, trusted=True)
    ase_optimizer = ase_class(reference, logfile=None)
    ase_optimizer.run(fmax=0.05)
    ase_steps = ase_optimizer.get_number_of_steps()
    print(f"{type(record).__name__}: {result.steps} steps, ASE {ase_steps}; largest force {result.max_force:.4f} eV/A; "
          f"positions differ from ASE's by {np.abs(result.atoms.positions - reference.positions).max():.2e} A")
    assert result.converged and abs(result.steps - ase_steps) <= 2
    assert np.abs(result.atoms.positions - reference.positions).max() < 5e-3
    assert result.energy == pytest.approx(reference.get_potential_energy(), abs=1e-4 * len(atoms))


def test_the_optimiser_s_own_time_at_5000_atoms(model_path):
    atoms = _rattled(10, sigma=0.05)
    force_field = loupmd.load(model_path, trusted=True)
    optimize.relax(force_field, atoms, optimize.FIRE(), fmax=1e-3, steps=3)        # export, engine, tuning
    shares = {}
    for name, record in (("FIRE", optimize.FIRE()), ("LBFGS", optimize.LBFGS())):
        result = optimize.relax(force_field, atoms, record, fmax=1e-3, steps=40)
        shares[name] = result.optimizer_s / result.force_s
        print(f"{name}: {result.steps} steps, {result.force_s / result.force_calls * 1e3:.2f} ms per force call, "
              f"optimiser {result.optimizer_s / result.steps * 1e3:.3f} ms per step: {100 * shares[name]:.2f}% of "
              "the force calls")
    # The plan's criterion is 2% for both. LBFGS on the host took 17% after 40 steps (PLAN.md D30); it runs on the
    # device since.
    assert shares["FIRE"] < 0.02
    assert shares["LBFGS"] < 0.02


class HostOnly:
    """A force field without an engine to hand out: ``relax`` then takes LBFGS's steps on host arrays."""

    def __init__(self, force_field):
        self.evaluate = force_field.evaluate


@pytest.mark.parametrize("memory", [100, 4], ids=["memory-100", "memory-4"])
def test_lbfgs_on_the_device_takes_the_host_s_steps(model_path, memory):
    """The same relaxation inside the engine and on host arrays; with memory 4 the history is a ring that
    wraps several times."""
    atoms = _rattled(3)
    force_field = loupmd.load(model_path, trusted=True)
    record = optimize.LBFGS(memory=memory)
    device = optimize.relax(force_field, atoms, record, fmax=0.02)
    host = optimize.relax(HostOnly(force_field), atoms, record, fmax=0.02)
    seen = []
    watched = optimize.relax(force_field, atoms, record, fmax=0.02,
                             callback=lambda step, positions, energy, largest: seen.append((step, largest)))
    worst = np.abs(device.atoms.positions - host.atoms.positions).max()
    print(f"LBFGS memory {memory}: {device.steps} steps on the device, {host.steps} on the host; positions within "
          f"{worst:.1e} A; one step per call: {watched.steps} steps")
    assert device.converged and host.converged and device.steps == host.steps == watched.steps
    assert device.steps > 2 * memory or memory == 100
    assert worst < 1e-5 and device.energy == pytest.approx(host.energy, abs=1e-6 * len(atoms))
    assert [step for step, _ in seen] == list(range(device.steps + 1)) and seen[-1][1] < 0.02 <= seen[-2][1]
    assert np.abs(watched.atoms.positions - device.atoms.positions).max() < 1e-5


def test_minimize_continues_and_starts_anew(sto_engine):
    eng = sto_engine
    at = _rattled(3)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, None, at.cell.array)
    start = eng.minimize(0, fmax=0.02)
    assert (start.steps, start.total_steps, start.converged) == (0, 0, 0) and start.max_force_ev_a > 0.5
    whole = eng.minimize(1000, fmax=0.02)
    reference = eng.get_state()[0]
    assert whole.converged and whole.steps == whole.total_steps and whole.max_force_ev_a < 0.02
    assert whole.potential_energy_ev < start.potential_energy_ev
    again = eng.minimize(1000, fmax=0.02)                         # already there: nothing to do
    assert (again.steps, again.converged, again.total_steps) == (0, 1, whole.total_steps)

    eng.set_state(at.positions, None, at.cell.array)               # new positions: a new relaxation
    first = eng.minimize(5, fmax=0.02)
    rest = eng.minimize(1000, fmax=0.02)
    assert (first.steps, first.converged, first.total_steps) == (5, 0, 5)
    assert rest.converged and first.steps + rest.steps == rest.total_steps == whole.steps
    assert np.abs(eng.get_state()[0] - reference).max() < 1e-6

    fixed = np.zeros(len(at), dtype=bool)
    fixed[::5] = True
    eng.set_state(at.positions, None, at.cell.array)
    eng.set_fixed_atoms(fixed)
    held = eng.minimize(1000, fmax=0.02)
    positions, _, forces, _ = eng.get_state()
    assert held.converged and held.total_steps == held.steps                  # the fixed atoms started it anew
    assert np.array_equal(positions[fixed], at.positions[fixed])
    assert np.sqrt((forces[~fixed] ** 2).sum(axis=1).max()) == pytest.approx(held.max_force_ev_a, rel=1e-12)
    assert np.sqrt((forces[fixed] ** 2).sum(axis=1).max()) > held.max_force_ev_a   # they do not count

    for settings, reason in ((dict(fmax=0.0), "fmax_ev_a must be finite and positive, got 0 eV/A"),
                             (dict(memory=0), "memory must be from 1 to 1000 history pairs, got 0"),
                             (dict(maxstep_A=-1.0), "maxstep_a, damping and alpha must be finite and positive"),
                             (dict(alpha=float("nan")), "maxstep_a, damping and alpha must be finite and positive")):
        with pytest.raises(BackendError, match="loup_minimize: " + reason):
            eng.minimize(10, **settings)
    with pytest.raises(BackendError, match="loup_minimize: max_steps must not be negative, got -1"):
        eng.minimize(-1)


def test_the_list_check_may_follow_the_force_pass(sto_engine, monkeypatch):
    """The list check of a move either holds the force pass back (``LOUP_MIN_AHEAD=0``) or arrives with the next
    step's results, the force pass being run again where the move had outdated the list (``LOUP_MIN_AHEAD=1``);
    the engine chooses per step. A small skin and a strong rattle make atoms cross half the skin several times."""
    eng = sto_engine
    at = _rattled(3, sigma=0.12)
    runs = {}
    for mode in ("0", "1", None):
        if mode is None:
            monkeypatch.delenv("LOUP_MIN_AHEAD", raising=False)
        else:
            monkeypatch.setenv("LOUP_MIN_AHEAD", mode)
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.2)
        eng.set_state(at.positions, None, at.cell.array)
        stats = eng.minimize(1000, fmax=0.02)
        runs[mode] = (stats.steps, stats.rebuilds, stats.force_passes, stats.repeated_passes, bool(stats.converged),
                      eng.get_state()[0])
    held, ahead, chosen = runs["0"], runs["1"], runs[None]
    print("LBFGS, skin 0.2 A: " + "; ".join(
        f"{name}: {run[0]} steps, {run[1]} rebuilds, {run[2]} force passes, {run[3]} repeated"
        for name, run in (("check before the pass", held), ("check after it", ahead), ("the engine's choice", chosen)))
          + f"; positions within {max(np.abs(run[5] - held[5]).max() for run in (ahead, chosen)):.1e} A")
    assert held[4] and ahead[4] and chosen[4] and held[0] == ahead[0] == chosen[0]
    assert held[1] >= 2 and held[1] == ahead[1] == chosen[1]
    assert held[3] == 0 and held[2] == held[0] + 1
    assert ahead[3] == ahead[1] and ahead[2] == ahead[0] + 1 + ahead[3]
    assert chosen[3] <= chosen[1] and chosen[2] == chosen[0] + 1 + chosen[3]
    assert np.abs(ahead[5] - held[5]).max() < 1e-5 and np.abs(chosen[5] - held[5]).max() < 1e-5


def test_minimize_needs_positions(sto_bundle):
    eng = LoupEngine(sto_bundle)
    with pytest.raises(BackendError, match="loup_minimize: no system is set"):
        eng.minimize(10)
    at = srtio3(2)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    with pytest.raises(BackendError, match="loup_minimize: no positions or neighbour list"):
        eng.minimize(10)


def test_the_relaxed_lattice_constant_is_ase_s(model_path):
    """S4-T11: SrTiO3 3x3x3 strained by 2% and rattled; positions and cell relaxed together."""
    from ase.filters import FrechetCellFilter

    atoms = _rattled(3, sigma=0.02)
    atoms.set_cell(atoms.cell.array * 1.02, scale_atoms=True)
    result = optimize.relax(loupmd.load(model_path, trusted=True), atoms,
                            optimize.LBFGS(cell_filter=optimize.FrechetCell()), fmax=0.002, steps=400)
    reference = atoms.copy()
    reference.calc = loupmd.calc(model_path, trusted=True)
    ase_optimizer = AseLBFGS(FrechetCellFilter(reference), logfile=None)
    ase_optimizer.run(fmax=0.002, steps=400)
    mine = result.atoms.cell.cellpar()[:3] / 3.0
    theirs = reference.cell.cellpar()[:3] / 3.0
    print(f"cell relaxation: {result.steps} steps, ASE {ase_optimizer.get_number_of_steps()}; lattice constants "
          f"{np.round(mine, 5)} A, ASE {np.round(theirs, 5)} A; largest difference {np.abs(mine - theirs).max():.2e} A; "
          f"stress left {np.abs(result.atoms.get_stress()).max():.2e} eV/A^3")
    assert result.converged and np.abs(mine - theirs).max() < 1e-4
    assert 3.85 < mine.mean() < 3.99 and abs(mine.mean() - 3.905 * 1.02) > 0.01     # it moved off the strained cell
