"""run_style loupmd without an ensemble: the engine's integrators take over the input's fixes (lammps/README.md).

Each ensemble is run through LAMMPS and, from LAMMPS's own starting state, through the Python engine with the
integrator the run style is to pick: the same positions, velocities and box come out. That checks the mapping of
every setting (times, units, chain lengths, seeds, the degrees of freedom), not the integrators themselves, which
tests/gpu/test_nhc_gpu.py and its neighbours check against ASE.

Needs LOUPMD_LMP=/path/to/lmp, an lmp built with ML-LOUPMD against the library under test (skipped without it).
"""
from __future__ import annotations

import numpy as np
import pytest
from gpu_support import find_model, srtio3
from test_lammps import LMP, _head, _lmp, _packages, _thermo

from loupmd import LoupEngine, _core, ensure_loup_bundle

pytestmark = pytest.mark.skipif(not __import__("os").path.exists(LMP),
                                reason="set LOUPMD_LMP to an lmp built with ML-LOUPMD")
VEL = 98.22694788464063     # A/ps per ASE velocity unit
GPA_PER_BAR = 1.0e-4
DT_PS = 0.001


@pytest.fixture(scope="module")
def cell(tmp_path_factory):
    """SrTiO3 3 x 3 x 3 (135 atoms) in a sheared box, rattled; its LAMMPS data file and the OMAT-0 small bundle."""
    from ase.io import write

    d = tmp_path_factory.mktemp("lmp_rs")
    at = srtio3(3)
    c = at.cell.array.copy()
    c[1, 0] += 0.06 * c[0, 0]
    c[2, 0] -= 0.04 * c[0, 0]
    c[2, 1] += 0.05 * c[1, 1]
    at.set_cell(c, scale_atoms=True)
    at.positions += np.random.default_rng(11).normal(scale=0.04, size=at.positions.shape)
    write(str(d / "sys.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return d, at, ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])


@pytest.fixture(scope="module")
def ortho(cell):
    """The same crystal in its orthogonal box (fix press/berendsen takes no sheared one), as ortho.data."""
    from ase.io import write

    d = cell[0]
    at = srtio3(3)
    at.positions += np.random.default_rng(11).normal(scale=0.04, size=at.positions.shape)
    write(str(d / "ortho.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return at


def _dump(path, n):
    lines = path.read_text().splitlines()
    k = max(i for i, ln in enumerate(lines) if ln.startswith("ITEM: ATOMS"))
    rows = np.array([[float(x) for x in ln.split()] for ln in lines[k + 1:k + 1 + n]])
    assert np.array_equal(rows[:, 0].astype(int), np.arange(1, n + 1))
    return rows


def _run(d, name, bundle, fixes, steps, thermo=None, pre="", temp=300.0, runs=1, ok=True, data="sys.data",
         between=""):
    """`fixes` with run_style loupmd; the state before and after as LAMMPS has it, the thermo rows and the screen.
    `between` goes between the run commands (with {name}_mid.dump written after it)."""
    per_run = steps // runs
    mid = f"{between}\nwrite_dump all custom {name}_mid.dump id xu yu zu vx vy vz modify sort id format float %.15g\n"
    body = _head(bundle).replace("sys.data", data) + f"""timestep {DT_PS}
velocity all create {temp} 4928459 mom yes rot no dist gaussian
{pre}
{fixes}
run_style loupmd
thermo {thermo or per_run}
thermo_style custom step temp pe ke lx ly lz xy xz yz press
thermo_modify format float %.15g
write_dump all custom {name}_0.dump id xu yu zu vx vy vz modify sort id format float %.15g
""" + (mid if between else "").join([f"run {per_run}\n"] * runs) + f"""write_dump all custom {name}_1.dump id xu yu zu vx vy vz fx fy fz modify sort id format float %.15g
"""
    out = _lmp(d, name, body, ok=ok)
    return out


def _state(d, name, n):
    rows = _thermo(d, name)
    first, last = rows[0], rows[-1]

    def box(r):
        lx, ly, lz, xy, xz, yz = r[4:10]
        return np.array([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]])

    a, b = _dump(d / f"{name}_0.dump", n), _dump(d / f"{name}_1.dump", n)
    return (a[:, 1:4], a[:, 4:7] / VEL, box(first)), (b[:, 1:4], b[:, 4:7] / VEL, box(last)), rows


def _masses(d, at):
    lines = (d / "sys.data").read_text().splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith("Masses"))
    by_type = {int(ln.split()[0]): float(ln.split()[1]) for ln in lines[k + 2:k + 5]}
    type_of = {8: 1, 22: 2, 38: 3}
    return np.array([by_type[type_of[int(z)]] for z in at.get_atomic_numbers()])


def _engine_run(d, at, bundle, start, steps, fixed=None, masses=None, **fields):
    pos, vel, box = start
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), _masses(d, at) if masses is None else masses, skin=0.5)
    eng.set_state(pos, vel, box)
    if fixed is not None:
        eng.set_fixed_atoms(fixed)
    eng.run(steps, _core.integrator(dt_fs=1000.0 * DT_PS, **fields))
    p, v, _, _ = eng.get_state()
    return p, v, eng.get_cell()


