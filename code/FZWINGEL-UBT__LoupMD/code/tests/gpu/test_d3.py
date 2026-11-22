"""The real-space two-body D3 term (plan task S6-D04, ``src/dispersion/d3_pair.cu``) against simple-dftd3 at the
same settings, for each damping, on NbCl5 and a molecular crystal (paracetamol), and the d3bj-mace preset against
the torch-dftd calculator ``mace_mp(dispersion=True)`` builds. Tolerances of the plan: 1e-6 eV/atom, 1e-5 eV/A,
1e-7 eV/A^3. Needs a GPU and a library with ``loup_d3_evaluate``; no model."""
from __future__ import annotations

import numpy as np
import pytest

from loupmd import _d3
from loupmd import dispersion as d
from loupmd.bench import suites
from loupmd.errors import BackendError, InputError

BOHR = _d3.BOHR
HARTREE = 27.211386245988
TOL_E, TOL_F, TOL_S = 1e-6, 1e-5, 1e-7
SPLIT_E_FRACTION = 0.05     # the split sum's energy error against the plain 40 bohr sum's


def _lib_or_skip():
    try:
        return _d3._lib()
    except BackendError as error:
        pytest.skip(str(error))


def _rattled(atoms, seed=1, sigma=0.05):
    atoms = atoms.copy()
    atoms.pbc = True
    atoms.positions += np.random.default_rng(seed).normal(0.0, sigma, atoms.positions.shape)
    return atoms


def _system(name):
    from ase.io import read

    if name == "nbcl5":
        try:
            return _rattled(read(suites.structure_file("nbcl5")))
        except InputError as error:
            pytest.skip(str(error))
    if name == "paracetamol":
        return _rattled(read(suites._SHIPPED / "paracetamol_cod2104364.cif"))
    if name == "srtio3":
        return _rattled(suites.srtio3(2))
    raise ValueError(name)


def _reference(atoms, record):
    """simple-dftd3 (LGPL, called as an external library) at the record's settings, with the three-body term
    (s9 = 1) when the record has it."""
    dftd3 = pytest.importorskip("dftd3.interface")
    p = record.parameters
    s9 = 1.0 if record.three_body else 0.0
    param = {"bj": lambda: dftd3.RationalDampingParam(s6=p["s6"], s8=p["s8"], a1=p["a1"], a2=p["a2"], s9=s9),
             "bjm": lambda: dftd3.ModifiedRationalDampingParam(s6=p["s6"], s8=p["s8"], a1=p["a1"], a2=p["a2"],
                                                               s9=s9),
             "zero": lambda: dftd3.ZeroDampingParam(s6=p["s6"], s8=p["s8"], rs6=p["rs6"], rs8=p["rs8"],
                                                    alp=p["alpha"], s9=s9),
             "zerom": lambda: dftd3.ModifiedZeroDampingParam(s6=p["s6"], s8=p["s8"], rs6=p["rs6"], rs8=p["rs8"],
                                                             alp=p["alpha"], bet=p["beta"], s9=s9)}[record.damping]()
    model = dftd3.DispersionModel(atoms.numbers, atoms.positions / BOHR, np.asarray(atoms.cell) / BOHR,
                                  np.array([True, True, True]))
    model.set_realspace_cutoff(disp2=record.pair_cutoff_bohr, disp3=record.three_body_cutoff_bohr,
                               cn=record.cn_cutoff_bohr)
    res = model.get_dispersion(param, grad=True)
    return (float(res["energy"]) * HARTREE, -np.asarray(res["gradient"]) * HARTREE / BOHR,
            np.asarray(res["virial"]) * HARTREE / atoms.get_volume())


def _compare(atoms, got, ref):
    e, f, s = ref
    n = len(atoms)
    de = abs(got["energy"] - e) / n
    df = float(np.abs(got["forces"] - f).max())
    ds = float(np.abs(got["stress"] - s).max())
    assert de <= TOL_E and df <= TOL_F and ds <= TOL_S, (de, df, ds)
    return de, df, ds


@pytest.mark.parametrize("system", ["nbcl5", "paracetamol", "srtio3"])
@pytest.mark.parametrize("damping", ["bj", "zero", "bjm", "zerom"])
def test_each_damping_agrees_with_simple_dftd3(system, damping):
    lib = _lib_or_skip()
    atoms = _system(system)
    record = d.resolve(d.Dispersion(damping=damping, long_range="none"), functional="pbe")
    got = _d3.evaluate(atoms, record, lib=lib)
    _compare(atoms, got, _reference(atoms, record))


