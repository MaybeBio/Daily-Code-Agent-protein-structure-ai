"""The tile planner of the tiled capacity mode (plan task S5-T01).

``src/tile_plan.cu`` is host code only, so the test compiles it with g++ into a small library of its own and calls
it through the three functions ``include/loupmd.h`` declares for it. Needs neither a GPU nor libloupmd.so; skips
without g++ or without the source tree.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms
from ase.neighborlist import neighbor_list

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "tile_plan.cu"
REACH = 6.5            # cutoff 6.0 A plus skin 0.5 A
GRID_FIT_SCALES = (1.0, 1.04, 1.08, 1.12, 1.17, 1.22, 1.28)


@pytest.fixture(scope="module")
def planner(tmp_path_factory):
    gxx = shutil.which("g++")
    if gxx is None or not SOURCE.is_file():
        pytest.skip("needs g++ and the source tree")
    out = tmp_path_factory.mktemp("tile_plan") / "libtileplan.so"
    done = subprocess.run([gxx, "-x", "c++", "-std=c++17", "-O2", "-shared", "-fPIC", f"-I{ROOT / 'src'}",
                           f"-I{ROOT / 'include'}", str(SOURCE), "-o", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-3000:]
    lib = ctypes.CDLL(str(out))
    c_ll, c_int, c_double, ptr = ctypes.c_longlong, ctypes.c_int, ctypes.c_double, ctypes.POINTER
    lib.loup_tile_plan.argtypes = [ptr(c_double), c_ll, ptr(c_double), c_int, c_ll, ptr(c_int), c_double, ptr(c_int),
                                   ptr(c_ll), ptr(c_ll), ptr(c_int)]
    lib.loup_tile_plan_copy.argtypes = [ptr(c_ll), ptr(c_int), ptr(c_int), ptr(c_ll), ptr(c_int), ptr(c_int)]
    lib.loup_tile_plan_error.restype = ctypes.c_char_p

    def as_ptr(array, kind):
        return array.ctypes.data_as(ptr(kind))

    def plan(positions, cell, receivers, reach=0.0, edges=0, degree=None, shape=None, copy=True):
        positions = np.ascontiguousarray(positions, dtype=np.float64)
        cell = np.ascontiguousarray(cell, dtype=np.float64)
        n = len(positions)
        degree_c = None if degree is None else np.ascontiguousarray(degree, dtype=np.int32)
        shape_c = None if shape is None else np.ascontiguousarray(shape, dtype=np.int32)
        tiles, ghosts, grid = c_ll(), c_ll(), (c_int * 3)()
        start = time.perf_counter()
        status = lib.loup_tile_plan(as_ptr(positions, c_double), n, as_ptr(cell, c_double), receivers, edges,
                                    None if degree_c is None else as_ptr(degree_c, c_int), reach,
                                    None if shape_c is None else as_ptr(shape_c, c_int),
                                    ctypes.byref(tiles), ctypes.byref(ghosts), grid)
        seconds = time.perf_counter() - start
        if status != 0:
            raise RuntimeError(lib.loup_tile_plan_error().decode())
        result = {"grid": tuple(grid), "tiles": tiles.value, "ghosts": ghosts.value, "seconds": seconds}
        if copy:
            arrays = {"local_ptr": np.empty(tiles.value + 1, np.int64), "local": np.empty(n, np.int32),
                      "local_shift": np.empty((n, 3), np.int32), "ghost_ptr": np.empty(tiles.value + 1, np.int64),
                      "ghost": np.empty(ghosts.value, np.int32), "ghost_shift": np.empty((ghosts.value, 3), np.int32)}
            assert lib.loup_tile_plan_copy(as_ptr(arrays["local_ptr"], c_ll), as_ptr(arrays["local"], c_int),
                                           as_ptr(arrays["local_shift"], c_int), as_ptr(arrays["ghost_ptr"], c_ll),
                                           as_ptr(arrays["ghost"], c_int), as_ptr(arrays["ghost_shift"], c_int)) == 0
            result.update(arrays)
        return result

    return plan


def srtio3(rep, rattle=0.05, seed=11, shear=False, strays=True):
    a = 3.905
    atoms = Atoms(symbols=["Sr", "Ti", "O", "O", "O"],
                  scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
                  cell=[a, a, a], pbc=True).repeat((rep, rep, rep))
    if shear:                                  # a triclinic cell: the plane spacings are not the vector lengths
        cell = atoms.cell.array.copy()
        cell[1] += 0.31 * cell[0]
        cell[2] += 0.17 * cell[0] - 0.23 * cell[1]
        atoms.set_cell(cell, scale_atoms=True)
    rng = np.random.default_rng(seed)
    positions = atoms.positions + rng.normal(0.0, rattle, atoms.positions.shape)
    if strays:                                 # every 50th atom a few cells away: the planner wraps it
        moved = np.arange(0, len(atoms), 50)
        positions[moved] += rng.integers(-2, 3, (len(moved), 3)) @ atoms.cell.array
    return positions, atoms.cell.array.copy()


def spacings(cell):
    inverse = np.linalg.inv(cell)
    return 1.0 / np.linalg.norm(inverse, axis=0)


def rule_grid(cell, n, receivers, scale=1.0):
    """The rule of FastMACE's ``_grid_shape``: about cubic blocks of about ``receivers`` atoms."""
    side = (abs(np.linalg.det(cell)) * min(receivers, n) / n) ** (1.0 / 3.0)
    return tuple(max(1, int(round(scale * s / side))) for s in spacings(cell))


