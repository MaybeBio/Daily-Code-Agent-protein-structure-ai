"""loup_compute_device (LAMMPS_KOKKOS_PLAN.md stage B): the evaluation on arrays that stay on the GPU, as the LAMMPS
Kokkos pair style calls it, and loup_evaluate's one-graph path, on every neighbour-rebuild path of the step graph they
share with the MD loop. The device arrays here are torch CUDA tensors."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np
import pytest
from gpu_support import ROOT, find_model, srtio3

from loupmd import LoupEngine, ensure_loup_bundle

torch = pytest.importorskip("torch")
pytestmark = pytest.mark.skipif(not torch.cuda.is_available(), reason="needs a CUDA device")


def _bundle():
    return ensure_loup_bundle(find_model("mace-omat-0-small.model"), [8, 22, 38])


def _engine(n_rep=3, seed=3):
    at = srtio3(n_rep)
    at.positions += np.random.default_rng(seed).normal(scale=0.05, size=at.positions.shape)
    eng = LoupEngine(_bundle())
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    return at, eng


def _virial(stress, volume):
    """loup_evaluate's stress (dE/d strain / V, 3 x 3) as loup_compute_device's virial (xx yy zz xy xz yz, eV)."""
    return -volume * np.array([stress[0, 0], stress[1, 1], stress[2, 2], stress[0, 1], stress[0, 2], stress[1, 2]])


def test_device_call_matches_evaluate_for_shuffled_rows_and_both_layouts():
    at, eng = _engine()
    n = len(at)
    cell = at.cell.array
    e_ref, f_ref, s_ref = eng.evaluate(at.positions, cell)

    # rows in another order than the engine's atoms, as LAMMPS's local atoms are after sorting
    order = np.random.default_rng(0).permutation(n)
    ids = torch.tensor(order, dtype=torch.int32, device="cuda")
    x = torch.tensor(at.positions[order], dtype=torch.float64, device="cuda")

    # row-major [n][3] forces (strides 3, 1)
    f = torch.zeros((n, 3), dtype=torch.float64, device="cuda")
    e, v = eng.compute_device(x.data_ptr(), cell, f.data_ptr(), ids.data_ptr(), virial=True)
    assert abs(e - e_ref) < 1e-6 * n
    assert np.abs(f.cpu().numpy() - f_ref[order]).max() < 2e-5
    assert np.abs(v - _virial(s_ref, at.get_volume())).max() < 2e-4

    # column-major [n_alloc][3] forces with n_alloc > n (Kokkos::LayoutLeft, strides 1, n_alloc); forces are added
    n_alloc = n + 7
    g = torch.full((3, n_alloc), 1.0, dtype=torch.float64, device="cuda")
    e2, _ = eng.compute_device(x.data_ptr(), cell, g.data_ptr(), ids.data_ptr(), f_strides=(1, n_alloc))
    assert abs(e2 - e_ref) < 1e-6 * n
    got = g.cpu().numpy()
    assert np.abs(got[:, :n].T - 1.0 - f_ref[order]).max() < 2e-5
    assert np.all(got[:, n:] == 1.0)  # rows beyond n_rows untouched


# The step graph's rebuild paths (LOUP_MD_REBUILD, read when an engine is created) and the atom reorder.
PATHS = [
    pytest.param({}, id="device-rebuild"),
    pytest.param({"LOUP_MD_REBUILD": "host"}, id="host-rebuild"),
    pytest.param({"LOUP_MD_REBUILD": "fallback"}, id="fallback-rebuild"),
    pytest.param({"LOUP_REORDER": "1"}, id="atom-reorder"),
]


@pytest.mark.parametrize("env", PATHS)
@pytest.mark.parametrize("call", ["device", "evaluate"])
def test_calls_follow_moves_and_neighbour_rebuilds(env, call, monkeypatch):
    """Small moves keep the list, moves beyond skin / 2 rebuild it (the first one host-driven, with the variant
    timing; later ones on the path under test): every result equals a freshly built list's."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    at, eng = _engine()
    for k in env:
        monkeypatch.delenv(k)
    ref = LoupEngine(_bundle())  # the reference: default paths, the system set again (a new list) for every call
    n = len(at)
    cell = at.cell.array
    z, m = at.get_atomic_numbers(), at.get_masses()
    rng = np.random.default_rng(1)
    x = torch.tensor(at.positions, dtype=torch.float64, device="cuda")
    f = torch.zeros((n, 3), dtype=torch.float64, device="cuda")
    pos = at.positions.copy()
    for step, scale in enumerate([0.0, 0.01, 0.15, 0.01, 0.15, 0.01, 0.15, 0.01]):
        pos = pos + rng.normal(scale=scale, size=pos.shape)
        if call == "device":
            x.copy_(torch.tensor(pos, dtype=torch.float64))
            f.zero_()
            # without energy the call returns early: the forces are read after the default stream is synchronised
            eng.compute_device(x.data_ptr(), cell, f.data_ptr(), energy=False)
            torch.cuda.synchronize()
            forces = f.cpu().numpy()
            e, _ = eng.compute_device(x.data_ptr(), cell, 0)
        else:
            e, forces, _ = eng.evaluate(pos, cell)
        ref.set_system(z, m, skin=0.5)
        e_ref, f_ref, _ = ref.evaluate(pos, cell)
        assert abs(e - e_ref) < 1e-6 * n, step
        assert np.abs(forces - f_ref).max() < 5e-5, step