def test_shorter_cutoffs_agree_with_simple_dftd3():
    """A pair cutoff below the CN cutoff and both shorter than the cell (SrTiO3 2x2x2 is 7.8 A, 14.8 bohr)."""
    lib = _lib_or_skip()
    atoms = _system("srtio3")
    record = d.resolve(d.Dispersion(pair_cutoff_bohr=20.0, cn_cutoff_bohr=30.0, long_range="none"),
                       functional="pbe")
    _compare(atoms, _d3.evaluate(atoms, record, lib=lib), _reference(atoms, record))


def test_d3bj_mace_agrees_with_the_torch_dftd_calculator_of_mace_mp():
    """mace_mp(dispersion=True) adds TorchDFTD3Calculator(damping="bj", xc="pbe", cutoff=40 bohr, cnthr 40 bohr);
    compared at float64 (mace_mp's default float32 would set the tolerance, not the term)."""
    torch = pytest.importorskip("torch")
    calc_mod = pytest.importorskip("torch_dftd.torch_dftd3_calculator")
    lib = _lib_or_skip()
    atoms = _system("paracetamol")
    record = d.resolve("d3bj-mace", functional="PBE")
    ref = calc_mod.TorchDFTD3Calculator(device="cpu", damping="bj", xc="pbe", cutoff=40.0 * BOHR,
                                        cnthr=40.0 * BOHR, dtype=torch.float64)
    ref_atoms = atoms.copy()
    ref_atoms.calc = ref
    from ase.stress import voigt_6_to_full_3x3_stress

    expected = (ref_atoms.get_potential_energy(), ref_atoms.get_forces(),
                voigt_6_to_full_3x3_stress(ref_atoms.get_stress()))
    _compare(atoms, _d3.evaluate(atoms, record, lib=lib), expected)


def test_per_atom_energies_the_energy_only_path_and_wrapping():
    lib = _lib_or_skip()
    atoms = _system("paracetamol")
    record = d.resolve("d3bj", functional="pbe")
    full = _d3.evaluate(atoms, record, per_atom=True, lib=lib)
    assert abs(full["energies"].sum() - full["energy"]) < 1e-9 * max(1.0, abs(full["energy"]))
    only = _d3.evaluate(atoms, record, forces=False, stress=False, lib=lib)
    assert abs(only["energy"] - full["energy"]) < 1e-9 * abs(full["energy"])
    moved = atoms.copy()                       # atoms outside the cell, by whole lattice vectors
    moved.positions += np.random.default_rng(3).integers(-2, 3, (len(atoms), 3)) @ np.asarray(atoms.cell)
    again = _d3.evaluate(moved, record, lib=lib)
    assert abs(again["energy"] - full["energy"]) / len(atoms) < 1e-8
    assert np.abs(again["forces"] - full["forces"]).max() < 1e-6


def test_the_switch_is_smooth_and_its_forces_are_the_gradient():
    """smoothing=w: forces and stress are the derivatives of the switched energy (central differences)."""
    lib = _lib_or_skip()
    atoms = _system("srtio3")
    record = d.resolve(d.Dispersion(pair_cutoff_bohr=20.0, cn_cutoff_bohr=20.0, smoothing=6.0, long_range="none"),
                       functional="pbe")
    got = _d3.evaluate(atoms, record, lib=lib)
    plain = _d3.evaluate(atoms, d.resolve(d.Dispersion(pair_cutoff_bohr=20.0, cn_cutoff_bohr=20.0,
                                                       long_range="none"), functional="pbe"), lib=lib)
    assert got["energy"] > plain["energy"]           # the switch removes attraction near the cutoff
    h = 1e-3
    for atom, axis in ((0, 0), (7, 2), (21, 1)):
        up, down = atoms.copy(), atoms.copy()
        up.positions[atom, axis] += h
        down.positions[atom, axis] -= h
        fd = -(_d3.evaluate(up, record, forces=False, stress=False, lib=lib)["energy"] -
               _d3.evaluate(down, record, forces=False, stress=False, lib=lib)["energy"]) / (2 * h)
        assert abs(fd - got["forces"][atom, axis]) < 2e-5, (atom, axis, fd, got["forces"][atom, axis])
    def fd_stress_error(rec, analytic, eps=1e-3):
        strained = []
        for sign in (1, -1):
            a = atoms.copy()
            a.set_cell(np.asarray(atoms.cell) @ (np.eye(3) + sign * eps * np.diag([1.0, 0.0, 0.0])), scale_atoms=True)
            strained.append(_d3.evaluate(a, rec, forces=False, stress=False, lib=lib)["energy"])
        return abs((strained[0] - strained[1]) / (2 * eps) / atoms.get_volume() - analytic[0, 0])

    # the bound: float32 rounding of the pair energies (1e-7 of the total) over the strain step. The unswitched sum
    # is no control here: straining moves pairs across its hard cutoff, and its energy jumps.
    switched = fd_stress_error(record, got["stress"])
    bound = 1e-7 * abs(got["energy"]) / (2 * 1e-3 * atoms.get_volume())
    print(f"switch: stress xx vs central difference {switched:.1e} eV/A^3 (rounding bound {bound:.1e})")
    assert switched <= bound