def _same(got, ref, n, box_tol=0.0):
    """LAMMPS's end state against the engine's: two processes pick their GEMM plans separately, so the forces differ
    in float32 rounding and the trajectories by what a few dozen steps make of that."""
    (p, v, box), (p_ref, v_ref, box_ref) = got, ref
    assert np.abs(box - box_ref).max() <= box_tol + 1e-12, np.abs(box - box_ref).max()
    # the dump's unwrapped positions and the engine's differ by whole box vectors only where LAMMPS re-wrapped
    frac = np.linalg.solve(box_ref.T, (p - p_ref).T).T
    assert np.abs(frac - np.round(frac)).max() * np.abs(box_ref).max() < 2e-5
    assert np.abs(v - v_ref).max() * VEL < 2e-3          # A/ps, of thermal velocities of a few A/ps


CASES = {
    "nve": ("fix 1 all nve", dict(kind=_core.LOUP_NVE)),
    "nvt": ("fix 1 all nvt temp 320.0 320.0 0.05",
            dict(kind=_core.LOUP_NHC, temp_k=320.0, tau_t_fs=50.0, mass_temp_k=320.0, chain_length=3, chain_loops=1,
                 fix_com=1)),
    "nvt_ramp_tchain": ("fix 1 all nvt temp 200.0 400.0 0.05 tchain 5 tloop 2",
                        dict(kind=_core.LOUP_NHC, temp_k=200.0, temp_rate_k_per_step=200.0 / 40, tau_t_fs=50.0,
                             mass_temp_k=200.0, chain_length=5, chain_loops=2, fix_com=1)),
    "langevin": ("fix 1 all nve\nfix 2 all langevin 320.0 320.0 0.1 48279",
                 dict(kind=_core.LOUP_LANGEVIN, temp_k=320.0, friction_per_fs=1.0 / 100.0, seed=48279)),
    "langevin_zero": ("fix 1 all nve\nfix 2 all langevin 320.0 320.0 0.1 48279 zero yes",
                      dict(kind=_core.LOUP_LANGEVIN, temp_k=320.0, friction_per_fs=1.0 / 100.0, seed=48279,
                           fix_com=1)),
    "berendsen": ("fix 1 all nve\nfix 2 all temp/berendsen 350.0 350.0 0.1",
                  dict(kind=_core.LOUP_BERENDSEN_NVT, temp_k=350.0, tau_t_fs=100.0, fix_com=1)),
    "npt": ("fix 1 all npt temp 320.0 320.0 0.05 iso 2000.0 2000.0 0.5",
            dict(kind=_core.LOUP_MTK_NPT, temp_k=320.0, tau_t_fs=50.0, mass_temp_k=320.0, chain_length=3,
                 chain_loops=1, p_chain_length=3, p_chain_loops=1, pressure_gpa=2000.0 * GPA_PER_BAR, tau_p_fs=500.0,
                 cell_mode=_core.LOUP_CELL_HYDROSTATIC, fix_com=1)),
    "berendsen_npt": ("fix 1 all nve\nfix 2 all temp/berendsen 320.0 320.0 0.1\n"
                      "fix 3 all press/berendsen iso 5000.0 5000.0 0.5 modulus 1.8e6",
                      dict(kind=_core.LOUP_BERENDSEN_NPT, temp_k=320.0, tau_t_fs=100.0,
                           pressure_gpa=5000.0 * GPA_PER_BAR, tau_p_fs=500.0, compressibility_per_gpa=1.0 / 180.0,
                           cell_mode=_core.LOUP_CELL_HYDROSTATIC, fix_com=1)),
    "berendsen_npt_xz": ("fix 1 all nve\nfix 2 all temp/berendsen 320.0 320.0 0.1\n"
                         "fix 3 all press/berendsen x 5000.0 5000.0 0.5 z 5000.0 5000.0 0.5 modulus 1.8e6",
                         dict(kind=_core.LOUP_BERENDSEN_NPT, temp_k=320.0, tau_t_fs=100.0,
                              pressure_gpa=5000.0 * GPA_PER_BAR, tau_p_fs=500.0,
                              compressibility_per_gpa=1.0 / 180.0, cell_mode=_core.LOUP_CELL_FULL,
                              cell_mask=(1, 0, 1), fix_com=1)),
}
ORTHO = ("berendsen_npt", "berendsen_npt_xz")      # fix press/berendsen refuses a sheared box


