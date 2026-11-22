"""The tiled call (plan task S5-T03): a periodic system evaluated tile by tile with the per-layer sweeps, the state
between sweeps in whole-system arrays on the device. Energy, forces and stress must be those of the whole-system
call. Every test creates engines and skips when its model file is absent."""
from __future__ import annotations

import ctypes
import gc
import re

import numpy as np
import pytest
from gpu_support import find_model, srtio3, unfolded, water_box

from loupmd import BackendError, LoupEngine, ensure_loup_bundle
from loupmd import _core

SKIN = 0.5
c_ll, c_int, c_double, ptr = ctypes.c_longlong, ctypes.c_int, ctypes.c_double, ctypes.POINTER


def _tiled(bundle, at, receivers):
    eng = LoupEngine(bundle)
    lib = eng._lib
    lib.loup_debug_evaluate_tiled.argtypes = [ctypes.c_void_p, c_int, ptr(c_int), ptr(c_double), ptr(c_double), c_int,
                                              c_double, ptr(c_double), ptr(c_double), ptr(c_double), ptr(c_ll)]
    z = np.ascontiguousarray(at.get_atomic_numbers(), dtype=np.int32)
    pos = np.ascontiguousarray(at.positions, dtype=np.float64)
    cell = np.ascontiguousarray(at.cell.array, dtype=np.float64)
    energy, tiles = c_double(), c_ll()
    forces, stress = np.zeros((len(at), 3)), np.zeros((3, 3))
    rc = lib.loup_debug_evaluate_tiled(eng._h, len(at), z.ctypes.data_as(ptr(c_int)), pos.ctypes.data_as(ptr(c_double)),
                                       cell.ctypes.data_as(ptr(c_double)), receivers, SKIN, ctypes.byref(energy),
                                       forces.ctypes.data_as(ptr(c_double)), stress.ctypes.data_as(ptr(c_double)),
                                       ctypes.byref(tiles))
    error = _core.last_error(eng._h) if rc != 0 else None
    del eng                                            # also on failure: pytest keeps a failed test's frames
    gc.collect()
    if error is not None:
        raise BackendError(error, call="loup_debug_evaluate_tiled")
    return energy.value, forces, stress, tiles.value


def _whole(bundle, at):
    eng = LoupEngine(bundle)
    try:
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=SKIN)
        return eng.evaluate(at.positions, at.cell.array)
    finally:
        del eng                                        # also on failure: pytest keeps a failed test's frames
        gc.collect()


def _oxide(rep):
    at = srtio3(rep)
    at.positions += np.random.default_rng(5).normal(scale=0.04, size=at.positions.shape)
    at.set_cell(at.cell.array * np.array([[1.0, 0.006, 0.0], [0.0, 1.0, 0.004], [0.003, 0.0, 1.0]]), scale_atoms=True)
    return at


def _water(reps):
    at = water_box().repeat(reps)
    at.positions += np.random.default_rng(6).normal(scale=0.02, size=at.positions.shape)
    return at


# (model file, structure, receivers per tile, layers). SrTiO3 20x20x20 and the water box 4x4x4 are 40,000 and
# 41,472 atoms; MH-1's whole-system call does not fit 16 GB at 40,000 atoms, so 17x17x17 (24,565); OMOL-0 extra
# large (1024 channels) on 2 x 648 atoms.
CASES = [
    ("mace-omat-0-medium.model", lambda: _oxide(20), 10000, 2),
    ("mace-omat-0-small.model", lambda: _oxide(20), 10000, 2),
    ("mace-mh-1.model", lambda: _oxide(17), 6000, 2),
    ("MACE-OFF23_medium.model", lambda: _water((4, 4, 4)), 10000, 2),
    ("MACE-omol-0-extra-large-1024.model", lambda: _water((2, 1, 1)), 400, 3),
    # MP-0 medium: a pruned second conv layer (its skipped projections' zeros, the sender-owned backward that an
    # open domain must not take) and a compact layer 0; MPtrj-2022.9: both layers compact
    ("2023-12-03-mace-128-L1_epoch-199.model", lambda: _oxide(12), 2200, 2),
    ("MACE_MPtrj_2022.9.model", lambda: _oxide(12), 2200, 2),
]
IDS = [c[0].split(".model")[0] for c in CASES]


