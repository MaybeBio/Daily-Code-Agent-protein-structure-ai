"""The engine's error channel (plan task S1-T01): every refused or failed call leaves its reason in
loup_last_error, Python raises it as a BackendError, and the library prints nothing unless LOUP_DEBUG_ERRORS is set."""
from __future__ import annotations

import os
import subprocess
import sys
import threading

import numpy as np
import pytest
from gpu_support import ROOT, srtio3

import loupmd
from loupmd import BackendError, LoupEngine


def _ready(eng, rep=2):
    at = srtio3(rep)
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    return at


def test_refusal_text_reaches_python(sto_engine):
    at = _ready(sto_engine)
    z = at.get_atomic_numbers().copy()
    z[3] = 11  # Na is not in the bundle
    with pytest.raises(BackendError) as info:
        sto_engine.set_system(z, at.get_masses())
    err = info.value
    assert err.call == "loup_set_system"
    assert str(err) == ("loup_set_system: atomic number 11 (atom 3) is not in the bundle, which was exported for "
                        "8, 22, 38")
    assert sto_engine.last_error() == str(err)


def test_message_is_cleared_by_the_next_successful_call(sto_engine):
    at = _ready(sto_engine)
    with pytest.raises(BackendError):
        sto_engine.evaluate(at.positions, np.zeros((3, 3)))
    assert "singular or zero cell" in sto_engine.last_error()
    sto_engine.evaluate(at.positions, at.cell.array)
    assert sto_engine.last_error() == ""


def test_nothing_on_stderr_for_a_handled_error(sto_engine, tmp_path, capfd, monkeypatch):
    monkeypatch.delenv("LOUP_DEBUG_ERRORS", raising=False)
    at = _ready(sto_engine)
    capfd.readouterr()
    with pytest.raises(BackendError):
        sto_engine.set_system(at.get_atomic_numbers(), at.get_masses(), skin=-1.0)
    with pytest.raises(BackendError):
        sto_engine.evaluate(at.positions, np.zeros((3, 3)))
    with pytest.raises(BackendError):
        sto_engine.run_langevin(1, temp_k=float("nan"))
    with pytest.raises(BackendError):
        LoupEngine(tmp_path / "does_not_exist.loup")
    assert capfd.readouterr().err == ""


def test_debug_switch_prints_the_message(tmp_path):
    """LOUP_DEBUG_ERRORS is read by the library, so it is set for a child process."""
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from loupmd import BackendError, LoupEngine\n"
        "try:\n"
        "    LoupEngine(sys.argv[2])\n"
        "except BackendError as err:\n"
        "    print(str(err))\n"
    )
    missing = str(tmp_path / "does_not_exist.loup")
    out = {}
    for debug in (False, True):
        env = {k: v for k, v in os.environ.items() if k != "LOUP_DEBUG_ERRORS"}
        if debug:
            env["LOUP_DEBUG_ERRORS"] = "1"
        out[debug] = subprocess.run([sys.executable, "-c", code, str(ROOT), missing], env=env, capture_output=True,
                                    text=True, check=True)
    message = f"loup_create: Cannot open .loup file: {missing}"
    assert out[False].stdout.strip() == message and out[True].stdout.strip() == message
    assert message not in out[False].stderr
    assert message in out[True].stderr


def test_create_error_is_per_thread(tmp_path):
    seen = {}

    def worker():
        try:
            LoupEngine(tmp_path / "does_not_exist.loup")
        except BackendError as err:
            seen["raised"] = str(err)
        seen["worker"] = loupmd.last_error()

    with pytest.raises(BackendError):
        LoupEngine(tmp_path / "other_missing.loup")
    mine = loupmd.last_error()
    assert "other_missing.loup" in mine
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert "does_not_exist.loup" in seen["raised"] and seen["worker"] == seen["raised"]
    assert loupmd.last_error() == mine  # the worker's failure did not replace this thread's message


def test_a_successful_create_clears_the_threads_create_error(sto_bundle, tmp_path):
    with pytest.raises(BackendError):
        LoupEngine(tmp_path / "does_not_exist.loup")
    assert loupmd.last_error() != ""
    LoupEngine(sto_bundle)
    assert loupmd.last_error() == ""


def _nan(shape, index):
    a = np.zeros(shape)
    a[index] = np.nan
    return a