def check_plan(plan, positions, cell, receivers, reach):
    n = len(positions)
    local_ptr, local, local_shift = plan["local_ptr"], plan["local"], plan["local_shift"]
    ghost_ptr, ghost, ghost_shift = plan["ghost_ptr"], plan["ghost"], plan["ghost_shift"]
    tiles = plan["tiles"]
    # every atom is local in exactly one tile, in ascending order within a tile, at most `receivers` per tile
    assert local_ptr[0] == 0 and local_ptr[-1] == n and np.all(np.diff(local_ptr) > 0)
    assert np.array_equal(np.sort(local), np.arange(n))
    sizes = np.diff(local_ptr)
    assert sizes.max() <= receivers and tiles >= -(-n // receivers)
    inside = np.ones(n, dtype=bool)
    inside[local_ptr[1:-1]] = False            # the first atom of each later tile starts a new ascending run
    assert np.all((np.diff(local) > 0) | ~inside[1:])
    # the shift of a local puts it into the cell
    wrapped = (positions[local] + local_shift @ cell) @ np.linalg.inv(cell)
    assert wrapped.min() > -1e-9 and wrapped.max() < 1.0 + 1e-9
    assert ghost_ptr[0] == 0 and ghost_ptr[-1] == len(ghost) == plan["ghosts"] and np.all(np.diff(ghost_ptr) >= 0)

    # every neighbour within `reach` of a local is local or a ghost candidate of that tile, as the same image
    tile_of = np.empty(n, dtype=np.int64)
    tile_of[local] = np.repeat(np.arange(tiles), sizes)
    shift_of = np.empty((n, 3), dtype=np.int64)
    shift_of[local] = local_shift
    atoms = Atoms(numbers=np.ones(n, dtype=int), positions=positions, cell=cell, pbc=True)
    i, j, S = neighbor_list("ijS", atoms, reach)
    assert len(i) > 10 * n                     # the list is a real one

    def key(tile, atom, shift):
        shift = np.asarray(shift, dtype=np.int64) + 512
        assert shift.min() >= 0 and shift.max() < 1024
        return ((tile * n + atom) * 1024 + shift[:, 0]) * 1024 * 1024 + shift[:, 1] * 1024 + shift[:, 2]

    entries = np.concatenate([key(tile_of[local], local.astype(np.int64), local_shift),
                              key(np.repeat(np.arange(tiles), np.diff(ghost_ptr)), ghost.astype(np.int64),
                                  ghost_shift)])
    assert len(np.unique(entries)) == len(entries)             # nothing is listed twice in a tile
    # in the tile's frame local i sits at r_i + shift_i, so its neighbour is r_j + (S + shift_i) cell
    wanted = key(tile_of[i], j.astype(np.int64), S + shift_of[i])
    missing = ~np.isin(wanted, entries)
    assert not missing.any(), f"{int(missing.sum())} of {len(wanted)} neighbours are in no list of their tile"
    return sizes


@pytest.mark.parametrize("rep,receivers,shear", [(20, 4096, False), (11, 600, True), (2, 4096, False), (5, 100, True)],
                         ids=["40000-atoms", "triclinic", "cell-below-reach", "triclinic-small-tiles"])
def test_every_atom_is_local_once_and_every_neighbour_is_in_its_tile(planner, rep, receivers, shear):
    positions, cell = srtio3(rep, shear=shear)
    plan = planner(positions, cell, receivers, reach=REACH)
    sizes = check_plan(plan, positions, cell, receivers, REACH)
    if rep == 20:
        assert len(positions) == 40_000 and plan["tiles"] >= 10 and plan["ghosts"] > len(positions)
    if rep == 2:                                # one tile; its own atoms come back as periodic images
        assert plan["tiles"] == 1 and sizes[0] == 40 and plan["ghosts"] > 40
        assert np.abs(plan["ghost_shift"]).max() >= 1


def test_without_a_reach_there_are_no_ghosts_and_the_grid_can_be_given(planner):
    positions, cell = srtio3(10)
    plan = planner(positions, cell, 512)
    assert plan["ghosts"] == 0 and not plan["ghost_ptr"].any()
    again = planner(positions, cell, 512, shape=plan["grid"])
    assert again["grid"] == plan["grid"] and np.array_equal(again["local"], plan["local"])
    assert np.array_equal(again["local_ptr"], plan["local_ptr"])
    coarse = planner(positions, cell, 512, shape=(1, 1, 1))     # one block, split into consecutive pieces
    assert coarse["grid"] == (1, 1, 1) and coarse["tiles"] == -(-5000 // 512)
    assert np.array_equal(coarse["local"], np.arange(5000))
    assert np.array_equal(np.diff(coarse["local_ptr"]), [512] * 9 + [5000 - 9 * 512])


def test_the_grid_is_the_one_with_the_fewest_pieces(planner):
    """FastMACE's ``fit_grid`` (without a reach): of the rule's grid and six finer ones, the grid whose blocks make
    the fewest tiles (the coarser one on a tie). On a crystal the rule's blocks can sit just above the cap, and each
    then splits."""
    positions, cell = srtio3(24, rattle=0.0, strays=False)       # 69,120 atoms
    n, receivers = len(positions), 4096
    counts = {}
    for scale in GRID_FIT_SCALES:
        grid = rule_grid(cell, n, receivers, scale)
        if grid not in counts:
            counts[grid] = planner(positions, cell, receivers, shape=grid)["tiles"]
    fitted = planner(positions, cell, receivers)
    best = min(counts.values())
    assert fitted["tiles"] == best and fitted["grid"] == next(g for g, c in counts.items() if c == best)
    assert best <= counts[rule_grid(cell, n, receivers)]


def _grid_rows(positions, cell, grid, receivers, reach):
    """The fit's rows of a grid: every piece of a block counts the block's atoms and its halo (the mean density over
    the block's shell `reach` thick)."""
    frac = positions @ np.linalg.inv(cell)
    frac -= np.floor(frac)
    k = np.asarray(grid)
    b = np.minimum((frac * k).astype(np.int64), k - 1)
    counts = np.bincount((b[:, 0] * k[1] + b[:, 1]) * k[2] + b[:, 2], minlength=int(np.prod(k)))
    sides = spacings(cell) / k
    halo = len(positions) / abs(np.linalg.det(cell)) * (np.prod(sides + 2 * reach) - np.prod(sides))
    pieces = -(-counts // receivers)
    return float(np.sum(pieces * (counts + halo)))


def test_with_a_reach_the_grid_is_the_one_with_the_fewest_rows(planner):
    """O32: with a reach, the grid whose pieces have the fewest rows (locals and halo; a piece of a split block takes
    about the whole block). Here the rule's 3 x 3 x 3 blocks of 2,560 atoms split at the cap of 2,048 into 54
    pieces whose domains are their whole block; 4 x 4 x 4 makes more tiles (64) but fewer rows and smaller domains
    (2,560,000 atoms at cap 65,536 the same: a 12.6 GB workspace against 5 GB)."""
    positions, cell = srtio3(24, rattle=0.0, strays=False)       # 69,120 atoms
    n, receivers = len(positions), 2048
    assert rule_grid(cell, n, receivers) == (3, 3, 3)
    rows = {}
    for scale in GRID_FIT_SCALES:
        grid = rule_grid(cell, n, receivers, scale)
        rows.setdefault(grid, _grid_rows(positions, cell, grid, receivers, REACH))
    fewest = planner(positions, cell, receivers)
    fitted = planner(positions, cell, receivers, reach=REACH)
    assert fewest["grid"] == (3, 3, 3) and fewest["tiles"] == 54
    assert fitted["grid"] == min(rows, key=rows.get) == (4, 4, 4) and fitted["tiles"] == 64
    widest = {name: max(np.diff(p["local_ptr"]) + np.diff(p["ghost_ptr"]))
              for name, p in (("fewest", planner(positions, cell, receivers, reach=REACH, shape=(3, 3, 3))),
                              ("fitted", fitted))}
    assert widest["fitted"] < 0.8 * widest["fewest"]               # 4,429 against 6,050 rows


def test_the_edge_cap_splits_a_block_as_fastmace_does(planner):
    positions, cell = srtio3(6, strays=False)                     # 1,080 atoms
    n = len(positions)
    degree = np.random.default_rng(5).integers(20, 61, n).astype(np.int32)
    degree[17] = 900                                              # one atom above the cap is a tile of its own
    receivers, edges = 200, 800
    plan = planner(positions, cell, receivers, edges=edges, degree=degree, shape=(1, 1, 1))
    assert np.array_equal(plan["local"], np.arange(n))
    cumulative = np.concatenate([[0], np.cumsum(degree, dtype=np.int64)])
    expected, piece = [0], 0
    while piece < n:                                              # _split_block of fastmace/model/tiled.py
        over = int(np.searchsorted(cumulative, cumulative[piece] + edges, side="right"))
        piece = min(piece + receivers, max(over - 1, piece + 1), n)
        expected.append(piece)
    assert np.array_equal(plan["local_ptr"], expected)
    sums = np.add.reduceat(degree.astype(np.int64), plan["local_ptr"][:-1])
    sizes = np.diff(plan["local_ptr"])
    assert np.all((sums <= edges) | (sizes == 1)) and (sizes == 1).any()
    whole = planner(positions, cell, receivers, edges=edges, degree=degree, reach=REACH)
    check_plan(whole, positions, cell, receivers, REACH)
    sums = np.add.reduceat(degree[whole["local"]].astype(np.int64), whole["local_ptr"][:-1])
    assert np.all((sums <= edges) | (np.diff(whole["local_ptr"]) == 1))


def test_a_million_atoms_are_planned_in_half_a_second(planner):
    positions, cell = srtio3(59, strays=False)                    # 1,026,895 atoms
    times = [planner(positions, cell, 16384, reach=REACH, copy=False)["seconds"] for _ in range(3)]
    plan = planner(positions, cell, 16384, reach=REACH)
    assert plan["local_ptr"][-1] == len(positions) == 1_026_895 and np.diff(plan["local_ptr"]).max() <= 16384
    print(f"\n1,026,895 atoms: {plan['tiles']} tiles on grid {plan['grid']}, {plan['ghosts']} ghost candidates, "
          f"planned in {min(times) * 1e3:.0f} ms (runs: {', '.join(f'{t * 1e3:.0f}' for t in times)})")
    assert min(times) < 0.5


@pytest.mark.parametrize("change,message", [
    (dict(receivers=0), "receivers must be positive"),
    (dict(cell=np.zeros((3, 3))), "the cell has no volume"),
    (dict(reach=-1.0), "reach must be finite and not negative"),
    (dict(shape=(0, 1, 1)), "the grid must have at least one block per axis"),
    (dict(nan=True), "is not finite"),
    (dict(edges=100), "the edge cap needs the atoms' edge counts"),
])
def test_what_cannot_be_planned_is_refused_by_name(planner, change, message):
    positions, cell = srtio3(3, strays=False)
    options = dict(receivers=64, reach=REACH)
    if change.pop("nan", False):
        positions[7, 1] = np.nan
    cell = change.pop("cell", cell)
    options.update(change)
    receivers = options.pop("receivers")
    with pytest.raises(RuntimeError, match=message):
        planner(positions, cell, receivers, **options)
    assert planner(*srtio3(3, strays=False), 64)["tiles"] >= 3       # the planner works after a refusal