# ----------------------------------------------------------------------------------- the three-body term (S6-D08)

@pytest.mark.parametrize("system,damping", [("nbcl5", "bj"), ("paracetamol", "bj"), ("srtio3", "bj"),
                                            ("srtio3", "zero"), ("paracetamol", "zerom")])
def test_the_three_body_term_agrees_with_simple_dftd3(system, damping):
    """d3bj-atm's 20 bohr three-body cutoff; SrTiO3 2x2x2 (14.8 bohr) is shorter than it, so triangles hold two
    images of one atom."""
    lib = _lib_or_skip()
    atoms = _system(system)
    record = d.resolve(d.Dispersion(damping=damping, three_body=True, three_body_cutoff_bohr=20.0,
                                    long_range="none"), functional="pbe")
    got = _d3.evaluate(atoms, record, lib=lib)
    two = _d3.evaluate(atoms, d.resolve(d.Dispersion(damping=damping, long_range="none"), functional="pbe"), lib=lib)
    ref = _reference(atoms, record)
    de, df, ds = _compare(atoms, got, ref)
    share = (got["energy"] - two["energy"]) / abs(two["energy"])
    print(f"{system} {damping}: three-body {1e3 * (got['energy'] - two['energy']) / len(atoms):+.3f} meV/atom "
          f"({100 * share:.1f}% of the pair term); vs simple-dftd3 {de:.1e} eV/atom, {df:.1e} eV/A, {ds:.1e} eV/A^3")
    assert share > 0.0                                    # ATM is repulsive in these crystals (design section 3.2)


def test_the_three_body_term_at_40_bohr_agrees_with_simple_dftd3():
    """d3-reference's cutoffs (60 bohr pairs, 40 bohr three-body and coordination numbers): several chunks of
    neighbours per atom."""
    lib = _lib_or_skip()
    atoms = _system("srtio3")
    record = d.resolve("d3-reference", functional="pbe")
    _compare(atoms, _d3.evaluate(atoms, record, lib=lib), _reference(atoms, record))


def test_the_three_body_term_per_atom_energy_only_and_switched():
    lib = _lib_or_skip()
    atoms = _system("srtio3")
    record = d.resolve(d.Dispersion(three_body=True, three_body_cutoff_bohr=20.0, long_range="none"),
                       functional="pbe")
    full = _d3.evaluate(atoms, record, per_atom=True, lib=lib)
    assert abs(full["energies"].sum() - full["energy"]) < 1e-9 * abs(full["energy"])
    only = _d3.evaluate(atoms, record, forces=False, stress=False, lib=lib)
    assert abs(only["energy"] - full["energy"]) < 1e-9 * abs(full["energy"])
    switched = d.resolve(d.Dispersion(three_body=True, three_body_cutoff_bohr=20.0, pair_cutoff_bohr=20.0,
                                      cn_cutoff_bohr=20.0, smoothing=6.0, long_range="none"), functional="pbe")
    got = _d3.evaluate(atoms, switched, lib=lib)
    h = 1e-3
    for atom, axis in ((0, 0), (7, 2), (21, 1)):
        up, down = atoms.copy(), atoms.copy()
        up.positions[atom, axis] += h
        down.positions[atom, axis] -= h
        fd = -(_d3.evaluate(up, switched, forces=False, stress=False, lib=lib)["energy"] -
               _d3.evaluate(down, switched, forces=False, stress=False, lib=lib)["energy"]) / (2 * h)
        assert abs(fd - got["forces"][atom, axis]) < 2e-5, (atom, axis, fd, got["forces"][atom, axis])


def test_what_is_not_built_is_refused_by_the_library():
    lib = _lib_or_skip()
    atoms = _system("srtio3")
    record = d.resolve("d3bj", functional="pbe")
    atoms.pbc = False
    with pytest.raises(InputError, match="periodic cell"):
        _d3.evaluate(atoms, record, lib=lib)
    atoms.pbc = True
    atoms.numbers[0] = 99
    with pytest.raises(BackendError, match="no reference C6 for atomic number 99"):
        _d3.evaluate(atoms, record, lib=lib)


# ------------------------------------------------------------------------------------- inside the engine's passes

def _engine_pair(sto_bundle, atoms, record, skin=0.5):
    """Two engines on the test model: one with the D3 term, one without."""
    from loupmd import LoupEngine

    plain, with_d3 = LoupEngine(sto_bundle), LoupEngine(sto_bundle)
    for eng in (plain, with_d3):
        eng.set_system(atoms.numbers, atoms.get_masses(), skin=skin)
    try:
        with_d3.set_dispersion(record)
    except BackendError as error:
        pytest.skip(str(error))
    return plain, with_d3