@pytest.mark.parametrize("model,structure,receivers,layers", CASES, ids=IDS)
@pytest.mark.full
def test_the_tiled_call_gives_the_whole_system_result(model, structure, receivers, layers, monkeypatch):
    monkeypatch.delenv("LOUP_CHAIN_FOLD", raising=False)   # the tiled engines are default ones: the fold built, off
    at = structure()
    n = len(at)
    zs = sorted(set(at.get_atomic_numbers().tolist()))
    bundle = ensure_loup_bundle(find_model(model), zs)
    # The whole-system references run without the skip-chain fold, the operations the tiles run
    # (gpu_support.unfolded): the bounds below are those of the same operations on other GEMM row counts.
    with unfolded():
        e_a, f_a, s_a = _whole(bundle, at)
    e_t, f_t, s_t, tiles = _tiled(bundle, at, receivers)
    assert tiles >= 2
    # The tensor-core hybrid GEMMs are chosen per GEMM shape, and a tile's GEMMs have other row counts than the
    # whole system's: where one side gets a hybrid kernel and the other a float32 one, the energies differ by the
    # hybrid's rounding (PLAN.md D16). Without hybrids on either side the plan's bounds apply.
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    with unfolded():
        e_c, f_c, s_c = _whole(bundle, at)
    e_n, f_n, s_n, _ = _tiled(bundle, at, receivers)
    monkeypatch.delenv("LOUP_NO_HYBRID")

    def diff(e, f, s, e0, f0, s0):
        return abs(e - e0) / n, np.abs(f - f0).max(), np.abs(s - s0).max()

    default, plain, kernels = diff(e_t, f_t, s_t, e_a, f_a, s_a), diff(e_n, f_n, s_n, e_c, f_c, s_c),         diff(e_c, f_c, s_c, e_a, f_a, s_a)
    print(f"tiled {model}: {n} atoms, {tiles} tiles; default GEMMs dE {default[0]:.2e} eV/atom, dF {default[1]:.2e} "
          f"eV/A, dS {default[2]:.2e} eV/A^3; no hybrids dE {plain[0]:.2e}, dF {plain[1]:.2e}, dS {plain[2]:.2e}; "
          f"whole system between the two kernel sets {kernels[0]:.1e}, {kernels[1]:.1e}, {kernels[2]:.1e}")
    # Without hybrids: the plan's bounds (1e-7 eV/atom, 1e-5 eV/A; stress a tenth of the gate's floor). With the
    # default GEMMs: forces as the plan; energy at a fifth of the gate's energy floor (0.01 meV/atom) and stress at
    # twice its floor (1e-7 eV/A^3): which tile shapes get the hybrid depends on the plan picks, and fresh picks gave
    # up to 1.03e-6 eV/atom before the tile GEMM buckets and 1.42e-6 with them, and stress from 9e-9 to 1.10e-7 on
    # OMAT-0 small with either library of S5-T08 (PLAN.md D16, D60, D66).
    for name, d, bound in zip(("energy", "forces", "stress"), plain, (1e-7, 1e-5, 1e-8)):
        assert d <= bound, f"{name}, no hybrids: the tiled call differs by {d:.3e}"
    for name, d, bound in zip(("energy", "forces", "stress"), default, (2e-6, 1e-5, 2e-7)):
        assert d <= bound, f"{name}, default GEMMs: the tiled call differs by {d:.3e}"


def test_a_tiled_call_on_a_kept_workspace_gives_a_fresh_engines_result():
    """The handle keeps the tile workspace between tiled calls (ledger `tile-kept-lists`): a later call with
    other tiles, or on a smaller system, must give what a new engine gives."""
    big, small = _oxide(8), _oxide(6)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])

    def fresh(at, receivers):
        eng = LoupEngine(bundle)
        try:
            return eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, receivers, skin=SKIN)
        finally:
            del eng
            gc.collect()

    eng = LoupEngine(bundle)
    try:
        calls = [(big, 1000), (big, 400), (small, 300), (big, 1000)]
        kept = [eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, r, skin=SKIN) for at, r in calls]
    finally:
        del eng
        gc.collect()
    for (at, r), (e, f, s, tiles) in zip(calls, kept):
        e0, f0, s0, tiles0 = fresh(at, r)
        assert tiles == tiles0 >= 2
        # The same GEMM shapes can get other plans on a new engine only through the autotune's timing; the hybrid
        # rounding bounds of the tiled test apply (D60): 1.02e-6 eV/atom once in 11 runs (16 November 2026; the other
        # ten and five runs without hybrids passed the old 1e-6 on the same library), so the tiled test's 2e-6.
        assert abs(e - e0) / len(at) <= 2e-6 and np.abs(f - f0).max() <= 1e-5 and np.abs(s - s0).max() <= 1e-7
    e1, f1, _, _ = kept[0]
    e4, f4, _, _ = kept[3]
    # Same engine, tiles and plans: the same numbers up to the order of the float32 atomic sums (measured up to
    # 3.5e-9 eV/atom and 1.03e-6 eV/A); stale state from an earlier call would be far larger.
    assert abs(e4 - e1) / len(big) <= 1e-8 and np.abs(f4 - f1).max() <= 1e-5