def _check_case(cell, ortho, name, tag, thermo=None):
    d, at, bundle = cell
    if name in ORTHO:
        at = ortho
    fixes, fields = CASES[name]
    n, steps = len(at), 40
    _run(d, tag, bundle, fixes, steps, thermo=thermo, data="ortho.data" if name in ORTHO else "sys.data")
    start, end, rows = _state(d, tag, n)
    assert len(rows) == 1 + steps // (thermo or steps)
    ref = _engine_run(d, at, bundle, start, steps, **fields)
    moves_box = fields["kind"] in (_core.LOUP_MTK_NPT, _core.LOUP_BERENDSEN_NPT)
    _same(end, ref, n, box_tol=1e-6 if moves_box else 0.0)
    if moves_box:
        assert np.abs(end[2] - start[2]).max() > 1e-5        # the box did move
        if fields["cell_mode"] == _core.LOUP_CELL_HYDROSTATIC:      # the shape is kept
            assert np.allclose(end[2] / end[2][0, 0], start[2] / start[2][0, 0], atol=1e-9)
        else:                                                       # y is not barostatted
            assert end[2][1, 1] == start[2][1, 1] and end[2][0, 0] != start[2][0, 0] and end[2][2, 2] != start[2][2, 2]


@pytest.mark.parametrize("name", list(CASES))
def test_the_run_style_runs_the_engines_integrator_of_the_fixes(cell, ortho, name):
    _check_case(cell, ortho, name, name)


@pytest.mark.parametrize("name", ["nvt_ramp_tchain", "langevin", "npt", "berendsen_npt"])
def test_output_inside_a_run_leaves_the_trajectory_alone(cell, ortho, name):
    """Thermo output every 10 steps makes four blocks of the 40 steps. At each one LAMMPS takes the state, wraps the
    atoms and has the pair style evaluate, and the engine goes on from LAMMPS's positions: with the same thermostat
    and barostat variables, the same place in the noise stream and in the temperature ramp, and the same box, so
    the end is that of the engine's one run of 40 steps."""
    _check_case(cell, ortho, name, name + "_blocks", thermo=10)


def test_temp_csvr_is_taken_over(cell):
    """The fix keeps no seed to compare with, so: the run is reproducible, and from 600 K the system is brought to
    the fix's 300 K."""
    if "EXTRA-FIX" not in _packages():
        pytest.skip("this lmp has no EXTRA-FIX package (fix temp/csvr)")
    d, at, bundle = cell
    fixes = "fix 1 all nve\nfix 2 all temp/csvr 300.0 300.0 0.02 7711"
    out = _run(d, "csvr_a", bundle, fixes, 300, thermo=100, temp=600.0)
    assert "velocity rescaling of Bussi" in out
    _run(d, "csvr_b", bundle, fixes, 300, thermo=100, temp=600.0)
    a, b = _state(d, "csvr_a", len(at)), _state(d, "csvr_b", len(at))
    assert np.abs(a[1][0] - b[1][0]).max() < 1e-4            # the same noise in both runs
    temps = [r[1] for r in a[2]]
    assert temps[0] == pytest.approx(600.0, abs=1.0) and all(240.0 < t < 360.0 for t in temps[1:])