def _oxide(rep=3, seed=5):
    atoms = suites.srtio3(rep)
    atoms.positions += np.random.default_rng(seed).normal(scale=0.03, size=atoms.positions.shape)
    return atoms


def test_the_engine_adds_the_term_to_energy_forces_stress_and_per_atom_energies(sto_bundle):
    lib = _lib_or_skip()
    atoms = _oxide()
    record = d.resolve("d3bj", functional="pbe")
    plain, with_d3 = _engine_pair(sto_bundle, atoms, record)
    alone = _d3.evaluate(atoms, record, per_atom=True, lib=lib)
    cell = atoms.cell.array
    for eng in (plain, with_d3):
        eng.set_state(atoms.positions, None, cell)
    e0, f0, s0 = plain.evaluate(atoms.positions, cell)
    e1, f1, s1 = with_d3.evaluate(atoms.positions, cell)
    spread = np.abs(plain.evaluate(atoms.positions, cell)[1] - f0).max()      # the model's own repeat spread
    n = len(atoms)
    # the gate's energy floor (0.01 meV/atom): float32 rounding of the model's total, about 1e-7 of it, comes near 1e-6
    assert abs(e1 - (e0 + alone["energy"])) / n < 1e-5
    assert np.abs(f1 - (f0 + alone["forces"])).max() < max(4 * spread, 1e-5)
    assert np.abs(s1 - (s0 + alone["stress"])).max() < 1e-7
    _, _, _, a0 = plain.evaluate_per_atom(atoms.positions, cell)
    _, _, _, a1 = with_d3.evaluate_per_atom(atoms.positions, cell)
    assert np.abs(a1 - (a0 + alone["energies"])).max() < 1e-5
    assert abs(with_d3.evaluate_energy(atoms.positions, cell) - plain.evaluate_energy(atoms.positions, cell)
               - alone["energy"]) / n < 1e-5           # the same floor: 1.05e-6 eV/atom seen once (status 6.33)
    with_d3.set_dispersion(None)                                              # removed again
    assert abs(with_d3.evaluate(atoms.positions, cell)[0] - e0) / n < 1e-5


@pytest.mark.parametrize("variable_cell", [False, True], ids=["fixed cell", "deforming cell"])
def test_the_md_step_carries_the_term(sto_bundle, monkeypatch, variable_cell):
    """200 captured NVE steps (several list rebuilds; with LOUP_DEBUG_CELL_RATE the cell grows 0.02% per step on
    the device, so the term must read the device's cell): the energy and forces on the device at the end are the
    model's plus the term alone at the final positions and cell."""
    from gpu_support import maxwell_velocities

    from loupmd import _core

    lib = _lib_or_skip()
    if variable_cell:
        monkeypatch.setenv("LOUP_VARIABLE_CELL", "1")
        monkeypatch.setenv("LOUP_DEBUG_CELL_RATE", "2e-4")
    atoms = _oxide()
    record = d.resolve("d3bj", functional="pbe")
    plain, with_d3 = _engine_pair(sto_bundle, atoms, record)
    with_d3.set_state(atoms.positions, maxwell_velocities(atoms, 600.0, 3), atoms.cell.array)
    stats = with_d3.run(200, _core.integrator(_core.LOUP_NVE, 1.0))
    positions, _, forces, energy = with_d3.get_state()
    cell = with_d3.get_cell()
    monkeypatch.delenv("LOUP_VARIABLE_CELL", raising=False)
    monkeypatch.delenv("LOUP_DEBUG_CELL_RATE", raising=False)
    if variable_cell:
        assert abs(np.linalg.det(cell) / atoms.get_volume() - 1.0002 ** 600) < 1e-6
    final = atoms.copy()
    final.positions, final.cell = positions, cell
    plain.set_state(positions, None, cell)
    e0, f0, _ = plain.evaluate(positions, cell)
    alone = _d3.evaluate(final, record, stress=False, lib=lib)
    print(f"{'deforming' if variable_cell else 'fixed'} cell: {stats.rebuilds} rebuilds, D3 {alone['energy']:.4f} eV")
    assert stats.rebuilds >= 1
    assert abs(energy - (e0 + alone["energy"])) / len(atoms) < 1e-5
    assert np.abs(forces - (f0 + alone["forces"])).max() < 1e-4