def test_device_call_refuses_a_wrong_row_count_and_a_bad_id():
    at, eng = _engine(2)
    n = len(at)
    cell = at.cell.array
    x = torch.tensor(at.positions, dtype=torch.float64, device="cuda")
    f = torch.zeros((n, 3), dtype=torch.float64, device="cuda")
    ids = torch.arange(n, dtype=torch.int32, device="cuda")
    e0, _ = eng.compute_device(x.data_ptr(), cell, f.data_ptr(), ids.data_ptr())
    ids[0] = n  # outside 0 .. n-1
    with pytest.raises(RuntimeError):
        eng.compute_device(x.data_ptr(), cell, f.data_ptr(), ids.data_ptr())
    ids[0] = 0  # the corrected call is accepted again
    e1, _ = eng.compute_device(x.data_ptr(), cell, f.data_ptr(), ids.data_ptr())
    assert abs(e1 - e0) < 1e-6 * n
    eng._n = n - 1  # a row count that is not the system's
    with pytest.raises(RuntimeError):
        eng.compute_device(x.data_ptr(), cell, f.data_ptr())
    eng._n = n


_FIRST_CALL = r"""
import json, sys
import numpy as np
sys.path.insert(0, sys.argv[1])
from loupmd import LoupEngine
d = np.load(sys.argv[3])
eng = LoupEngine(sys.argv[2])
eng.set_system(d["z"], d["m"], skin=0.5)
eng.set_state(d["pos"], None, d["cell"])
if sys.argv[4] == "evaluate":
    e, f, _ = eng.evaluate(d["pos"], d["cell"])
else:
    import torch
    x = torch.tensor(d["pos"], dtype=torch.float64, device="cuda")
    ft = torch.zeros(d["pos"].shape, dtype=torch.float64, device="cuda")
    e, _ = eng.compute_device(x.data_ptr(), d["cell"], ft.data_ptr())
    torch.cuda.synchronize()
    f = ft.cpu().numpy()
print("RESULT " + json.dumps({"e": e, "f": np.asarray(f).tolist()}))
"""