# (name, what the call needs, the call, a fragment of the reason). `at` is the 40-atom cell of _ready.
REFUSALS = [
    ("no_system_evaluate", "nothing", lambda e, at: e._lib.loup_evaluate(e._h, None, None, 0, None, None, None),
     "loup_evaluate: no system is set (call loup_set_system first)"),
    ("no_system_set_state", "nothing", lambda e, at: e._lib.loup_set_state(e._h, None, None, None),
     "loup_set_state: no system is set"),
    ("no_system_get_state", "nothing", lambda e, at: e._lib.loup_get_state(e._h, None, None, None, None),
     "loup_get_state: no system is set"),
    ("no_system_run", "nothing", lambda e, at: e.run_nve(1), "loup_run_nve: no system is set"),
    ("no_system_profile", "nothing", lambda e, at: e.profile_force(1, 1), "loup_profile_force: no system is set"),
    ("no_atoms", "nothing", lambda e, at: e._lib.loup_set_system(e._h, 0, None, None, 0.5),
     "loup_set_system: n_atoms must be positive, got 0"),
    ("null_species", "nothing", lambda e, at: e._lib.loup_set_system(e._h, 5, None, None, 0.5),
     "loup_set_system: atomic_numbers is NULL"),
    ("skin", "nothing", lambda e, at: e.set_system(at.get_atomic_numbers(), at.get_masses(), skin=float("nan")),
     "loup_set_system: skin must be finite and not negative, got nan A"),
    ("mass", "nothing", lambda e, at: e.set_system(at.get_atomic_numbers(), np.where(np.arange(len(at)) == 7, 0.0,
                                                                                    at.get_masses())),
     "loup_set_system: atom 7 has mass 0 amu; masses must be finite and positive"),
    ("no_positions_run", "system", lambda e, at: e.run_nve(1),
     "loup_run_nve: no positions or neighbour list (call loup_set_state or loup_evaluate first)"),
    ("no_positions_profile", "system", lambda e, at: e.profile_force(1, 1),
     "loup_profile_force: no positions or neighbour list"),
    ("null_positions", "system", lambda e, at: e._lib.loup_evaluate(e._h, None, None, 0, None, None, None),
     "loup_evaluate: positions is NULL"),
    ("nan_cell", "system", lambda e, at: e.evaluate(at.positions, _nan((3, 3), (1, 2)) + at.cell.array),
     "loup_evaluate: non-finite cell entry [1, 2]"),
    ("singular_cell", "system", lambda e, at: e.set_state(at.positions, None, np.zeros((3, 3))),
     "loup_set_state: singular or zero cell (det = 0 A^3); the engine is fully periodic"),
    ("nan_position", "system", lambda e, at: e.evaluate(at.positions + _nan((len(at), 3), (5, 2)), at.cell.array),
     "loup_evaluate: non-finite position (atom 5)"),
    ("nan_velocity", "system", lambda e, at: e.set_state(at.positions, _nan((len(at), 3), (2, 1)), at.cell.array),
     "loup_set_state: non-finite velocity (atom 2)"),
    ("steps", "state", lambda e, at: e.run_nve(0), "loup_run_nve: n_steps must be positive, got 0"),
    ("timestep", "state", lambda e, at: e.run_nve(1, dt_fs=-1.0),
     "loup_run_nve: dt_fs must be finite and positive, got -1 fs"),
    ("langevin_timestep", "state", lambda e, at: e.run_langevin(1, dt_fs=float("inf")),
     "loup_run_langevin: dt_fs must be finite and positive, got inf fs"),
    ("temperature", "state", lambda e, at: e.run_langevin(1, temp_k=-1.0),
     "loup_run_langevin: temp_k must be finite and not negative, got -1 K"),
    ("friction", "state", lambda e, at: e.run_langevin(1, friction_per_fs=float("inf")),
     "loup_run_langevin: friction_per_fs must be finite and not negative, got inf /fs"),
    ("profile_counts", "state", lambda e, at: e.profile_force(-1, 0),
     "loup_profile_force: warmup must not be negative and n_calls must be positive, got -1 and 0"),
]


@pytest.mark.parametrize("needs,call,reason", [r[1:] for r in REFUSALS], ids=[r[0] for r in REFUSALS])
def test_every_refusal_has_its_own_text(sto_engine, needs, call, reason):
    eng = sto_engine
    at = srtio3(2)
    if needs in ("system", "state"):
        eng.set_system(at.get_atomic_numbers(), at.get_masses())
    if needs == "state":
        eng.set_state(at.positions, np.zeros((len(at), 3)), at.cell.array)
    try:
        rc = call(eng, at)
    except BackendError as err:
        assert str(err).startswith(reason), str(err)
    else:  # a direct library call (arguments the Python binding itself would refuse)
        assert rc == -1
    assert eng.last_error().startswith(reason), eng.last_error()


def test_a_null_handle_is_refused_with_a_message():
    lib = loupmd._core._load_lib()
    assert lib.loup_run_nve(None, 1, 1.0, None) == -1
    assert loupmd.last_error() == "loup_run_nve: the handle is NULL"
