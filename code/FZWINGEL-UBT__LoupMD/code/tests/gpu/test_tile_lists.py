"""Per-tile neighbour lists (plan task S5-T02): each tile of the planner (S5-T01) is an open domain whose ghosts are
its ghost candidates, and the engine's list of that domain holds the tile's edges. Together the tiles must hold
exactly the whole-system list: every edge once, at the right periodic image. Candidates that send along no edge
are dropped, and the list of the tile without them is the same."""
from __future__ import annotations

import ctypes

import numpy as np
import pytest
from gpu_support import srtio3

from loupmd import BackendError, LoupEngine
from loupmd import _core

SKIN = 0.5
c_ll, c_int, c_double, ptr = ctypes.c_longlong, ctypes.c_int, ctypes.c_double, ctypes.POINTER


def _bind(lib):
    lib.loup_tile_plan.argtypes = [ptr(c_double), c_ll, ptr(c_double), c_int, c_ll, ptr(c_int), c_double, ptr(c_int),
                                   ptr(c_ll), ptr(c_ll), ptr(c_int)]
    lib.loup_tile_plan_copy.argtypes = [ptr(c_ll), ptr(c_int), ptr(c_int), ptr(c_ll), ptr(c_int), ptr(c_int)]
    lib.loup_tile_plan_error.restype = ctypes.c_char_p
    lib.loup_debug_set_domain.argtypes = [ctypes.c_void_p, c_int, c_int, ptr(c_int), c_double]
    lib.loup_debug_domain_edges.argtypes = [ctypes.c_void_p, ptr(c_double), ptr(c_double), c_ll, ptr(c_int),
                                            ptr(c_int), ptr(c_double), ptr(c_ll), ptr(ctypes.c_ubyte)]


def _check(eng, rc, call):
    if rc != 0:
        raise BackendError(_core.last_error(eng._h), call=call)


def _edges(eng, positions, cell, n_ghost=0):
    """Receivers, senders, shifts and (for a domain) the used-ghost mask of the handle's list for ``positions``."""
    lib = eng._lib
    pos = np.ascontiguousarray(positions, dtype=np.float64)
    cel = np.ascontiguousarray(cell, dtype=np.float64)
    count = c_ll()
    used = np.zeros(max(n_ghost, 1), np.uint8)
    _check(eng, lib.loup_debug_domain_edges(eng._h, pos.ctypes.data_as(ptr(c_double)), cel.ctypes.data_as(ptr(c_double)),
                                            0, None, None, None, ctypes.byref(count),
                                            used.ctypes.data_as(ptr(ctypes.c_ubyte)) if n_ghost else None),
           "loup_debug_domain_edges")
    e = count.value
    rcv, snd, sh = np.empty(e, np.int32), np.empty(e, np.int32), np.empty((e, 3))
    _check(eng, lib.loup_debug_domain_edges(eng._h, pos.ctypes.data_as(ptr(c_double)), cel.ctypes.data_as(ptr(c_double)),
                                            e, rcv.ctypes.data_as(ptr(c_int)), snd.ctypes.data_as(ptr(c_int)),
                                            sh.ctypes.data_as(ptr(c_double)), ctypes.byref(count), None),
           "loup_debug_domain_edges")
    assert count.value == e
    return rcv, snd, sh, used[:n_ghost].astype(bool)


def _plan(lib, positions, cell, receivers, reach):
    pos = np.ascontiguousarray(positions, dtype=np.float64)
    cel = np.ascontiguousarray(cell, dtype=np.float64)
    tiles, ghosts, grid = c_ll(), c_ll(), (c_int * 3)()
    rc = lib.loup_tile_plan(pos.ctypes.data_as(ptr(c_double)), len(pos), cel.ctypes.data_as(ptr(c_double)), receivers,
                            0, None, reach, None, ctypes.byref(tiles), ctypes.byref(ghosts), grid)
    assert rc == 0, lib.loup_tile_plan_error()
    t, g, n = tiles.value, ghosts.value, len(pos)
    out = dict(local_ptr=np.empty(t + 1, np.int64), local=np.empty(n, np.int32), local_shift=np.empty((n, 3), np.int32),
               ghost_ptr=np.empty(t + 1, np.int64), ghost=np.empty(g, np.int32), ghost_shift=np.empty((g, 3), np.int32))
    assert lib.loup_tile_plan_copy(out["local_ptr"].ctypes.data_as(ptr(c_ll)), out["local"].ctypes.data_as(ptr(c_int)),
                                   out["local_shift"].ctypes.data_as(ptr(c_int)),
                                   out["ghost_ptr"].ctypes.data_as(ptr(c_ll)), out["ghost"].ctypes.data_as(ptr(c_int)),
                                   out["ghost_shift"].ctypes.data_as(ptr(c_int))) == 0
    out["tiles"], out["grid"] = t, tuple(grid)
    return out


def _keys(receiver, sender, image, n):
    """One integer per edge: receiver, sender and the sender's periodic image (each component -2 .. 2)."""
    assert np.abs(image).max(initial=0) <= 2
    im = image + 2
    return ((receiver.astype(np.int64) * n + sender) * 125 + im[:, 0] * 25 + im[:, 1] * 5 + im[:, 2])


