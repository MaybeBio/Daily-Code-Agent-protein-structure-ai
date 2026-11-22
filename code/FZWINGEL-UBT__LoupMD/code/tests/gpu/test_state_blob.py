"""loup_export_state / loup_import_state (plan task S1-T06): the state a restart needs as one versioned block.

Every test creates an engine.
"""
from __future__ import annotations

import ctypes
import struct

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

from loupmd import BackendError, LoupEngine

HEADER = 640   # StateHeader of src/engine.cu
LANGEVIN = dict(dt_fs=1.0, temp_k=300.0, friction_per_fs=0.01, seed=5)


def _atoms(rep=3, seed=4):
    at = srtio3(rep)
    at.positions += np.random.default_rng(seed).normal(scale=0.03, size=at.positions.shape)
    return at


def _engine(bundle, at, start=True):
    eng = LoupEngine(bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    if start:
        eng.set_state(at.positions, maxwell_velocities(at, 300.0, 9), at.cell.array)
    return eng


def test_export_destroy_create_import_restores_every_array_bitwise(sto_bundle):
    at = _atoms()
    eng = _engine(sto_bundle, at)
    eng.run_langevin(50, **LANGEVIN)
    pos, vel, _, _ = eng.get_state()
    blob = eng.export_state()
    assert len(blob) == HEADER + 48 * len(at) + 8
    assert blob[:8] == b"LOUPSTA1" and struct.unpack_from("<II", blob, 8) == (1, HEADER)
    n_atoms, _, step_counter = struct.unpack_from("<QQQ", blob, 16)
    assert (n_atoms, step_counter) == (len(at), 50)
    assert np.array_equal(np.frombuffer(blob, dtype="<f8", count=9, offset=48).reshape(3, 3), at.cell.array)
    del eng

    fresh = _engine(sto_bundle, at, start=False)
    fresh.import_state(blob)
    pos2, vel2, _, _ = fresh.get_state()
    assert np.array_equal(pos2, pos) and np.array_equal(vel2, vel)
    assert fresh.export_state() == blob  # step counter, displacement tracker and cell included


def test_a_resumed_langevin_run_continues_the_uninterrupted_one(sto_bundle):
    """50 steps, export, a new engine, import, 100 more steps: within a few times the difference of two
    uninterrupted runs of 150 steps (and below the plan's 1e-4 A), so the noise stream continued."""
    at = _atoms()

    def uninterrupted():
        eng = _engine(sto_bundle, at)
        eng.run_langevin(50, **LANGEVIN)
        eng.run_langevin(100, **LANGEVIN)
        return eng.get_state()[0]

    ref_a, ref_b = uninterrupted(), uninterrupted()
    first = _engine(sto_bundle, at)
    first.run_langevin(50, **LANGEVIN)
    blob = first.export_state()
    del first
    resumed = _engine(sto_bundle, at, start=False)
    resumed.import_state(blob)
    resumed.run_langevin(100, **LANGEVIN)
    spread = np.abs(ref_a - ref_b).max()
    diff = np.abs(resumed.get_state()[0] - ref_a).max()
    assert diff <= max(5.0 * spread, 1e-7), (diff, spread)
    assert diff < 1e-4

    replayed = _engine(sto_bundle, at)  # the check of the check: a noise stream restarted at step 0 is far off
    replayed.run_langevin(50, **LANGEVIN)
    pos, vel, _, _ = replayed.get_state()
    restart = _engine(sto_bundle, at, start=False)
    restart.set_state(pos, vel, at.cell.array)
    restart.run_langevin(100, **LANGEVIN)
    assert np.abs(restart.get_state()[0] - ref_a).max() > 100.0 * max(diff, 1e-9)


def _patched(blob, offset, fmt, value):
    """``blob`` with one header field replaced and the checksum left as it was."""
    out = bytearray(blob)
    struct.pack_into(fmt, out, offset, value)
    return bytes(out)


def test_blobs_that_do_not_fit_are_refused_with_the_reason(sto_bundle):
    at = _atoms()
    eng = _engine(sto_bundle, at)
    eng.run_nve(5, 1.0)
    blob = eng.export_state()
    pos, vel, _, _ = eng.get_state()

    small = _atoms(rep=2)
    other = _engine(sto_bundle, small)
    with pytest.raises(BackendError, match="loup_import_state: the state blob holds 135 atoms, and the handle's system has 40"):
        other.import_state(blob)

    shuffled = at[::-1]  # the same atoms in another order: positions would land on other species
    reordered = _engine(sto_bundle, shuffled, start=False)
    with pytest.raises(BackendError, match="written for other atomic numbers or another atom order"):
        reordered.import_state(blob)

    cases = [
        (blob[:-8], "the state blob has 7120 bytes, and 7128 are expected for 135 atoms"),
        (blob + b"\0" * 8, "the state blob has 7136 bytes, and 7128 are expected"),
        (blob[:64], "the state blob has 64 bytes, fewer than its header"),
        (b"NOTSTATE" + blob[8:], "not a LoupMD state blob"),
        (_patched(blob, 8, "<I", 2), "the state blob has version 2, and this library reads version 1"),
        (_patched(blob, HEADER + 16, "<d", 1.0), "the state blob is damaged"),
        (_patched(blob, 32, "<Q", 51), "the state blob is damaged"),
    ]
    for bad, reason in cases:
        with pytest.raises(BackendError, match=reason):
            eng.import_state(bad)
    pos2, vel2, _, _ = eng.get_state()  # refused blobs changed nothing
    assert np.array_equal(pos2, pos) and np.array_equal(vel2, vel)
    eng.import_state(blob)
    assert np.isfinite(eng.run_nve(2, 1.0).final_temperature_k)


def test_size_query_small_buffer_and_missing_positions(sto_bundle):
    at = _atoms()
    eng = _engine(sto_bundle, at, start=False)
    with pytest.raises(BackendError, match="loup_export_state: no positions to export"):
        eng.export_state()
    eng.set_state(at.positions, None, at.cell.array)
    need = HEADER + 48 * len(at) + 8
    size = ctypes.c_size_t()
    assert eng._lib.loup_export_state(eng._h, None, 0, ctypes.byref(size)) == 0 and size.value == need
    buf = ctypes.create_string_buffer(100)
    size.value = 0
    assert eng._lib.loup_export_state(eng._h, buf, 100, ctypes.byref(size)) == -1
    assert size.value == need
    assert eng.last_error() == f"loup_export_state: the buffer holds 100 bytes, and the state of 135 atoms needs {need}"
    assert eng._lib.loup_import_state(eng._h, None, need) == -1
    assert eng.last_error() == "loup_import_state: the buffer is NULL"


def test_import_before_a_system_is_refused(sto_bundle):
    eng = LoupEngine(sto_bundle)
    with pytest.raises(BackendError, match="loup_import_state: no system is set"):
        eng.import_state(b"\0" * 200)