@pytest.mark.full
def test_the_wavefront_gives_the_plain_tiled_result_from_a_smaller_row_pool(monkeypatch, capfd):
    """S5-T08: LOUP_TILE_WAVEFRONT=1 runs the three sweeps of a two-layer model in the wavefront's order, with the
    layer outputs and their gradients in a pool of rows taken and given back during the call. Its plan splits the
    first and last layer of tiles at the faces, so its tiles differ from the plain call's; without hybrids the
    two agree to float32 rounding of other GEMM row counts (energy 1e-9 relative, forces 1e-5 eV/A)."""
    at = srtio3(1).repeat((64, 6, 6))                  # 11,520 atoms in a rod 250 A long: tiles in layers along it
    at.positions += np.random.default_rng(7).normal(scale=0.04, size=at.positions.shape)
    n = len(at)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "0")
    e_p, f_p, s_p, tiles_p = _tiled(bundle, at, 600)
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "1")
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")
    capfd.readouterr()
    e_w, f_w, s_w, tiles_w = _tiled(bundle, at, 600)
    lines = [line for line in capfd.readouterr().err.splitlines() if line.startswith("tile wavefront:")]
    assert len(lines) == 1, "the wavefront did not run"
    pool = int(lines[0].split("row pool ")[1].split()[0])
    print(f"wavefront: {lines[0]}; plain call {tiles_p} tiles; dE {abs(e_w - e_p) / abs(e_p):.2e} relative, "
          f"dF {np.abs(f_w - f_p).max():.2e} eV/A, dS {np.abs(s_w - s_p).max():.2e} eV/A^3")
    assert tiles_w >= tiles_p >= 4
    assert pool < 0.5 * n
    assert abs(e_w - e_p) <= 1e-9 * abs(e_p)
    assert np.abs(f_w - f_p).max() <= 1e-5 and np.abs(s_w - s_p).max() <= 1e-8