def test_held_atoms(cell):
    """fix setforce 0 0 0 on a group at rest, and a fix nve on the others only: both leave the engine with atoms held
    in place, as the engine's own fixed atoms."""
    d, at, bundle = cell
    n, steps = len(at), 40
    held = np.zeros(n, dtype=bool)
    held[:20] = True
    pre = "group hold id 1:20\ngroup mobile subtract all hold\nvelocity hold set 0.0 0.0 0.0"
    for name, fixes in (("hold_setforce", "fix 0 hold setforce 0.0 0.0 0.0\nfix 1 all nve"),
                        ("hold_group", "fix 1 mobile nve")):
        out = _run(d, name, bundle, fixes, steps, pre=pre)
        assert "Held in place : 20 atoms" in out
        start, end, _ = _state(d, name, n)
        # (LAMMPS's wrap through fractional coordinates may move the last bit in a sheared box)
        assert np.abs(end[0][:20] - start[0][:20]).max() < 1e-12 and np.array_equal(end[1][:20], start[1][:20])
        ref = _engine_run(d, at, bundle, start, steps, fixed=held, kind=_core.LOUP_NVE)
        _same(end, ref, n)
        forces = _dump(d / f"{name}_1.dump", n)[:, 7:10]
        assert np.abs(forces[20:]).max() > 0.1
        if name == "hold_setforce":     # the fix's zeros, as under run_style verlet
            assert np.array_equal(forces[:20], np.zeros((20, 3)))
    # a held atom that moves in LAMMPS (zero force, a velocity) is refused
    out = _run(d, "hold_moving", bundle, "fix 0 hold setforce 0.0 0.0 0.0\nfix 1 all nve", steps,
               pre="group hold id 1:20", ok=False)
    assert "is in a 'fix setforce 0 0 0' group and has a velocity" in out


def test_fix_momentum_keeps_the_centre_of_mass(cell):
    d, at, bundle = cell
    n, steps = len(at), 40
    out = _run(d, "mom", bundle, "fix 1 all nve\nfix 2 all momentum 10 linear 1 1 1", steps)
    assert "centre of mass kept at rest" in out
    start, end, _ = _state(d, "mom", n)
    _same(end, _engine_run(d, at, bundle, start, steps, kind=_core.LOUP_NVE, fix_com=1), n)


def test_two_runs_continue_one_trajectory(cell):
    """Nothing changes between two run commands, so the engine keeps its state, the thermostat's chain included: two
    runs of 20 steps are one of 40."""
    d, at, bundle = cell
    n = len(at)
    fixes = "fix 1 all nvt temp 320.0 320.0 0.05"
    _run(d, "one40", bundle, fixes, 40)
    _run(d, "two20", bundle, fixes, 40, runs=2)
    a, b = _state(d, "one40", n), _state(d, "two20", n)
    _same(b[1], a[1], n)


def test_a_second_run_never_repeats_the_first_runs_noise(cell):
    """The engine's noise is a function of the seed, the atom and the steps taken on the system it holds. New
    velocities between two runs are a new state on the same system: the stream runs on. New masses are a new system,
    whose steps count from zero: the run style moves the seed. (The fix's own generator would not repeat itself
    either.)"""
    d, at, bundle = cell
    n = len(at)
    fixes = "fix 1 all nve\nfix 2 all langevin 320.0 320.0 0.1 48279"
    fields = dict(kind=_core.LOUP_LANGEVIN, temp_k=320.0, friction_per_fs=1.0 / 100.0)

    def mid_state(name, end):
        m = _dump(d / f"{name}_mid.dump", n)
        return m[:, 1:4], m[:, 4:7] / VEL, end[2]

    # new velocities: the engine that ran the first 20 steps, given the new state, goes on with the same seed
    _run(d, "renew", bundle, fixes, 40, runs=2, between="velocity all create 320.0 991 mom yes rot no dist gaussian")
    start, end, _ = _state(d, "renew", n)
    mid = mid_state("renew", end)
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), _masses(d, at), skin=0.5)
    it = _core.integrator(dt_fs=1000.0 * DT_PS, seed=48279, **fields)
    eng.set_state(*start)
    eng.run(20, it)
    eng.set_state(*mid)
    eng.run(20, it)
    p, v, _, _ = eng.get_state()
    _same(end, (p, v, end[2]), n)
    again = _engine_run(d, at, bundle, mid, 20, seed=48279, **fields)       # the first run's noise once more
    assert np.abs(end[1] - again[1]).max() * VEL > 0.05

    # new masses: a new system, and the seed moved by the run style
    _run(d, "remass", bundle, fixes, 40, runs=2, between="mass 1 17.5")
    start, end, _ = _state(d, "remass", n)
    mid = mid_state("remass", end)
    masses = _masses(d, at)
    masses[at.get_atomic_numbers() == 8] = 17.5
    moved = (48279 + 0x9E3779B97F4A7C15) % 2**64
    _same(end, _engine_run(d, at, bundle, mid, 20, masses=masses, seed=moved, **fields), n)
    again = _engine_run(d, at, bundle, mid, 20, masses=masses, seed=48279, **fields)
    assert np.abs(end[1] - again[1]).max() * VEL > 0.05