def test_lm_md_with_the_three_body_preset_in_npt_reports_its_cost(model_path, tmp_path):
    """lm.md(dispersion="d3bj-atm") under the barostat: the run completes, the report names the term and its measured
    cost per evaluation with the three-body share (PLAN.md S6-D08), and the term moves the pressure."""
    import loupmd

    _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    atoms = _oxide()
    result = loupmd.md(atoms, model=ff, ensemble="NPT", temperature_K=300.0, pressure_GPa=0.0, timestep_fs=1.0,
                       steps=100, seed=2, dispersion="d3bj-atm", output=str(tmp_path / "run"))
    cost = result.metadata["dispersion"]["cost"]
    print(f"d3bj-atm on SrTiO3 3x3x3 ({len(atoms)} atoms): {cost}")
    assert cost["ms_per_evaluation"] > 0.0 and cost["three_body_ms"] > 0.0
    assert "three-body term to 20 bohr" in result.summary or "three-body term" in result.summary
    assert "of which the three-body term" in result.summary
    assert np.isfinite(result.simulation.atoms.get_volume())


# ----------------------------------------------------------------------------- loupmd validate --dispersion (S6-D10)

@pytest.mark.parametrize("preset", list(d.PRESETS))
def test_loupmd_validate_dispersion_passes_for_every_preset(preset, tmp_path, capsys):
    from ase.io import write

    from loupmd.cli import main

    pytest.importorskip("dftd3.interface")
    _lib_or_skip()
    path = tmp_path / "sto.extxyz"
    write(path, _system("srtio3"))
    code = main(["validate", "--dispersion", preset, "--model", "omat0-medium", "--structure", str(path)])
    out = capsys.readouterr().out
    print(out.splitlines()[-2])
    assert code == 0 and "dispersion check PASSED" in out, out


def test_the_dispersion_check_fails_for_a_wrong_parameter_set():
    from dataclasses import replace

    from loupmd.validate import dispersion as check

    pytest.importorskip("dftd3.interface")
    lib = _lib_or_skip()
    record = d.resolve("d3bj", functional="pbe")
    wrong = replace(record, parameters=dict(record.parameters, a2=record.parameters["a2"] + 0.05))
    result = check.check([("srtio3", _system("srtio3"))], record, lib=lib, reference_record=wrong)
    assert not result["passed"]
    assert result["rows"][0]["deviation"]["energy_eV_atom"] > 100 * check.BOUNDS["energy_eV_atom"]
    assert check.check([("srtio3", _system("srtio3"))], record, lib=lib)["passed"]


# ------------------------------------------------------------------- the ASE calculator and Monte Carlo (S6-D09)

def test_the_ase_calculator_adds_the_term(model_path):
    import loupmd

    lib = _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    atoms = _oxide()
    record = d.resolve("d3bj", functional="pbe")
    alone = _d3.evaluate(atoms, record, lib=lib)
    a, b = atoms.copy(), atoms.copy()
    a.calc, b.calc = loupmd.calc(ff), loupmd.calc(ff, dispersion="d3bj")
    e0, f0, s0 = a.get_potential_energy(), a.get_forces(), a.get_stress(voigt=False)
    e1, f1, s1 = b.get_potential_energy(), b.get_forces(), b.get_stress(voigt=False)
    n = len(atoms)
    assert abs(e1 - (e0 + alone["energy"])) / n < 1e-5
    assert np.abs(f1 - (f0 + alone["forces"])).max() < 1e-4
    assert np.abs(s1 - (s0 + alone["stress"])).max() < 1e-6
    a.calc.reset()                                     # the shared engine loses the term again for the plain one
    assert abs(a.get_potential_energy() - e0) / n < 1e-5


def test_relaxations_take_exactly_their_own_term(model_path):
    """lm.optimize.relax with dispersion= relaxes MACE + D3 (the on-device LBFGS and the host FIRE alike: the
    calculator with the same term finds the relaxed forces small); without it no term the shared engine held from a
    calculator is used."""
    import loupmd

    _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    atoms = _oxide()
    with_d3, plain = loupmd.calc(ff, dispersion="d3bj"), loupmd.calc(ff)
    for optimizer in (loupmd.optimize.LBFGS(), loupmd.optimize.FIRE()):
        relaxed = loupmd.optimize.relax(ff, atoms, optimizer, fmax=0.02, steps=400, dispersion="d3bj")
        assert relaxed.converged, (type(optimizer).__name__, relaxed)
        check = relaxed.atoms.copy()
        check.calc = with_d3
        assert np.abs(check.get_forces()).max() < 0.03
        assert abs(check.get_potential_energy() - relaxed.energy) / len(atoms) < 1e-5
    probe = atoms.copy()
    probe.calc = with_d3
    probe.get_potential_energy()                                  # the shared engine now holds the term
    bare = loupmd.optimize.relax(ff, atoms, steps=0)
    reference = atoms.copy()
    reference.calc = plain
    assert abs(bare.energy - reference.get_potential_energy()) / len(atoms) < 1e-5