@pytest.mark.parametrize("wavefront", ["0", "1"])
@pytest.mark.parametrize("keep_active", [None, "0", "1"])
@pytest.mark.parametrize("stage", ["1", "0", "36"])
def test_tile_lists_in_host_memory_give_the_device_lists_result(wavefront, keep_active, stage, monkeypatch, capfd):
    """O31 (S5-T07): LOUP_TILE_HOST_LISTS=1 keeps the tile lists' edge arrays in mapped pinned host memory. Each
    sweep that compacts a tile's active edges (its first of the call, or every sweep of a tile without a slot:
    LOUP_TILE_KEEP_ACTIVE=0 none, =1 one slot for all tiles) reads them from a device buffer they were copied into
    on a copy stream one compaction ahead (LOUP_TILE_HOST_STAGE=1, the default where it fits), or over the bus
    (=0). The host lists are compact (O32: senders and integer image shifts, 8 B per edge, the rest rebuilt on
    the device per compaction) unless LOUP_TILE_HOST_COMPACT=0 ("36": the full form, staged; 28 B per edge since the
    merge of round6-hardening 13d6337, 36 B before). Same tiles, same
    kernels: the device lists' numbers up to the order of the float32 atomic sums, in the call that builds the
    lists and in a later call that keeps them."""
    at = srtio3(1).repeat((32, 6, 6))                  # 5,760 atoms in a rod: several layers of tiles along it
    at.positions += np.random.default_rng(8).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(9).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", wavefront)
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")         # two engines: no hybrid-or-not plan pick between them (D16)
    if keep_active is not None:
        monkeypatch.setenv("LOUP_TILE_KEEP_ACTIVE", keep_active)
    monkeypatch.setenv("LOUP_TILE_HOST_STAGE", "0" if stage == "0" else "1")
    monkeypatch.setenv("LOUP_TILE_HOST_COMPACT", "0" if stage == "36" else "1")
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(host):
        monkeypatch.setenv("LOUP_TILE_HOST_LISTS", host)
        eng = LoupEngine(bundle)
        try:
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 400, skin=SKIN) for x in (at.positions, moved)]
            ex = eng.last_execution()
            return out, ex
        finally:
            del eng
            gc.collect()

    (dev, ex_d), (host, ex_h) = run("0"), run("1")
    err = capfd.readouterr().err
    assert not ex_d.host_lists and ex_h.host_lists and ex_h.lists_kept
    assert f"tile host lists staged: {'no' if stage == '0' else 'yes'}" in err
    assert (", compact" in err) == (stage != "36")
    assert "staging out of step" not in err
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(dev, host):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.parametrize("wavefront", ["0", "1"])
@pytest.mark.parametrize("keep_active", [None, "0"])
def test_compact_device_lists_give_the_full_device_lists_result(wavefront, keep_active, monkeypatch, capfd):
    """O32: device tile lists keep their edges as senders and integer image shifts (8 B per edge) and the active-edge
    compaction's inputs are decoded from them on the device, as with compact host lists; LOUP_TILE_DEVICE_COMPACT=0
    keeps the full form (28 B per edge). Same tiles and kernels: the full lists' numbers up to the order of the
    float32 atomic sums,
    in the building call and a kept one, with kept active edges or a compaction in every sweep."""
    at = srtio3(1).repeat((32, 6, 6))                  # 5,760 atoms in a rod
    at.positions += np.random.default_rng(18).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(19).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", wavefront)
    monkeypatch.setenv("LOUP_TILE_HOST_LISTS", "0")
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "0")
    if keep_active is not None:
        monkeypatch.setenv("LOUP_TILE_KEEP_ACTIVE", keep_active)

    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(compact):
        monkeypatch.setenv("LOUP_TILE_DEVICE_COMPACT", compact)
        eng = LoupEngine(bundle)
        try:
            capfd.readouterr()
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 400, skin=SKIN) for x in (at.positions, moved)]
            said = [x for x in capfd.readouterr().err.splitlines() if x.startswith("tile lists:")]
            return out, eng.last_execution(), said
        finally:
            del eng
            gc.collect()

    (full, ex_f, said_f), (comp, ex_c, said_c) = run("0"), run("1")
    assert not ex_c.host_lists and ex_c.lists_kept
    assert said_f and said_f[0].startswith("tile lists: device, 0 of")
    n_tiles = said_c[0].split(" of ")[1].split()[0]
    assert said_c[0].startswith(f"tile lists: device, {n_tiles} of {n_tiles} compact")
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(full, comp):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.parametrize("wavefront", ["0", "1"])
@pytest.mark.parametrize("host_lists", ["0", "1"])
def test_compact_active_slots_give_the_compaction_result(wavefront, host_lists, monkeypatch, capfd):
    """O32: a tile of a compact list that finds no full slot of kept active edges takes a compact one (row pointers,
    senders and integer image shifts, 8 B per edge): its first sweep packs the shifts after the compaction, its
    later sweeps restore the receivers, vectors and spline locators from it instead of compacting again. Against a
    compaction in every sweep (LOUP_TILE_KEEP_ACTIVE=0, LOUP_TILE_KEEP_COMPACT=0): compact slots only, and one full
    and one compact slot; device lists and staged host lists; the building call and a kept one."""
    at = srtio3(1).repeat((32, 6, 6))                  # 5,760 atoms in a rod
    at.positions += np.random.default_rng(20).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(21).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", wavefront)
    monkeypatch.setenv("LOUP_TILE_HOST_LISTS", host_lists)
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "0")
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(full, compact):
        monkeypatch.setenv("LOUP_TILE_KEEP_ACTIVE", full)
        monkeypatch.setenv("LOUP_TILE_KEEP_COMPACT", compact)
        eng = LoupEngine(bundle)
        try:
            capfd.readouterr()
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 400, skin=SKIN) for x in (at.positions, moved)]
            err = capfd.readouterr().err
            said = [x for x in err.splitlines() if x.startswith("tile compact active slots:")]
            assert "staging out of step" not in err
            return out, int(said[0].split(":")[1].split()[0])
        finally:
            del eng
            gc.collect()

    (ref, n0), (comp, n1), (mixed, n2) = run("0", "0"), run("0", "99"), run("1", "1")
    assert n0 == 0 and n1 >= 2 and n2 == 1
    for other in (comp, mixed):
        for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(ref, other):
            assert t0 == t1 >= 4
            assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.parametrize("model", ["mace-omat-0-small.model", "mace-mp-0b3-medium.model"])
