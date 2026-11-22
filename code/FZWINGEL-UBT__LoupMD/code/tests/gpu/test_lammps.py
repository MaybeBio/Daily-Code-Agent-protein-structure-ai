"""The LAMMPS styles of lammps/ (pair_style loupmd and loupmd/kk, run_style loupmd) against the Python engine.

Needs a LAMMPS executable built with the package ML-LOUPMD against the library under test: LOUPMD_LMP=/path/to/lmp
(the tests are skipped without it). The Kokkos style is tested when that executable has the KOKKOS package."""
from __future__ import annotations

import functools
import os
import subprocess

import numpy as np
import pytest
from gpu_support import find_model, srtio3

from loupmd import LoupEngine, ensure_loup_bundle

LMP = os.environ.get("LOUPMD_LMP", "")
pytestmark = pytest.mark.skipif(not os.path.exists(LMP), reason="set LOUPMD_LMP to an lmp built with ML-LOUPMD")
BAR = 1.602176634e6  # eV/A^3 in bar
KK = ["-k", "on", "g", "1", "-sf", "kk"]


@functools.lru_cache(maxsize=None)
def _packages() -> str:
    return subprocess.run([LMP, "-h"], capture_output=True, text=True).stdout.split("Installed packages")[-1][:400]


def _has_kokkos() -> bool:
    return "KOKKOS" in _packages()


def _style_args(style):
    if style == "kk" and not _has_kokkos():
        pytest.skip("this lmp has no KOKKOS package")
    return KK if style == "kk" else []