def _crystal():
    at = srtio3(20)                                      # 40,000 atoms
    at.positions += np.random.default_rng(11).normal(scale=0.05, size=at.positions.shape)
    at.set_cell(at.cell.array * np.array([[1.0, 0.01, 0.0], [0.0, 1.0, 0.006], [0.004, 0.0, 1.0]]), scale_atoms=True)
    return at


# 12,000 receivers: one block cut into four pieces in atom order; 3,000: a grid of blocks, as FastMACE plans them
@pytest.mark.parametrize("receivers", [12000, 3000])
def test_the_tiles_lists_together_are_the_whole_system_list(sto_bundle, receivers):
    at = _crystal()
    n, cell, pos = len(at), at.cell.array, at.positions
    z = at.get_atomic_numbers()
    whole = LoupEngine(sto_bundle)
    _bind(whole._lib)
    whole.set_system(z, at.get_masses(), skin=SKIN)
    r_list = whole.info().r_max + SKIN
    rcv, snd, sh, _ = _edges(whole, pos, cell)
    image = np.rint(-sh @ np.linalg.inv(cell)).astype(np.int64)      # the sender's image: pos[s] + image @ cell
    assert np.allclose(image @ cell, -sh, atol=1e-9)
    whole_keys = _keys(rcv, snd, image, n)
    assert len(np.unique(whole_keys)) == len(whole_keys)
    whole_len = np.linalg.norm(pos[rcv] - (pos[snd] + image @ cell), axis=1)

    plan = _plan(whole._lib, pos, cell, receivers, r_list + 0.01)
    assert plan["tiles"] >= 4
    tile_keys, tile_len = [], []
    dropped = candidates = 0
    eng = LoupEngine(sto_bundle)
    _bind(eng._lib)
    for t in range(plan["tiles"]):
        loc = plan["local"][plan["local_ptr"][t]:plan["local_ptr"][t + 1]]
        lsh = plan["local_shift"][plan["local_ptr"][t]:plan["local_ptr"][t + 1]]
        gho = plan["ghost"][plan["ghost_ptr"][t]:plan["ghost_ptr"][t + 1]]
        gsh = plan["ghost_shift"][plan["ghost_ptr"][t]:plan["ghost_ptr"][t + 1]]
        place = np.concatenate([pos[loc] + lsh @ cell, pos[gho] + gsh @ cell])
        atom = np.concatenate([loc, gho])
        shift = np.concatenate([lsh, gsh]).astype(np.int64)
        pad = r_list + 1.0                             # the box's own images then lie beyond the list's reach
        origin = place.min(axis=0) - pad
        box = np.diag(np.ptp(place, axis=0) + 2.0 * pad)

        def domain(keep):
            zz = np.ascontiguousarray(z[atom[keep]], dtype=np.int32)
            _check(eng, eng._lib.loup_debug_set_domain(eng._h, len(loc), len(zz) - len(loc),
                                                       zz.ctypes.data_as(ptr(c_int)), SKIN), "loup_debug_set_domain")
            r, s, d_sh, used = _edges(eng, place[keep] - origin, box, len(zz) - len(loc))
            assert not d_sh.any(), "an open domain's edges have no periodic shift"
            a_r, a_s = atom[keep][r], atom[keep][s]
            img = shift[keep][s] - shift[keep][r]      # the sender's image relative to the receiver's
            return _keys(a_r, a_s, img, n), np.linalg.norm(place[keep][r] - place[keep][s], axis=1), used

        everything = np.arange(len(atom))
        keys, lengths, used = domain(everything)
        assert len(used) == len(gho)
        candidates += len(gho)
        dropped += int((~used).sum())
        if t < 2:                                      # without the unused candidates the list is the same
            kept = np.concatenate([np.arange(len(loc)), len(loc) + np.nonzero(used)[0]])
            keys_kept, _, used_kept = domain(kept)
            assert used_kept.all()
            assert np.array_equal(np.sort(keys_kept), np.sort(keys))
        tile_keys.append(keys)
        tile_len.append(lengths)

    tile_keys = np.concatenate(tile_keys)
    tile_len = np.concatenate(tile_len)
    assert len(np.unique(tile_keys)) == len(tile_keys), "an edge is in two tiles"
    only_whole = ~np.isin(whole_keys, tile_keys)
    only_tiles = ~np.isin(tile_keys, whole_keys)
    # A pair at the list's radius may fall on either side in float arithmetic of another frame; nothing else may
    # differ (the build's own boundary margin is 0.01 A or more).
    band = 0.02
    print(f"tiles {plan['tiles']} grid {plan['grid']}: {len(whole_keys)} edges; {only_whole.sum()} only in the whole "
          f"list, {only_tiles.sum()} only in the tiles; candidates {candidates}, dropped {dropped} "
          f"({dropped / max(candidates, 1):.1%})")
    assert np.all(np.abs(whole_len[only_whole] - r_list) < band)
    assert np.all(np.abs(tile_len[only_tiles] - r_list) < band)
    assert only_whole.sum() + only_tiles.sum() <= 1e-4 * len(whole_keys)
    assert dropped > 0