@pytest.mark.parametrize("host_lists", ["0", "1"])
@pytest.mark.parametrize("pipe", ["alias", "1", "0"])
def test_layer_state_in_host_memory_gives_the_device_state_result(model, host_lists, pipe, monkeypatch):
    """O32 (S5-T07 step 2): LOUP_TILE_HOST_STATE=1 keeps the plain order's layer outputs and their gradients in
    pinned host memory, each atom's row in its tile's block of locals; a tile's own rows move as one copy, its ghost
    rows are gathered and its gradient rows added on the host (in row order instead of the device's atomics). Same
    tiles and kernels otherwise: the device state's numbers up to the order of the float32 sums, in the call that
    builds the lists and in a later call that keeps them, with the lists on the device or in host memory, with the
    copies and host work overlapped with the sweeps (LOUP_TILE_HOST_PIPE=1, the default) or not; overlapped, the
    gradients take the rows of the layer outputs once these are read (the default, "alias") or their own array
    (LOUP_TILE_HOST_ALIAS=0)."""
    at = srtio3(1).repeat((32, 6, 6))                  # 5,760 atoms in a rod: several tiles along it
    at.positions += np.random.default_rng(11).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(12).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model(model), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")         # two engines: no hybrid-or-not plan pick between them (D16)
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "0")
    monkeypatch.setenv("LOUP_TILE_HOST_LISTS", host_lists)
    monkeypatch.setenv("LOUP_TILE_HOST_PIPE", "0" if pipe == "0" else "1")
    monkeypatch.setenv("LOUP_TILE_HOST_ALIAS", "1" if pipe == "alias" else "0")

    def run(state):
        monkeypatch.setenv("LOUP_TILE_HOST_STATE", state)
        eng = LoupEngine(bundle)
        try:
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 400, skin=SKIN) for x in (at.positions, moved)]
            return out, eng.last_execution()
        finally:
            del eng
            gc.collect()

    (dev, ex_d), (host, ex_h) = run("0"), run("1")
    assert ex_h.lists_kept
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(dev, host):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.parametrize("alias", ["1", "0"])
def test_host_state_tiles_with_their_own_rows_on_the_device_give_the_device_state_result(alias, monkeypatch, capfd):
    """O32: in a cube cut into tiles without ghosts of their own atoms, the last forward tile's outputs stay in the
    layer buffer for its last sweep (the first of that phase), and the last last-layer tile's own gradient rows stay
    on the device for its backward sweep (the first of that phase), added there to the other tiles' host adds. The
    device state's numbers, in the building call and a kept one, with the gradients on the outputs' rows or not."""
    at = srtio3(1).repeat((14, 14, 14))               # 13,720 atoms
    at.positions += np.random.default_rng(13).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(14).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "0")
    monkeypatch.setenv("LOUP_TILE_HOST_ALIAS", alias)
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(state):
        monkeypatch.setenv("LOUP_TILE_HOST_STATE", state)
        eng = LoupEngine(bundle)
        try:
            return [eng.evaluate_tiled(at.numbers, x, at.cell.array, 1800, skin=SKIN) for x in (at.positions, moved)]
        finally:
            del eng
            gc.collect()

    dev, host = run("0"), run("1")
    line = [x for x in capfd.readouterr().err.splitlines() if x.startswith("tile host state order:")]
    assert line and all(int(v) >= 0 for v in re.findall(r"tiles (-?\d+) .* and (-?\d+)", line[-1])[0])
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(dev, host):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.parametrize("host_lists", ["0", "1"])
def test_the_wavefronts_row_pool_in_host_memory_gives_the_device_pool_result(host_lists, monkeypatch, capfd):
    """O32: with the wavefront and LOUP_TILE_HOST_STATE=1 the row pool is in pinned host memory as blocks of a
    tile's locals, taken at the tile's first sweep and given back at its last (the device pool's schedule); the
    sweeps run one after another with the plain host state's copies and host adds. Same tiles and kernels: the
    device pool's numbers up to the order of the float32 sums, in the building call and a kept one."""
    at = srtio3(1).repeat((32, 6, 6))                  # 5,760 atoms in a rod: several layers of tiles along it
    at.positions += np.random.default_rng(15).normal(scale=0.04, size=at.positions.shape)
    moved = at.positions + np.random.default_rng(16).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "1")
    monkeypatch.setenv("LOUP_TILE_HOST_LISTS", host_lists)
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(state):
        monkeypatch.setenv("LOUP_TILE_HOST_STATE", state)
        eng = LoupEngine(bundle)
        try:
            capfd.readouterr()
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 400, skin=SKIN) for x in (at.positions, moved)]
            return out, eng.last_execution(), capfd.readouterr().err
        finally:
            del eng
            gc.collect()

    (dev, ex_d, err_d), (host, ex_h, err_h) = run("0"), run("1")
    assert "tile wavefront:" in err_d and "tile wavefront host pool:" not in err_d
    pool = [x for x in err_h.splitlines() if x.startswith("tile wavefront host pool:")]
    assert pool and "tile wavefront:" in err_h
    print(pool[0])
    assert not ex_d.host_state and ex_h.host_state and ex_h.lists_kept
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(dev, host):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