@pytest.mark.parametrize("call", ["evaluate", "device"])
def test_a_call_right_after_set_state_tunes_before_it_captures(call, tmp_path):
    """loup_set_state builds the list and runs no force pass, so the GEMM plans are untuned. A step graph must not be
    captured on them: where the call was the process's first force pass, the capture failed with a cuBLAS error
    (MACE-OMAT-0 medium, 320 atoms). The call runs in a process of its own with an empty plan folder: an engine that
    evaluated earlier in the process, or plan files on disk, hide the failure."""
    at = srtio3(4)
    at.positions += np.random.default_rng(3).normal(scale=0.05, size=at.positions.shape)
    bundle = ensure_loup_bundle(find_model("mace-omat-0-medium.model"), [8, 22, 38])
    np.savez(tmp_path / "s.npz", z=at.get_atomic_numbers(), m=at.get_masses(), pos=at.positions, cell=at.cell.array)
    env = dict(os.environ, LOUP_CACHE_DIR=str(tmp_path / "plans"))
    p = subprocess.run([sys.executable, "-c", _FIRST_CALL, str(ROOT), str(bundle), str(tmp_path / "s.npz"), call],
                       env=env, capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, (p.stdout + p.stderr)[-2000:]
    out = json.loads(next(line for line in p.stdout.splitlines() if line.startswith("RESULT "))[7:])
    ref = LoupEngine(bundle)
    ref.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    e_ref, f_ref, _ = ref.evaluate(at.positions, at.cell.array)
    assert abs(out["e"] - e_ref) < 1e-6 * len(at)
    assert np.abs(np.array(out["f"]) - f_ref).max() < 5e-5


def test_run_calls_in_blocks_continue_one_trajectory():
    """Run calls with the same parameters reuse their graphs: two NVE blocks give the positions of one run."""
    at, eng = _engine()
    vel = np.random.default_rng(5).normal(scale=0.02, size=at.positions.shape)
    eng.set_state(at.positions, vel, at.cell.array)
    eng.run_nve(40, dt_fs=0.5)
    pos_one, _, _, _ = eng.get_state()
    at2, eng2 = _engine()
    eng2.set_state(at2.positions, vel, at2.cell.array)
    eng2.run_nve(20, dt_fs=0.5)
    eng2.run_nve(20, dt_fs=0.5)
    pos_two, _, _, _ = eng2.get_state()
    assert np.abs(pos_one - pos_two).max() < 1e-6


def test_model_facts():
    at, eng = _engine(2)
    assert eng.cutoff() == pytest.approx(6.0)
    assert sorted(eng.species()) == [8, 22, 38]


def test_evaluate_ahead_changes_no_result_and_yields_to_every_other_call():
    """loup_set_evaluate_ahead: the next call's force pass is queued ahead after two calls in a row. Results are those
    of a freshly built list throughout: through a neighbour rebuild, a call with the other stress flag, a new cell, a
    run, a state read, a new system, and with a pass still queued when the engine goes.

    While a pass is queued nothing else in the process may use the GPU, so the references are made first and their
    engine is gone before the setting is switched on."""
    import gc

    at, eng = _engine()
    n = len(at)
    cell = at.cell.array
    z, m = at.get_atomic_numbers(), at.get_masses()
    rng = np.random.default_rng(11)
    seq, pos = [], at.positions.copy()
    for scale in [0.0, 0.01, 0.01, 0.01, 0.15, 0.01, 0.01, 0.01, 0.15, 0.01, 0.01, 0.01]:
        pos = pos + rng.normal(scale=scale, size=pos.shape)
        seq.append(pos.copy())
    cell2 = cell * 1.002
    ref = LoupEngine(_bundle())
    refs = []
    for k, x in enumerate(seq):
        ref.set_system(z, m, skin=0.5)
        refs.append(ref.evaluate(x, cell2 if k == 9 else cell))
    del ref
    gc.collect()

    def same(got, k, forces_only=False):
        e_ref, f_ref, s_ref = refs[k]
        assert abs(got[0] - e_ref) < 1e-6 * n, k
        assert np.abs(got[1] - f_ref).max() < 5e-5, k
        if not forces_only:
            assert np.abs(got[2] - s_ref).max() < 2e-6, k

    eng.set_evaluate_ahead(True)
    try:
        for k, x in enumerate(seq):
            if k == 9:
                same(eng.evaluate(x, cell2), k)  # another cell: the queued pass is let run and dropped
                continue
            same(eng.evaluate(x, cell), k)
            if k == 3:
                same(eng.evaluate(x, cell, compute_stress=False), k, forces_only=True)  # the other stress flag
            if k == 6:
                eng.set_state(x, np.zeros_like(x), cell)  # a run and a state read, with a pass queued before them
                eng.run_nve(3, dt_fs=0.5)
                assert np.isfinite(eng.get_state()[0]).all()
        eng.set_system(z, m, skin=0.5)  # a new system with a pass queued
        same(eng.evaluate(seq[0], cell), 0)
        same(eng.evaluate(seq[1], cell), 1)
        same(eng.evaluate(seq[2], cell), 2)  # a pass is queued now
    finally:
        eng.set_evaluate_ahead(False)  # lets a queued pass run: later tests use the GPU
    same(eng.evaluate(seq[3], cell), 3)
    eng.set_evaluate_ahead(True)
    eng.evaluate(seq[3], cell)
    eng.evaluate(seq[3], cell)
    eng.evaluate(seq[3], cell)
    del eng  # destroyed with a pass queued
    gc.collect()