@pytest.fixture(scope="module")
def case(tmp_path_factory):
    """SrTiO3 4 x 4 x 4 (320 atoms) in a sheared cell, rattled; its LAMMPS data file (IDs in the Atoms order, types
    O, Ti, Sr) and the OMAT-0 small bundle."""
    from ase.io import write

    d = tmp_path_factory.mktemp("lmp")
    at = srtio3(4)
    cell = at.cell.array.copy()
    cell[1, 0] += 0.07 * cell[0, 0]
    cell[2, 0] -= 0.05 * cell[0, 0]
    cell[2, 1] += 0.04 * cell[1, 1]
    at.set_cell(cell, scale_atoms=True)
    at.positions += np.random.default_rng(7).normal(scale=0.05, size=at.positions.shape)
    write(str(d / "sys.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return d, at, ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])


def _head(bundle, units="metal", elements="O Ti Sr", style="loupmd"):
    return (f"units {units}\natom_style atomic\natom_modify map yes\nboundary p p p\nread_data sys.data\n"
            f"pair_style {style}\npair_coeff * * {bundle} {elements}\nneighbor 0.5 bin\n")


def _lmp(d, name, body, args=(), ok=True):
    (d / f"in.{name}").write_text(body)
    r = subprocess.run([LMP, *args, "-echo", "none", "-in", f"in.{name}", "-log", f"{name}.log"], cwd=d,
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    if ok:
        assert r.returncode == 0 and "ERROR" not in out, out[-1500:]
    return out


def _thermo(d, name):
    """The rows of the last thermo block of a log (floats)."""
    rows, on = [], False
    for ln in (d / f"{name}.log").read_text().splitlines():
        if ln.split()[:1] == ["Step"]:
            rows, on = [], True
        elif ln.startswith("Loop time"):
            on = False
        elif on and not ln.startswith("WARNING"):         # a warning printed during the run
            rows.append([float(x) for x in ln.split()])
    return rows


@pytest.mark.parametrize("style", ["plain", "kk"])
def test_energy_forces_and_pressure_match_the_engine(case, style):
    d, at, bundle = case
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    e, f, s = eng.evaluate(at.positions, at.cell.array)
    _lmp(d, f"run0_{style}", _head(bundle) + f"""thermo_style custom step pe pxx pyy pzz pxy pxz pyz
thermo_modify format float %.12g
dump d all custom 1 run0_{style}.dump id fx fy fz
dump_modify d sort id format float %.10f
run 0
""", _style_args(style))
    row = _thermo(d, f"run0_{style}")[0]
    lines = (d / f"run0_{style}.dump").read_text().splitlines()
    k = max(i for i, ln in enumerate(lines) if ln.startswith("ITEM: ATOMS"))
    got = np.array([[float(x) for x in ln.split()] for ln in lines[k + 1:k + 1 + len(at)]])
    assert np.array_equal(got[:, 0].astype(int), np.arange(1, len(at) + 1))
    p_ref = -BAR * np.array([s[0, 0], s[1, 1], s[2, 2], s[0, 1], s[0, 2], s[1, 2]])
    assert abs(row[1] - e) < 1e-6 * len(at)
    assert np.abs(got[:, 1:4] - f).max() < 2e-5
    assert np.abs(np.array(row[2:8]) - p_ref).max() < max(1.0, 1e-5 * np.abs(p_ref).max())  # bar


def _md(bundle, integrator, steps=100, sort=0):
    return _head(bundle) + f"""atom_modify sort {sort} 2.0
timestep 0.0005
velocity all create 300.0 4928459 mom yes rot no dist gaussian
{integrator}
thermo {steps}
thermo_style custom step temp pe ke etotal
thermo_modify format float %.12g
run {steps}
"""


def test_the_engines_integrator_follows_fix_nve(case):
    """run_style loupmd nve against LAMMPS's own velocity Verlet from the same positions and velocities: the same
    trajectory early on (velocity units, time step), and both conserve the energy."""
    d, at, bundle = case
    n = len(at)
    _lmp(d, "nve_fix", _md(bundle, "fix 1 all nve"))
    _lmp(d, "nve_engine", _md(bundle, "run_style loupmd nve"))
    a, b = _thermo(d, "nve_fix"), _thermo(d, "nve_engine")
    assert abs(a[-1][2] - b[-1][2]) < 1e-5 * n and abs(a[-1][3] - b[-1][3]) < 1e-5 * n  # PE, KE after 100 steps
    for rows in (a, b):
        assert abs(rows[-1][4] - rows[0][4]) < 2e-4 * n  # total energy, eV


@pytest.mark.parametrize("style", ["plain", "kk"])
def test_sorting_the_atoms_every_step_changes_nothing(case, style):
    """The engine keeps atoms by ID, so LAMMPS may reorder its local atoms at will."""
    d, at, bundle = case
    args = _style_args(style)
    _lmp(d, f"sort0_{style}", _md(bundle, "fix 1 all nve", sort=0), args)
    _lmp(d, f"sort1_{style}", _md(bundle, "fix 1 all nve", sort=1), args)
    a, b = _thermo(d, f"sort0_{style}"), _thermo(d, f"sort1_{style}")
    assert abs(a[-1][2] - b[-1][2]) < 1e-6 * len(at)


def test_langevin_run_style_reaches_its_temperature(case):
    d, at, bundle = case
    _lmp(d, "lang", _head(bundle) + """timestep 0.001
run_style loupmd langevin 300.0 0.05 48279
thermo 200
thermo_style custom step temp pe ke etotal
run 800
""")
    rows = _thermo(d, "lang")
    assert rows[0][1] == 0.0 and all(230.0 < r[1] < 370.0 for r in rows[2:])  # from rest to 300 K (320 atoms)


def test_refusals_say_why(case):
    d, at, bundle = case
    out = _lmp(d, "bad_units", _head(bundle, units="real") + "run 0\n", ok=False)
    assert "requires metal units" in out
    out = _lmp(d, "bad_element", _head(bundle, elements="O Ti Na") + "run 0\n", ok=False)
    assert "is not in" in out and "which holds" in out
    out = _lmp(d, "bad_fix", _head(bundle) + "fix 1 all nve\nrun_style loupmd nve\nrun 1\n", ok=False)
    assert "so no fix may act during the steps" in out


@pytest.mark.parametrize("style", ["plain", "kk"])
def test_rigid_bodies_of_a_bonded_system_run(case, style):
    """A system with bonds and a host fix (rigid/small): LAMMPS-Kokkos aborted on its bond list while loupmd/kk
    requested no neighbour list (it now requests an occasional one, which is never built)."""
    if "RIGID" not in _packages() or "MOLECULE" not in _packages():
        pytest.skip("this lmp has no RIGID / MOLECULE packages")
    d, at, bundle = case
    n = len(at)
    # the same atoms as bodies of five (one formula unit each), with one bond per body
    order = {"O": 1, "Ti": 2, "Sr": 3}
    lines = (d / "sys.data").read_text().splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("Atoms"))
    head = [ln for ln in lines[:k] if "atoms" not in ln and "atom types" not in ln]
    atoms = [ln.split() for ln in lines[k + 2:k + 2 + n]]
    assert len(atoms) == n and all(int(a[1]) in order.values() for a in atoms)
    out = [head[0], "", f"{n} atoms", f"{n // 5} bonds", "3 atom types", "1 bond types"] + head[1:]
    # Coordinates from the Atoms object, not wrapped (read_data wraps them and sets the image flags), so that each
    # body is compact; the sheared cell is lower triangular, which is LAMMPS's frame already.
    x = at.positions
    out += ["Atoms # molecular", ""] + [f"{a[0]} {i // 5 + 1} {a[1]} {x[i, 0]:.10f} {x[i, 1]:.10f} {x[i, 2]:.10f}"
                                        for i, a in enumerate(atoms)]
    out += ["", "Bonds", ""] + [f"{m + 1} 1 {5 * m + 1} {5 * m + 2}" for m in range(n // 5)]
    (d / "bonded.data").write_text("\n".join(out) + "\n")
    deck = (f"units metal\natom_style molecular\natom_modify map yes\nboundary p p p\nread_data bonded.data\n"
            f"bond_style zero\nbond_coeff 1 3.4\npair_style loupmd\npair_coeff * * {bundle} O Ti Sr\nneighbor 0.5 bin\n"
            "timestep 0.0005\nvelocity all create 300.0 4928459 mom yes rot no dist gaussian\n"
            "fix 1 all rigid/nve/small molecule\nthermo 20\nthermo_style custom step temp pe ke etotal\nrun 40\n")
    _lmp(d, f"rigid_{style}", deck, _style_args(style))
    rows = _thermo(d, f"rigid_{style}")
    assert len(rows) == 3 and all(np.isfinite(x) for r in rows for x in r)
    assert abs(rows[-1][4] - rows[0][4]) < 5e-3 * n  # total energy, eV: a rigid-body run conserves it


def test_evaluate_ahead_gives_the_same_run(case):
    """pair_style loupmd ahead yes (the engine queues each next force pass ahead of its call): the same NVE run."""
    d, at, bundle = case
    n = len(at)
    deck = _md(bundle, "fix 1 all nve")
    _lmp(d, "ahead_no", deck.replace("pair_style loupmd", "pair_style loupmd ahead no"))
    _lmp(d, "ahead_yes", deck.replace("pair_style loupmd", "pair_style loupmd ahead yes"))
    a, b = _thermo(d, "ahead_no"), _thermo(d, "ahead_yes")
    assert abs(a[-1][2] - b[-1][2]) < 1e-5 * n and abs(a[-1][3] - b[-1][3]) < 1e-5 * n