def test_swap_monte_carlo_with_the_term(model_path):
    """Energy-only move energies include the term (against the full call, 0.01 kT at 300 K); a block of swaps on a
    Simulation with dispersion runs and the run goes on."""
    import gc

    from ase import units
    from ase.build import bulk

    import loupmd
    from loupmd import integrators, mc

    _lib_or_skip()
    at = bulk("Cu", "fcc", a=3.75, cubic=True).repeat((4, 4, 4))
    rng = np.random.default_rng(2)
    numbers = at.numbers.copy()
    numbers[rng.choice(len(at), len(at) // 4, replace=False)] = 79
    at.numbers = numbers
    at.positions += rng.normal(0.0, 0.03, at.positions.shape)
    ff = loupmd.load(model_path, trusted=True)
    sim = loupmd.Simulation(at, ff, integrator=integrators.Langevin(timestep_fs=1.0, temperature_K=300.0,
                                                                    friction_per_fs=0.01),
                            seed=1, capacity="whole", dispersion="d3bj")
    try:
        sim.run(steps=10)
        engine = sim._engine
        assert engine.dispersion is not None
        positions = engine.get_state()[0]
        cell = at.cell.array
        cu, au = np.flatnonzero(at.numbers == 29), np.flatnonzero(at.numbers == 79)
        worst = 0.0
        for _ in range(5):
            i, j = rng.choice(cu), rng.choice(au)
            trial = positions.copy()
            trial[[i, j]] = positions[[j, i]]
            worst = max(worst, abs(engine.evaluate_energy(trial, cell) -
                                   engine.evaluate(trial, cell, compute_stress=False)[0]))
        engine.evaluate(positions, cell, compute_stress=False)
        result = mc.swap(sim, mc.Swap(pairs=[("Cu", "Au")], attempts=100), seed=5)
        kT = units.kB * 300.0
        print(f"swap with D3 on {len(at)} atoms: move energies within {worst:.2e} eV ({worst / kT:.1e} kT), "
              f"{result.counters.accepted} of 100 accepted")
        assert worst <= 0.01 * kT and result.counters.attempted == 100
        sim.run(steps=10)
        assert np.isfinite(sim.atoms.get_potential_energy())
    finally:
        sim.close()
        del sim
        gc.collect()


def test_the_tiled_execution_carries_the_term(model_path):
    """S6-D09 / D76: a tiled Simulation (SrTiO3 10x10x10, 5,000 atoms in tiles of 2,000 receivers) with d3bj runs the
    whole-system term beside the tiled model; 20 NVE steps follow the whole-system run with the term."""
    import gc

    import loupmd
    from loupmd import integrators
    from loupmd.config import CapacityConfig

    _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    base = suites.srtio3(10)
    base.positions += np.random.default_rng(7).normal(scale=0.03, size=base.positions.shape)
    out = {}
    for mode, cap in (("whole", "whole"), ("tiled", CapacityConfig(mode="tiled", receivers=2000))):
        at = base.copy()
        sim = loupmd.Simulation(at, ff, integrator=integrators.NVE(timestep_fs=1.0), seed=1, capacity=cap,
                                dispersion="d3bj")
        try:
            sim.run(steps=20)
            out[mode] = (sim.atoms.positions.copy(), sim.atoms.get_potential_energy(),
                         getattr(sim._engine, "tiles", 0), sim.dispersion_cost)
        finally:
            sim.close()
            del sim
            gc.collect()
    (pw, ew, _, _), (pt, et, tiles, cost) = out["whole"], out["tiled"]
    dx, de = np.abs(pt - pw).max(), abs(et - ew) / len(base)
    print(f"tiled with d3bj: {tiles} tiles, vs whole after 20 NVE steps dx {dx:.2e} A, dE {de:.2e} eV/atom; {cost}")
    assert tiles >= 3 and dx <= 1e-5 and de <= 1e-5          # the gate's energy floor; float32 rounding of the total


# ------------------------------------------------------------------------------------------ the split sum (S6-D06)

def _split(rc=20.0, **fields):
    return d.resolve(d.Dispersion(pair_cutoff_bohr=rc, cn_cutoff_bohr=40.0, long_range="split", **fields),
                     functional="pbe")


def _long_sum(atoms, lib):
    """simple-dftd3 at 150 bohr plus the uniform tail beyond it, estimated from the 40 -> 150 bohr difference
    (E(R) - E_inf ~ R^-3): the infinite sum's energy; forces and stress of the 150 bohr sum; and the plain sum."""
    e150, f150, s150 = _reference(atoms, d.resolve(d.Dispersion(pair_cutoff_bohr=150.0, long_range="none"),
                                                   functional="pbe"))
    e40 = _d3.evaluate(atoms, d.resolve(d.Dispersion(long_range="none"), functional="pbe"), lib=lib)
    x = (40.0 / 150.0) ** 3
    return e150 + (e150 - e40["energy"]) * x / (1 - x), f150, s150, e40


@pytest.mark.parametrize("system", ["paracetamol", "srtio3", "nbcl5"])
def test_the_split_sum_reaches_the_infinite_sum(system):
    """At a 20 bohr real-space cutoff the split sum is closer to the infinite sum than the plain 40 bohr sum, in
    energy, forces and stress."""
    lib = _lib_or_skip()
    atoms = _system(system)
    n = len(atoms)
    e, f, s, plain = _long_sum(atoms, lib)
    got = _d3.evaluate(atoms, _split(), lib=lib)
    errs = [(abs(r["energy"] - e) / n, float(np.abs(r["forces"] - f).max()), float(np.abs(r["stress"] - s).max()))
            for r in (got, plain)]
    print(f"{system}: split 20 bohr {errs[0]}, plain 40 bohr {errs[1]} (eV/atom, eV/A, eV/A^3)")
    assert errs[0][0] < SPLIT_E_FRACTION * errs[1][0]
    assert errs[0][1] <= max(errs[1][1], TOL_F) and errs[0][2] <= max(errs[1][2], TOL_S)


def test_the_mesh_matches_the_direct_k_sum(monkeypatch):
    lib = _lib_or_skip()
    atoms = _system("paracetamol")
    n = len(atoms)
    monkeypatch.setenv("LOUP_D3_KSUM", "direct")
    direct = _d3.evaluate(atoms, _split(), lib=lib)
    monkeypatch.delenv("LOUP_D3_KSUM")
    mesh = _d3.evaluate(atoms, _split(), lib=lib)
    de = abs(mesh["energy"] - direct["energy"]) / n
    df = float(np.abs(mesh["forces"] - direct["forces"]).max())
    ds = float(np.abs(mesh["stress"] - direct["stress"]).max())
    print(f"mesh (order 8, 0.8 A) vs direct k sum: {de:.1e} eV/atom, {df:.1e} eV/A, {ds:.1e} eV/A^3")
    assert de <= TOL_E and df <= TOL_F and ds <= TOL_S


@pytest.mark.parametrize("ksum", ["mesh", "direct"])
def test_the_split_sums_forces_and_stress_are_the_gradient(monkeypatch, ksum):
    """Central differences of the energy: a check of signs and factors. Float32 pair energies make the difference
    quotient noisy at the 1e-5 eV/A level (status 6.31), so precision is checked against simple-dftd3 above."""
    lib = _lib_or_skip()
    if ksum == "direct":
        monkeypatch.setenv("LOUP_D3_KSUM", "direct")
    atoms = _system("srtio3")
    record = _split()
    got = _d3.evaluate(atoms, record, lib=lib)
    h, worst = 1e-2, 0.0
    for i in (0, 7, 23):
        for a in range(3):
            up, down = atoms.copy(), atoms.copy()
            up.positions[i, a] += h
            down.positions[i, a] -= h
            fd = -(_d3.evaluate(up, record, forces=False, stress=False, lib=lib)["energy"] -
                   _d3.evaluate(down, record, forces=False, stress=False, lib=lib)["energy"]) / (2 * h)
            worst = max(worst, abs(fd - got["forces"][i, a]))
    eps, sw = 1e-3, 0.0
    for a, b in ((0, 0), (2, 2), (0, 1)):
        e = []
        for sign in (1, -1):
            strain = np.eye(3)
            strain[a, b] += sign * eps / (1 if a == b else 2)
            strain[b, a] += 0 if a == b else sign * eps / 2
            x = atoms.copy()
            x.set_cell(np.asarray(atoms.cell) @ strain, scale_atoms=True)
            e.append(_d3.evaluate(x, record, forces=False, stress=False, lib=lib)["energy"])
        sw = max(sw, abs((e[0] - e[1]) / (2 * eps) / atoms.get_volume() - got["stress"][a, b]))
    only = _d3.evaluate(atoms, record, forces=False, stress=False, per_atom=True, lib=lib)
    print(f"split ({ksum}): forces vs central differences {worst:.1e} eV/A, stress {sw:.1e} eV/A^3")
    assert worst <= 1e-4 and sw <= 1e-5
    assert abs(only["energy"] - got["energy"]) <= 1e-9 * abs(got["energy"])
    assert abs(only["energies"].sum() - only["energy"]) <= 1e-7 * abs(got["energy"])     # rounding: 1.4e-8 seen


# ------------------------------------------------------------------------ the automatic choice (S6-D07, D80)

def _auto():
    return d.resolve(d.Dispersion(), functional="pbe")


@pytest.mark.parametrize("system", ["paracetamol", "srtio3", "nbcl5"])
def test_auto_chooses_the_fastest_checked_method(system):
    """On each benchmark system the setup check keeps the plain sum (its own bound) and picks a kept candidate;
    timed again on their own, the chosen one is the fastest of the kept ones within 5%."""
    import time

    lib = _lib_or_skip()
    atoms = _system(system)
    record = _auto()
    used, choice = d.choose(record, atoms, evaluate=_d3.evaluate)
    rows = {row["name"]: row for row in choice["candidates"]}
    for row in rows.values():
        print(system, row["name"], {k: row.get(k) for k in ("energy_meV_per_atom", "max_force_eV_per_A",
                                                                "stress_GPa", "ms", "kept", "why")})
    print(f"{system}: chosen {choice['chosen']}, setup {choice['setup_s']} s")
    assert set(rows) == {"none 40", "split 20", "split 25"}
    assert rows["none 40"]["kept"] and rows[choice["chosen"]]["kept"]
    assert used.long_range == rows[choice["chosen"]]["long_range"]
    assert used.pair_cutoff_bohr == rows[choice["chosen"]]["pair_cutoff_bohr"]
    records = dict(d.candidates(record)[0])
    kept = [name for name, row in rows.items() if row["kept"]]
    again = {name: [] for name in kept}
    for _ in range(3):
        for name in kept:
            again[name].append(_d3.evaluate(atoms, records[name], repeat=10, lib=lib)["ms"])
        time.sleep(0.1)
    again = {name: min(v) for name, v in again.items()}
    print(f"{system}: timed again {again}")
    assert again[choice["chosen"]] <= 1.05 * min(again.values())


def test_auto_drops_a_mesh_far_too_coarse():
    """A candidate made wrong on purpose (a 12 bohr real-space cutoff on a 6 A mesh) is dropped with the reason."""
    from dataclasses import replace

    _lib_or_skip()
    atoms = _rattled(suites.srtio3(6))
    record = _auto()
    coarse = replace(record, long_range="split", pair_cutoff_bohr=12.0, mesh_spacing_A=6.0, auto_methods=None)
    used, choice = d.choose(record, atoms, evaluate=_d3.evaluate, extra=[("split 12, 6 A mesh", coarse)])
    row = {r["name"]: r for r in choice["candidates"]}["split 12, 6 A mesh"]
    print(row)
    assert row["kept"] is False and "larger than the plain sum's" in row["why"]
    assert choice["chosen"] != "split 12, 6 A mesh" and used != coarse


def test_lm_md_chooses_the_long_range_method_at_setup(model_path, tmp_path):
    """lm.md with the preset 'd3bj' (long_range="auto"): the engine gets the chosen method; the metadata and the
    report list every candidate; a recheck on request gives a choice again."""
    import loupmd

    _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    result = loupmd.md(_oxide(), model=ff, temperature_K=300.0, timestep_fs=1.0, steps=20, seed=2,
                       dispersion="d3bj", output=str(tmp_path / "run"))
    entry = result.metadata["dispersion"]
    choice = entry["long_range_choice"]
    rows = {row["name"]: row for row in choice["candidates"]}
    assert set(rows) == {"none 40", "split 20", "split 25"} and choice["left_out"] == []
    assert entry["long_range_chosen_by"] == "automatic, at setup"
    assert entry["long_range_used"] == rows[choice["chosen"]]["long_range"]
    assert result.simulation._engine.dispersion.long_range == entry["long_range_used"]
    assert "long range checked against the split sum at 30 bohr" in result.summary
    assert f"{choice['chosen']} (chosen)" in result.summary
    again = result.simulation.recheck_dispersion()
    assert again["chosen"] in rows
    import json

    record = json.loads((tmp_path / "run" / "simulation.json").read_text())
    assert d.parse(record["dispersion"]).long_range == "auto"        # a resume checks again


def test_lm_md_runs_the_split_sum_in_npt(model_path, tmp_path):
    """lm.md with long_range="split" under the barostat: the run completes and the summary names the method."""
    import loupmd

    _lib_or_skip()
    ff = loupmd.load(model_path, trusted=True)
    result = loupmd.md(_oxide(), model=ff, ensemble="NPT", temperature_K=300.0, pressure_GPa=0.0, timestep_fs=1.0,
                       steps=50, seed=2, dispersion=loupmd.Dispersion(pair_cutoff_bohr=20.0, long_range="split"),
                       output=str(tmp_path / "run"))
    assert "long range: split (the user)" in result.summary
    assert result.metadata["dispersion"]["long_range"] == "split"
    assert np.isfinite(result.simulation.atoms.get_volume())