def test_output_inside_a_run_costs_no_new_step_graphs(cell, monkeypatch):
    """At every output step the pair style evaluates for LAMMPS. That evaluation keeps the integrator's captured
    step graphs (it used to capture its own over them, and the integrator's again at the next block)."""
    d, at, bundle = cell
    monkeypatch.setenv("LOUP_DEBUG_GRAPHS", "1")
    out = _run(d, "blocks", bundle, "fix 1 all nvt temp 320.0 320.0 0.05", 200, thermo=10)
    assert len(_thermo(d, "blocks")) == 21
    assert out.count("MD graph capture") <= 8, out.count("MD graph capture")


REFUSED = [
    ("fix 1 all npt temp 300.0 300.0 0.1 aniso 0.0 0.0 1.0", "cannot take over fix 1 (npt): only 'iso' is taken over"),
    ("fix 1 all npt temp 300.0 300.0 0.1 iso 0.0 1000.0 1.0", "cannot take over fix 1 (npt): a pressure ramp"),
    ("fix 1 all nvt temp 300.0 300.0 0.1 drag 0.2", "cannot take over fix 1 (nvt): drag"),
    ("fix 1 all nph iso 0.0 0.0 1.0", "cannot take over fix 1 (nph): it acts during the steps"),
    ("fix 1 all nve\nfix 2 all addforce 0.0 0.0 0.01", "cannot take over fix 2 (addforce): it acts during the steps"),
    ("fix 1 all nve\nfix 2 all press/berendsen iso 0.0 0.0 1.0 modulus 1.8e6",
     "cannot take over fix 2 (press/berendsen): the engine's Berendsen barostat comes with the Berendsen thermostat"),
    ("fix 1 all nve\nfix 2 all nve", "cannot take over fix 2 (nve): fix 1 integrates already"),
    ("fix 1 all nve\nfix 2 all setforce 0.0 0.0 1.0", "cannot take over fix 2 (setforce): only 'setforce 0.0 0.0 0.0'"),
    ("fix 1 all nve\nfix 2 all momentum 10 linear 1 1 0", "cannot take over fix 2 (momentum): only 'momentum N linear 1 1 1'"),
    ("fix 2 all langevin 300.0 300.0 0.1 4", "the input has no fix nve, fix nvt or fix npt"),
    ("", "the input has no fix nve, fix nvt or fix npt"),
]


@pytest.mark.parametrize("fixes,message", REFUSED, ids=[m.split(":")[0][-28:] + str(i) for i, (_, m) in enumerate(REFUSED)])
def test_a_fix_without_a_counterpart_is_refused_by_name(cell, fixes, message):
    d, at, bundle = cell
    out = _run(d, "refused", bundle, fixes, 10, ok=False)
    assert message in out, out[-800:]
    if message.startswith("cannot take over"):
        assert "Use the default run style (run_style verlet) with pair_style loupmd" in out


def test_the_log_says_what_runs(cell):
    d, at, bundle = cell
    out = _run(d, "says", bundle, "fix 1 all npt temp 300.0 300.0 0.1 iso 0.0 0.0 1.0", 10)
    assert "Ensemble      : fix 1 (npt 300 -> 300 K, Tdamp 0.1 ps, iso 0 bar, Pdamp 1 ps): Martyna-Tobias-Klein" in out
    assert "Integrator    : the LoupMD engine's; centre of mass kept at rest" in out