def test_the_plan_puts_the_wavefronts_row_pool_in_host_memory_below_the_device_pool(monkeypatch, capfd):
    """O32: with the wavefront forced, below the smallest memory fraction at which a cap fits with its row pool on
    the device, the plan moves the pool to host memory (host_state) instead of refusing; the call it plans runs the
    wavefront with the host pool and gives the device pool's numbers at the same cap."""
    at = srtio3(1).repeat((64, 6, 6))                  # 11,520 atoms in a rod
    at.positions += np.random.default_rng(17).normal(scale=0.04, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "1")
    eng = LoupEngine(bundle)
    try:
        def plan(fraction, state=None):
            if state is None:
                monkeypatch.delenv("LOUP_TILE_HOST_STATE", raising=False)
            else:
                monkeypatch.setenv("LOUP_TILE_HOST_STATE", state)
            eng.set_execution(_core.LOUP_EXEC_TILED, 0, fraction)
            try:
                return eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=SKIN)
            except BackendError:
                return None

        # a fixed free memory for the plan: the true figure moves by MB between two plans (other programs)
        monkeypatch.setenv("LOUP_DEBUG_PLAN_FREE", "8000")
        lo, hi = 1e-4, 0.9                             # the smallest fraction with the pool on the device
        while hi - lo > 1e-3 * hi:
            mid = 0.5 * (lo + hi)
            lo, hi = (lo, mid) if plan(mid, "0") is not None else (mid, hi)
        at_hi = plan(hi)
        assert at_hi is not None and not at_hi.host_state
        below = plan(lo * 0.999)
        assert below is not None and below.host_state and below.receivers >= 4096
        assert plan(lo * 0.999, "0") is None
        assert plan(lo * 0.999) is not None
        monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")
        capfd.readouterr()
        e1, f1, s1, _ = eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, 0, skin=SKIN)
        assert eng.last_execution().host_state
        assert "tile wavefront host pool:" in capfd.readouterr().err
    finally:
        del eng
        gc.collect()
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "0")
    ref = LoupEngine(bundle)
    try:
        ref.set_execution(_core.LOUP_EXEC_TILED, below.receivers, 0.9)
        e0, f0, s0, _ = ref.evaluate_tiled(at.numbers, at.positions, at.cell.array, below.receivers, skin=SKIN)
        assert not ref.last_execution().host_state
    finally:
        del ref
        gc.collect()
    assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


def test_kept_layer0_results_give_the_replay_result(monkeypatch, capfd):
    """O31: in the plain order each tile keeps layer 0's msgf and D from its forward sweep of layer 0, and its
    backward sweep of layer 0 reads them instead of replaying the forward (density layer 0 with the hidden table:
    OMAT-0 medium). Same tiles and kernels: the replay's numbers up to the order of the float32 atomic sums, in the
    call that builds the lists and in a kept call."""
    at = _oxide(8)                                     # 2,560 atoms
    moved = at.positions + np.random.default_rng(10).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "0")
    monkeypatch.setenv("LOUP_DEBUG_TILE_TIMES", "1")

    def run(keep):
        monkeypatch.setenv("LOUP_TILE_KEEP_L0", keep)
        eng = LoupEngine(bundle)
        try:
            capfd.readouterr()
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, 300, skin=SKIN) for x in (at.positions, moved)]
            said = [line for line in capfd.readouterr().err.splitlines() if line.startswith("tile layer 0 kept:")]
            return out, said
        finally:
            del eng
            gc.collect()

    (replay, said0), (kept, said1) = run("0"), run("1")
    assert said0 and said0[0].startswith("tile layer 0 kept: no")
    assert said1 and said1[0].startswith("tile layer 0 kept: yes")
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(replay, kept):
        assert t0 == t1 >= 4
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


def test_the_plan_moves_the_tile_lists_to_host_memory_only_when_they_do_not_fit(monkeypatch):
    """O31 (S5-T07): the memory plan keeps the tile lists on the device while some cap fits; below the smallest
    memory fraction at which one does, it moves their edge arrays to host memory (host_lists, host_bytes) instead
    of refusing the system."""
    at = _oxide(20)                                    # 40,000 atoms
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "0")    # the lists only (the layer state: the next test)
    eng = LoupEngine(bundle)
    try:
        def plan(fraction, host=None):
            if host is None:
                monkeypatch.delenv("LOUP_TILE_HOST_LISTS", raising=False)
            else:
                monkeypatch.setenv("LOUP_TILE_HOST_LISTS", host)
            eng.set_execution(_core.LOUP_EXEC_TILED, 0, fraction)
            try:
                return eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=SKIN)
            except BackendError:
                return None

        dev, forced = plan(0.9, "0"), plan(0.9, "1")
        assert dev is not None and not dev.host_lists and dev.host_bytes == 0
        assert forced.host_lists and forced.host_bytes > 0
        # the same cap on both sides. The edges leave the device and two staging buffers of the largest tile's edges
        # come (tile-plan-exact: the plan counts what the call holds), so with one or two tiles the device figure
        # stays about where it was.
        assert forced.receivers == dev.receivers
        device = lambda p: p.tiled_global_bytes + p.tile_workspace_bytes
        assert device(forced) <= 1.05 * device(dev)
        # the smallest fraction that fits with the lists on the device, to 0.1%
        # a fixed free memory for the plan: the true figure moves by MB between two plans (other programs)
        monkeypatch.setenv("LOUP_DEBUG_PLAN_FREE", "8000")
        lo, hi = 1e-4, 0.9
        while hi - lo > 1e-3 * hi:
            mid = 0.5 * (lo + hi)
            lo, hi = (lo, mid) if plan(mid, "0") is not None else (mid, hi)
        assert plan(hi).host_lists is False         # automatic choice: still on the device at that fraction
        below = plan(lo * 0.999)
        assert below is not None and below.host_lists and below.receivers >= 4096
        assert plan(lo * 0.999, "0") is None         # and refused when host lists are off
    finally:
        del eng
        gc.collect()


