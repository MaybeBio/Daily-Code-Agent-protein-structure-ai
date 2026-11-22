"""The LAMMPS styles in the tiled mode (LAMMPS_TILED_PLAN.md, LT4): pair_style loupmd and loupmd/kk with `capacity`,
and run_style loupmd on the engine's tiled MD.

The cell is the rod of tests/gpu/test_tiled.py, SrTiO3 32 x 6 x 6 (5,760 atoms), lightly sheared, with caps of 600
receivers so that tiles form in several layers; MACE-OMAT-0 medium (two layers). Whole-system references run
without the skip-chain fold (LOUP_CHAIN_FOLD=0), which is what the tiles run, and both sides without the hybrid
GEMMs (LOUP_NO_HYBRID=1) for the bounds of test_tiled.py. The run style is compared with the engine's tiled MD
driven from Python (loup_tiled_*) with the integrator the run style is to pick, as test_lammps_run_style.py does
for whole cells.

Needs LOUPMD_LMP=/path/to/lmp, an lmp built with ML-LOUPMD against the library under test (skipped without it).
"""
from __future__ import annotations

import gc
import re

import numpy as np
import pytest
from gpu_support import find_model, srtio3
from test_lammps import BAR, LMP, _lmp, _packages, _style_args, _thermo
from test_lammps_run_style import CASES, DT_PS, VEL, _dump, _masses, _same

from loupmd import LoupEngine, _core, ensure_loup_bundle

pytestmark = pytest.mark.skipif(not __import__("os").path.exists(LMP),
                                reason="set LOUPMD_LMP to an lmp built with ML-LOUPMD")
CAP = 600
TILED = f"loupmd capacity tiled receivers {CAP}"