def test_the_plan_moves_the_layer_state_to_host_memory_only_when_the_lists_there_are_not_enough(monkeypatch):
    """O32 (S5-T07 step 2): below the smallest memory fraction at which a cap fits with the tile lists in host
    memory, the plan also moves the layer outputs and their gradients there (host_state) instead of refusing the
    system; refused with LOUP_TILE_HOST_STATE=0. The call it plans runs with the layer state in host memory and
    gives the device state's numbers."""
    at = _oxide(20)                                    # 40,000 atoms
    bundle = ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "0")
    eng = LoupEngine(bundle)
    try:
        def plan(fraction, state=None):
            if state is None:
                monkeypatch.delenv("LOUP_TILE_HOST_STATE", raising=False)
            else:
                monkeypatch.setenv("LOUP_TILE_HOST_STATE", state)
            eng.set_execution(_core.LOUP_EXEC_TILED, 0, fraction)
            try:
                return eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=SKIN)
            except BackendError:
                return None

        # a fixed free memory for the plan: the true figure moves by MB between two plans (other programs)
        monkeypatch.setenv("LOUP_DEBUG_PLAN_FREE", "8000")
        lo, hi = 1e-4, 0.9                             # the smallest fraction with the state on the device
        while hi - lo > 1e-3 * hi:
            mid = 0.5 * (lo + hi)
            lo, hi = (lo, mid) if plan(mid, "0") is not None else (mid, hi)
        at_hi = plan(hi)
        assert at_hi is not None and not at_hi.host_state
        below = plan(lo * 0.999)
        assert below is not None and below.host_state and below.host_lists and below.receivers >= 4096
        assert below.host_bytes > at_hi.host_bytes
        assert plan(lo * 0.999, "0") is None
        # the planned call: host state, the device state's numbers
        assert plan(lo * 0.999) is not None
        e1, f1, s1, _ = eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, 0, skin=SKIN)
        assert eng.last_execution().host_state
    finally:
        del eng
        gc.collect()
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "0")
    ref = LoupEngine(bundle)
    try:
        ref.set_execution(_core.LOUP_EXEC_TILED, below.receivers, 0.9)
        e0, f0, s0, _ = ref.evaluate_tiled(at.numbers, at.positions, at.cell.array, below.receivers, skin=SKIN)
        assert not ref.last_execution().host_state
    finally:
        del ref
        gc.collect()
    assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8


@pytest.mark.full
def test_a_forced_host_state_beyond_the_host_memory_is_refused(monkeypatch):
    """O32: LOUP_TILE_HOST_STATE=1 skips the plan's 60% limit, but a plan that would pin more than 90% of the available
    host memory is refused instead of pinning it (8,008,065 atoms with the wavefront's host pool forced planned 42.1 GB
    against 40.1 GB available and took the WSL distro down). Skips where the host has room for that plan."""
    with open("/proc/meminfo") as f:
        avail = next(int(line.split()[1]) * 1024 for line in f if line.startswith("MemAvailable:"))
    if avail > 45e9:
        pytest.skip(f"{avail / 1e9:.0f} GB of host memory available: the forced plan of 42 GB would fit")
    at = srtio3(117)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    monkeypatch.setenv("LOUP_TILE_HOST_STATE", "1")
    monkeypatch.setenv("LOUP_TILE_WAVEFRONT", "1")
    eng = LoupEngine(bundle)
    try:
        eng.set_execution(_core.LOUP_EXEC_TILED, 0, 0.9)
        with pytest.raises(BackendError, match="pinned host memory") as caught:
            eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=SKIN)
        assert "LOUP_TILE_HOST_STATE=1" in str(caught.value)
    finally:
        del eng
        gc.collect()


def test_the_tiled_call_is_refused_for_long_range_models():
    at = _oxide(1)
    bundle = ensure_loup_bundle(find_model("MACE-POLAR-1-S.model"), [8, 22, 38])
    with pytest.raises(BackendError, match="the tiled call needs a bundle of the generic path without long range"):
        _tiled(bundle, at, 100)


_COUNT_TIMINGS = r"""
import sys, numpy as np
sys.path.insert(0, "tests/gpu")
from gpu_support import find_model, srtio3
from loupmd import LoupEngine, ensure_loup_bundle
at = srtio3(20)
at.positions += np.random.default_rng(11).normal(scale=0.03, size=at.positions.shape)
eng = LoupEngine(ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38]))
e, f, _, tiles = eng.evaluate_tiled(at.numbers, at.positions, at.cell.array, 5000, skin=0.5)
print("RESULT", repr(e / len(at)), tiles)
np.save(sys.argv[1], f)
"""