@pytest.fixture(scope="module")
def rod(tmp_path_factory):
    """SrTiO3 32 x 6 x 6 (5,760 atoms) in a lightly sheared box, rattled; its LAMMPS data file (sys.data, types O,
    Ti, Sr) and the OMAT-0 medium bundle."""
    from ase.io import write

    d = tmp_path_factory.mktemp("lmp_tiled")
    at = srtio3(1).repeat((32, 6, 6))
    c = at.cell.array.copy()
    c[1, 0] += 0.6
    c[2, 1] += 0.5
    at.set_cell(c, scale_atoms=True)
    at.positions += np.random.default_rng(13).normal(scale=0.04, size=at.positions.shape)
    write(str(d / "sys.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return d, at, ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])


def _head(bundle, style, data="sys.data", elements="O Ti Sr"):
    return (f"units metal\natom_style atomic\natom_modify map yes\nboundary p p p\nread_data {data}\n"
            f"pair_style {style}\npair_coeff * * {bundle} {elements}\nneighbor 0.5 bin\n")


def _tiled_line(out):
    """(tiles, cap, the line) of the pair style's plan line, or None."""
    m = re.search(r"LoupMD: \d+ atoms run tiled[^:]*: (\d+) tiles of at most (\d+) atoms[^\n]*", out)
    return (int(m.group(1)), int(m.group(2)), m.group(0)) if m else None


def _builds(out):
    """The tile list builds of the last run, from the pair style's run line."""
    found = re.findall(r"tiled MD steps, tile lists built (\d+) times", out)
    return int(found[-1]) if found else None


def _run0(d, name, bundle, style, args=()):
    """run 0: (screen, energy, pressure [xx yy zz xy xz yz] in bar, forces by ID)."""
    out = _lmp(d, name, _head(bundle, style) + f"""thermo_style custom step pe pxx pyy pzz pxy pxz pyz
thermo_modify format float %.15g
dump d all custom 1 {name}.dump id fx fy fz
dump_modify d sort id format float %.15g
run 0
""", args)
    row = _thermo(d, name)[0]
    lines = (d / f"{name}.dump").read_text().splitlines()
    k = max(i for i, ln in enumerate(lines) if ln.startswith("ITEM: ATOMS"))
    n = sum(1 for ln in lines[k + 1:] if ln.strip())
    f = np.array([[float(x) for x in ln.split()] for ln in lines[k + 1:k + 1 + n]])
    assert np.array_equal(f[:, 0].astype(int), np.arange(1, n + 1))
    return out, row[1], np.array(row[2:8]), f[:, 1:4]


def _compare(tiled, whole, n, de=1e-7, df=1e-5, ds=1e-8):
    (_, e_t, p_t, f_t), (_, e_w, p_w, f_w) = tiled, whole
    print(f"tiled vs whole: dE {abs(e_t - e_w) / n:.2e} eV/atom, dF {np.abs(f_t - f_w).max():.2e} eV/A, "
          f"dP {np.abs(p_t - p_w).max():.2e} bar")
    assert abs(e_t - e_w) / n <= de
    assert np.abs(f_t - f_w).max() <= df
    assert np.abs(p_t - p_w).max() <= ds * BAR


# ------------------------------------------------------------------------------------------------- the pair style

@pytest.mark.parametrize("style", ["plain", pytest.param("kk", marks=pytest.mark.full)])
def test_the_tiled_pair_style_matches_the_whole_call(rod, style, monkeypatch):
    d, at, bundle = rod
    args = _style_args(style)
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    tiled = _run0(d, f"t0_{style}", bundle, TILED, args)
    monkeypatch.setenv("LOUP_CHAIN_FOLD", "0")
    whole = _run0(d, f"w0_{style}", bundle, "loupmd capacity whole", args)
    said = _tiled_line(tiled[0])
    assert said is not None, tiled[0][-1500:]
    tiles, cap, line = said
    print(line)
    assert tiles >= 3 and cap == CAP and _tiled_line(whole[0]) is None
    _compare(tiled, whole, len(at))


@pytest.mark.full
def test_auto_runs_whole_when_the_cell_fits(rod):
    d, at, bundle = rod
    auto = _run0(d, "auto0", bundle, "loupmd")
    whole = _run0(d, "whole0", bundle, "loupmd capacity whole")
    assert "atoms run whole: the cell needs" in auto[0] and _tiled_line(auto[0]) is None
    assert "atoms run whole" not in whole[0]          # capacity whole makes no plan
    # the same whole call; the two processes pick their GEMM plans apart, so forces differ in float32 rounding
    _compare(auto, whole, len(at), de=1e-8)


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """SrTiO3 20 x 20 x 20 (40,000 atoms), rattled, with the OMAT-0 small bundle: whole fits the card, and tiles
    of 4,096 receivers or more take a fraction of what whole needs."""
    from ase.io import write

    d = tmp_path_factory.mktemp("lmp_tiled_big")
    at = srtio3(20)
    at.positions += np.random.default_rng(5).normal(scale=0.04, size=at.positions.shape)
    write(str(d / "sys.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return d, at, ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])


@pytest.mark.full
def test_auto_tiles_when_the_card_is_too_small(big, monkeypatch):
    """capacity auto on a card whose free memory (LOUP_DEBUG_PLAN_FREE) times `memory` holds half of what the whole
    cell needs: the pair style runs it in tiles and says so, with the whole call's results."""
    d, at, bundle = big
    monkeypatch.setenv("LOUP_DEBUG_PLAN_FREE", "8000")
    first = _run0(d, "big_auto", bundle, "loupmd")
    need = float(re.search(r"run whole: the cell needs ([0-9.]+) GiB", first[0]).group(1))
    fraction = min(0.5 * need * 1024.0 / 8000.0, 1.0)
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    tiled = _run0(d, "big_tiled", bundle, f"loupmd memory {fraction:.4f}")
    said = _tiled_line(tiled[0])
    assert said is not None, tiled[0][-1500:]
    print(f"whole needs {need} GiB; at memory {fraction:.4f} of 8000 MiB: {said[2]}")
    assert said[0] >= 2 and said[1] >= 4096
    monkeypatch.setenv("LOUP_CHAIN_FOLD", "0")
    whole = _run0(d, "big_whole", bundle, "loupmd capacity whole")
    _compare(tiled, whole, len(at))


def _md(bundle, style, steps, sort=0, thermo=None, fixes="fix 1 all nve", dt=0.0005):
    return _head(bundle, style) + f"""atom_modify sort {sort} 2.0
timestep {dt}
velocity all create 300.0 4928459 mom yes rot no dist gaussian
{fixes}
thermo {thermo or steps}
thermo_style custom step temp pe ke etotal press
thermo_modify format float %.15g
run {steps}
"""


@pytest.mark.full
def test_sorting_and_wrapping_keep_the_tile_lists(rod):
    """LAMMPS sorts its atoms every step and wraps them into the box when it reneighbours; the pair style passes
    unwrapped positions by ID, so the engine keeps its tile lists until an atom has moved skin/2, and sorting
    changes nothing. LAMMPS rebuilds its own lists by the same rule (neighbor 0.5, check yes), so the tile lists are
    built about as often as LAMMPS's, plus the first call's."""
    d, at, bundle = rod
    out0 = _lmp(d, "sort0_t", _md(bundle, TILED, 200, sort=0))
    out1 = _lmp(d, "sort1_t", _md(bundle, TILED, 200, sort=1))
    b0, b1 = _builds(out0), _builds(out1)
    nl = int(re.findall(r"Neighbor list builds = (\d+)", out0)[-1])
    a, b = _thermo(d, "sort0_t"), _thermo(d, "sort1_t")
    print(f"200 NVE steps tiled: list builds {b0} unsorted, {b1} sorted every step; LAMMPS's own {nl}")
    assert b0 is not None and b0 == b1 and abs(b0 - (nl + 1)) <= 1 and b0 < 20
    assert abs(a[-1][2] - b[-1][2]) < 1e-6 * len(at) and abs(a[-1][3] - b[-1][3]) < 1e-6 * len(at)


@pytest.mark.full
def test_a_barostat_through_the_tiled_pair_style_keeps_the_tile_lists(rod):
    """fix npt with the pair style in tiles (LAMMPS integrates and dilates the box about its centre in every step):
    the engine keeps its tile lists while the strain since their build leaves room for the atoms' moves
    (LAMMPS_TILED_PLAN.md LT6 (a)), so it builds them no more often than LAMMPS builds its own neighbour list,
    whose box check is the stricter one."""
    d, at, bundle = rod
    out = _lmp(d, "npt_t", _md(bundle, TILED, 200, fixes="fix 1 all npt temp 300.0 300.0 0.05 iso 0.0 0.0 0.5"))
    rows = _thermo(d, "npt_t")
    b = _builds(out)
    nl = int(re.findall(r"Neighbor list builds = (\d+)", out)[-1])
    print(f"200 NPT steps through the tiled pair style: tile list builds {b}, LAMMPS's own {nl}")
    assert "the box changes in every step" not in out
    assert np.isfinite(rows[-1][5]) and b is not None and b <= nl + 1 and b < 40


# ------------------------------------------------------------------------------------------------- the run style

def _run_rs(d, name, bundle, fixes, steps, thermo=None, runs=1, style=TILED, pre="", data="sys.data"):
    per_run = steps // runs
    body = _head(bundle, style, data=data) + f"""timestep {DT_PS}
velocity all create 300.0 4928459 mom yes rot no dist gaussian
{pre}
{fixes}
run_style loupmd
thermo {thermo or per_run}
thermo_style custom step temp pe ke lx ly lz xy xz yz press
thermo_modify format float %.15g
write_dump all custom {name}_0.dump id xu yu zu vx vy vz modify sort id format float %.15g
""" + "".join([f"run {per_run}\n"] * runs) + f"""write_dump all custom {name}_1.dump id xu yu zu vx vy vz modify sort id format float %.15g
"""
    return _lmp(d, name, body)


def _box(r):
    lx, ly, lz, xy, xz, yz = r[4:10]
    return np.array([[lx, 0.0, 0.0], [xy, ly, 0.0], [xz, yz, lz]])


def _states(d, name, n):
    rows = _thermo(d, name)
    a, b = _dump(d / f"{name}_0.dump", n), _dump(d / f"{name}_1.dump", n)
    return (a[:, 1:4], a[:, 4:7] / VEL, _box(rows[0])), (b[:, 1:4], b[:, 4:7] / VEL, _box(rows[-1])), rows


def _tiled_engine_run(d, at, bundle, start, steps, **fields):
    pos, vel, box = start
    eng = LoupEngine(bundle)
    try:
        eng.set_execution(_core.LOUP_EXEC_TILED, CAP, 0.9)
        eng.tiled_set_state(at.get_atomic_numbers(), _masses(d, at), pos, vel, box, receivers=CAP, skin=0.5)
        eng.tiled_run(steps, _core.integrator(dt_fs=1000.0 * DT_PS, **fields))
        p, v = eng.tiled_get_state()[:2]
        if fields["kind"] in BAROSTATS:
            box = eng.tiled_get_cell()
        builds = eng.last_execution().list_builds
    finally:
        del eng
        gc.collect()
    return (p, v, box), builds


BAROSTATS = (_core.LOUP_MTK_NPT, _core.LOUP_BERENDSEN_NPT)
TILED_CASES = ["nve", "nvt", "langevin", "langevin_zero", "berendsen", "npt", "berendsen_npt"]
ORTHO = ("berendsen_npt",)          # fix press/berendsen refuses a sheared box


@pytest.fixture(scope="module")
def rod_ortho(rod):
    """The rod in its orthogonal box, as ortho.data in the rod's folder."""
    from ase.io import write

    d = rod[0]
    at = srtio3(1).repeat((32, 6, 6))
    at.positions += np.random.default_rng(13).normal(scale=0.04, size=at.positions.shape)
    write(str(d / "ortho.data"), at, format="lammps-data", specorder=["O", "Ti", "Sr"], masses=True, units="metal",
          atom_style="atomic")
    return at


def _check_rs(rod, name, tag, thermo=None, runs=1, steps=40, ortho=None):
    d, at, bundle = rod
    data = "sys.data"
    if name in ORTHO:
        at, data = ortho, "ortho.data"
    fixes, fields = CASES[name]
    out = _run_rs(d, tag, bundle, fixes, steps, thermo=thermo, runs=runs, data=data)
    start, end, rows = _states(d, tag, len(at))
    assert "the LoupMD engine's tiled MD" in out and "Capacity      : tiled" in out, out[-2000:]
    assert f"{steps // runs} tiled MD steps" in out
    ref, builds = _tiled_engine_run(d, at, bundle, start, steps, **fields)
    moves_box = fields["kind"] in BAROSTATS
    _same(end, ref, len(at), box_tol=1e-6 if moves_box else 0.0)
    if moves_box:
        assert np.abs(end[2] - start[2]).max() > 1e-5        # the box did move
    return out, rows, builds


@pytest.mark.parametrize("name", [n if n in ("nve", "npt") else pytest.param(n, marks=pytest.mark.full)
                                  for n in TILED_CASES])
def test_the_tiled_run_style_follows_the_engines_tiled_md(rod, rod_ortho, name):
    _check_rs(rod, name, "rs_" + name, ortho=rod_ortho)


@pytest.mark.full
@pytest.mark.parametrize("name", ["nvt", "langevin", "npt", "berendsen_npt"])
def test_output_inside_a_tiled_run_leaves_the_trajectory_alone(rod, rod_ortho, name):
    """Thermo every 10 steps makes four blocks of the 40: at each, LAMMPS takes the state (and, under a barostat,
    the engine's cell), wraps the atoms and has the pair style evaluate (a tiled call with stress, on the kept
    lists), and the engine goes on from its own state. The end is that of one run of 40 steps, and no list is built
    for the output: the engine's own 40 steps build as many."""
    out, rows, builds = _check_rs(rod, name, "rs_blocks_" + name, thermo=10, ortho=rod_ortho)
    assert len(rows) == 5 and all(np.isfinite(r[10]) for r in rows)
    print(f"tiled run style, thermo every 10 of 40 steps: list builds {_builds(out)}, the engine's own run {builds}")
    assert _builds(out) == builds


@pytest.mark.full
def test_two_tiled_runs_continue_one_trajectory(rod):
    """run 20 twice: the second run's setup finds the engine's state unchanged and sends nothing, so the thermostat
    and the noise stream go on: the end is that of one run of 40 steps."""
    _check_rs(rod, "langevin", "rs_two_runs", runs=2)


@pytest.mark.full
def test_temp_csvr_runs_tiled(rod):
    if "EXTRA-FIX" not in _packages():
        pytest.skip("this lmp has no EXTRA-FIX package")
    d, at, bundle = rod
    out = _run_rs(d, "rs_csvr", bundle, "fix 1 all nve\nfix 2 all temp/csvr 300.0 300.0 0.05 4711", 40)
    rows = _thermo(d, "rs_csvr")
    assert "the LoupMD engine's tiled MD" in out and np.isfinite(rows[-1][2])


@pytest.mark.full
def test_tiled_nve_conserves_energy(rod):
    d, at, bundle = rod
    steps = 500
    _run_rs(d, "rs_nve_long", bundle, "fix 1 all nve", steps, thermo=50)
    rows = np.array(_thermo(d, "rs_nve_long"))
    total = rows[:, 2] + rows[:, 3]
    t_ps = rows[:, 0] * DT_PS
    drift = np.polyfit(t_ps, total, 1)[0] / len(at) * 1e3       # meV/atom/ps
    print(f"tiled run style NVE, {steps} steps: drift {drift:.4f} meV/atom/ps")
    assert abs(drift) < 0.05


# ------------------------------------------------------------------------------------------------- forms, refusals

@pytest.mark.full
@pytest.mark.parametrize("form", ["wavefront", "host_lists", "host_state"])
def test_wavefront_and_host_forms_give_the_plain_tiled_result(rod, form, monkeypatch):
    d, at, bundle = rod
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    plain = _run0(d, f"form_plain_{form}", bundle, TILED)
    style = TILED
    if form == "wavefront":
        style = f"loupmd capacity wavefront receivers {CAP}"
    else:
        monkeypatch.setenv("LOUP_TILE_HOST_LISTS", "1")
        if form == "host_state":
            monkeypatch.setenv("LOUP_TILE_HOST_STATE", "1")
    other = _run0(d, f"form_{form}", bundle, style)
    said = _tiled_line(other[0])
    assert said is not None, other[0][-1500:]
    print(said[2])
    expect = {"wavefront": "(wavefront schedule)", "host_lists": "tile lists in host memory",
              "host_state": "tile lists and layer state in host memory"}[form]
    assert expect in said[2]
    _compare(other, plain, len(at), de=1e-8, df=1e-5, ds=1e-8)


def _nacl(d):
    from ase.build import bulk
    from ase.io import write

    at = bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((3, 3, 3))
    write(str(d / "nacl.data"), at, format="lammps-data", specorder=["Na", "Cl"], masses=True, units="metal",
          atom_style="atomic")


def _water(d):
    from ase.io import write
    from gpu_support import water_box

    write(str(d / "water.data"), water_box(), format="lammps-data", specorder=["H", "O"], masses=True, units="metal",
          atom_style="atomic")


@pytest.mark.full
def test_tiled_refusals_say_why(rod):
    d, at, bundle = rod
    _nacl(d)
    polar = ensure_loup_bundle(find_model("MACE-POLAR-1-S.model"), [11, 17])
    out = _lmp(d, "ref_polar", _head(polar, "loupmd capacity tiled", data="nacl.data", elements="Na Cl")
               + "run 0\n", ok=False)
    assert "long-range models (MACE-POLAR-1) cannot run in tiles" in out
    out = _lmp(d, "ref_peratom", _head(bundle, TILED) + "compute pa all pe/atom\n"
               "dump d all custom 1 pa.dump id c_pa\nrun 0\n", ok=False)
    assert "does not provide per-atom energies" in out
    _water(d)
    omol = ensure_loup_bundle(find_model("MACE-omol-0-extra-large-1024.model"), [1, 8])
    out = _lmp(d, "ref_wave", _head(omol, "loupmd capacity wavefront", data="water.data", elements="H O")
               + "run 0\n", ok=False)
    assert "capacity wavefront needs a model of two layers" in out