@pytest.mark.full
def test_tile_gemm_buckets_time_fewer_shapes_and_keep_the_result(tmp_path):
    """S5-T10: in the tiled call a GEMM decision timed for one row count serves its size bucket (four per octave),
    so the first call on a new workspace times far fewer shapes. LOUP_TILE_GEMM_BUCKETS=0 times every row count.
    Each side runs in a process of its own with an empty plan cache and without hybrids (the same kernels either
    way, so the bound is float32 rounding of other GEMM tilings)."""
    import os
    import pathlib
    import subprocess
    import sys
    import time

    runs = {}
    for buckets in ("1", "0"):
        env = dict(os.environ, LOUP_TILE_GEMM_BUCKETS=buckets, LOUP_DEBUG_GEMM="1", LOUP_NO_HYBRID="1",
                   LOUP_CACHE_DIR=str(tmp_path / f"plans{buckets}"))
        start = time.perf_counter()
        done = subprocess.run([sys.executable, "-c", _COUNT_TIMINGS, str(tmp_path / f"f{buckets}.npy")], env=env,
                              capture_output=True, text=True, cwd=pathlib.Path(__file__).resolve().parents[2])
        wall = time.perf_counter() - start
        assert done.returncode == 0, done.stderr[-2000:]
        result = [line.split() for line in done.stdout.splitlines() if line.startswith("RESULT")][0]
        timed = sum(line.startswith("gemm M=") for line in done.stderr.splitlines())
        runs[buckets] = (float(result[1]), int(result[2]), timed, wall, np.load(tmp_path / f"f{buckets}.npy"))
    (e1, t1, n1, w1, f1), (e0, t0, n0, w0, f0) = runs["1"], runs["0"]
    print(f"tile GEMM buckets: {t1} tiles; shapes timed {n1} with buckets, {n0} without; process wall {w1:.1f} s "
          f"and {w0:.1f} s; dE {abs(e1 - e0):.2e} eV/atom, dF {np.abs(f1 - f0).max():.2e} eV/A")
    assert t1 == t0 >= 4
    assert n1 <= 0.6 * n0
    assert abs(e1 - e0) <= 1e-7 and np.abs(f1 - f0).max() <= 1e-5


@pytest.mark.parametrize("model,structure,receivers,saved_mib", [
    ("mace-omat-0-small.model", lambda: _oxide(16), 5000, 64),                    # 20,480 atoms
    ("MACE-omol-0-extra-large-1024.model", lambda: _water((2, 1, 1)), 400, 0),   # three layers: five sweeps
], ids=["omat-0-small", "omol-0-xl"])
def test_a_tiles_layers_share_one_arena_and_give_the_same_result(model, structure, receivers, saved_mib, monkeypatch):
    """tile-shared-layers: a sweep runs one layer, so a tiled system keeps its layers' own buffers in one arena as
    large as the largest layer; LOUP_TILE_SHARE_LAYERS=0 gives every buffer its own memory. Same kernels and
    operations: the numbers agree up to the order of the float32 atomic sums, in the building call and a kept one.
    The plan's cap and whole-system count are the same, its tile workspace is at least a fifth smaller, and the
    call's device peak is lower: by 38 KiB per receiver for OMAT-0 small, about 190 MiB at 5,000. (The peak is read
    from the device's free memory, which other programs move by tens of MiB: asked only where the saving is far above
    that.)"""
    at = structure()
    moved = at.positions + np.random.default_rng(23).normal(scale=0.01, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model(model), sorted(set(at.get_atomic_numbers().tolist())))
    monkeypatch.setenv("LOUP_NO_HYBRID", "1")

    def run(share):
        monkeypatch.setenv("LOUP_TILE_SHARE_LAYERS", share)
        eng = LoupEngine(bundle)
        try:
            eng.set_execution(_core.LOUP_EXEC_TILED, receivers, 0.9)
            plan = eng.plan_execution(at.numbers, at.positions, at.cell.array, skin=SKIN)
            out = [eng.evaluate_tiled(at.numbers, x, at.cell.array, receivers, skin=SKIN)
                   for x in (at.positions, moved)]
            return plan, out, eng.last_execution().peak_bytes
        finally:
            del eng
            gc.collect()

    (plan_own, own, peak_own), (plan_shared, shared, peak_shared) = run("0"), run("1")
    assert plan_shared.receivers == plan_own.receivers
    assert plan_shared.tile_workspace_bytes < 0.8 * plan_own.tile_workspace_bytes
    assert abs(plan_shared.whole_bytes - plan_own.whole_bytes) <= 0.01 * plan_own.whole_bytes
    if saved_mib:
        assert peak_own - peak_shared > saved_mib * 2**20, (peak_shared, peak_own)
    for (e0, f0, s0, t0), (e1, f1, s1, t1) in zip(own, shared):
        assert t0 == t1 >= 2
        assert abs(e1 - e0) / len(at) <= 1e-8 and np.abs(f1 - f0).max() <= 1e-5 and np.abs(s1 - s0).max() <= 1e-8
