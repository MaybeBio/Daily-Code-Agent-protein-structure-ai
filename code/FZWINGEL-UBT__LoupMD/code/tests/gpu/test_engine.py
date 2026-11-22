"""Engine checks beyond the accuracy gate: MD conservation, neighbour-list safety, input validation, error paths.

Run: python -m pytest tests -v   (the gate itself: tests/test_gate_wrapper.py, slow)
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from gpu_support import maxwell_velocities, srtio3

from loupmd import LoupEngine


def _rattled(atoms, sigma: float, seed: int):
    at = atoms.copy()
    at.positions += np.random.default_rng(seed).normal(0.0, sigma, at.positions.shape)
    return at


def test_nve_energy_conserved(sto_engine):
    at = _rattled(srtio3(4), 0.03, 1)  # 320 atoms
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 600.0, 2), at.cell.array)
    energies, rebuilds = [], 0
    for _ in range(20):  # 2 ps at 1 fs
        st = eng.run_nve(100, 1.0)
        energies.append(st.final_potential_energy_ev + st.final_kinetic_energy_ev)
        rebuilds += st.rebuilds
    e = (np.array(energies) - energies[0]) * 1000.0 / len(at)  # meV/atom
    slope = np.polyfit(np.arange(len(e)) * 0.1, e, 1)[0]  # meV/atom/ps
    assert rebuilds > 0
    assert abs(slope) < 0.05, f"NVE drift {slope:.4f} meV/atom/ps"
    assert np.abs(e).max() < 0.5, f"NVE excursion {np.abs(e).max():.3f} meV/atom"


def test_skin_list_matches_rebuild_every_step(sto_bundle):
    """Skin list (skin 0.5) vs a list rebuilt before every force call (skin 0): same trajectory."""
    at = _rattled(srtio3(3), 0.03, 3)
    v0 = maxwell_velocities(at, 900.0, 4)
    finals = []
    for skin in (0.5, 0.0):
        eng = LoupEngine(sto_bundle)
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=skin)
        eng.set_state(at.positions, v0, at.cell.array)
        st = eng.run_nve(60, 1.0)
        finals.append(eng.get_state())
    (p_a, v_a, f_a, e_a), (p_b, v_b, f_b, e_b) = finals
    # Same edge set, different summation order: agreement to float32 noise amplified over 60 steps.
    assert np.abs(p_a - p_b).max() < 1e-5
    assert np.abs(f_a - f_b).max() < 1e-3
    assert abs(e_a - e_b) / len(at) < 1e-5


@pytest.mark.parametrize("rebuild", ["device", "host", "fallback"])
def test_langevin_skin_list_matches_rebuild_every_step(sto_bundle, monkeypatch, rebuild):
    """Langevin with a small skin (a rebuild every few steps) vs a list rebuilt before every force call, with the
    rebuilds on the GPU inside the step graph, host-driven (the step's force pass skipped, the list rebuilt, the
    checked rest run), or counted on the GPU and finished on the host (LOUP_MD_REBUILD): same noise sequence, same
    trajectory."""
    if rebuild != "device":
        monkeypatch.setenv("LOUP_MD_REBUILD", rebuild)
    at = _rattled(srtio3(3), 0.03, 5)
    v0 = maxwell_velocities(at, 1500.0, 6)
    finals = []
    for skin in (0.2, 0.0):
        eng = LoupEngine(sto_bundle)
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=skin)
        eng.set_state(at.positions, v0, at.cell.array)
        st = eng.run_langevin(60, 1.0, temp_k=1500.0, friction_per_fs=0.02, seed=7)
        assert st.rebuilds > (59 if skin == 0.0 else 5)
        finals.append(eng.get_state())
    (p_a, v_a, f_a, e_a), (p_b, v_b, f_b, e_b) = finals
    assert np.abs(p_a - p_b).max() < 1e-5
    assert np.abs(f_a - f_b).max() < 1e-3
    assert abs(e_a - e_b) / len(at) < 1e-5


def test_tuning_time_reported_separately(sto_engine):
    at = srtio3(4)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.3)
    eng.set_state(at.positions, maxwell_velocities(at, 1500.0, 6), at.cell.array)
    st = eng.run_nve(200, 2.0)
    assert st.rebuilds > 0 and st.tune_ms > 0.0
    st2 = eng.run_nve(200, 2.0)
    assert st2.tune_ms == 0.0  # timed once per system


TIMING = "conv forward us"  # LOUP_DEBUG_SPLINE's line per timed layer


def test_variants_timed_after_50_steps_without_a_rebuild(sto_bundle, monkeypatch, capfd):
    """A cold crystal rebuilds no list, so the first rebuild's timing of the conv forward variants never comes: they
    are timed after 50 force passes instead (tune_early_variants), once and outside step_ms, and the run's forces stay
    those of a fresh engine. LOUP_CONV_TUNE=1 times them on any GPU; LOUP_DEBUG_SPLINE=1 prints each timing."""
    monkeypatch.setenv("LOUP_CONV_TUNE", "1")
    monkeypatch.setenv("LOUP_DEBUG_SPLINE", "1")
    at = srtio3(4)
    eng = LoupEngine(sto_bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 30.0, 4), at.cell.array)
    capfd.readouterr()
    st = eng.run_nve(40, 1.0)
    assert st.rebuilds == 0 and st.tune_ms == 0.0
    assert TIMING not in capfd.readouterr().err
    st = eng.run_nve(20, 1.0)
    assert st.rebuilds == 0 and st.tune_ms > 0.0
    assert TIMING in capfd.readouterr().err
    st = eng.run_nve(60, 1.0)
    assert st.tune_ms == 0.0 and TIMING not in capfd.readouterr().err
    pos, _, frc, e_md = eng.get_state()
    fresh = LoupEngine(sto_bundle)
    fresh.set_system(at.get_atomic_numbers(), at.get_masses())
    e, f, _ = fresh.evaluate(pos, at.cell.array)
    assert abs(e - e_md) / len(at) < 1e-6
    assert np.abs(f - frc).max() < 1e-4


def test_variants_timed_for_a_caller_that_changes_the_cell_at_every_call(sto_bundle, monkeypatch, capfd):
    """Every evaluation on a new cell rebuilds on the host (as LAMMPS's pair style under fix npt), where no MD step's
    rebuild times the variants: the 50th evaluation does, once, and the results stay a fresh engine's."""
    monkeypatch.setenv("LOUP_CONV_TUNE", "1")
    monkeypatch.setenv("LOUP_DEBUG_SPLINE", "1")
    at = _rattled(srtio3(3), 0.02, 12)
    eng = LoupEngine(sto_bundle)
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    capfd.readouterr()
    for k in range(60):
        s = 1.0 + 1e-4 * (k % 2)
        eng.evaluate(at.positions * s, at.cell.array * s)
        if k == 48:
            assert TIMING not in capfd.readouterr().err
    assert TIMING in capfd.readouterr().err
    s = 1.0 + 1e-4
    e, f, _ = eng.evaluate(at.positions * s, at.cell.array * s)
    assert TIMING not in capfd.readouterr().err
    fresh = LoupEngine(sto_bundle)
    fresh.set_system(at.get_atomic_numbers(), at.get_masses())
    e_ref, f_ref, _ = fresh.evaluate(at.positions * s, at.cell.array * s)
    assert abs(e - e_ref) / len(at) < 1e-6
    assert np.abs(f - f_ref).max() < 1e-4


def test_an_engine_destroyed_in_another_thread_leaves_a_run_alone(sto_bundle):
    """Python's garbage collector destroys an engine in whatever thread it runs in, e.g. one of the package's output
    writer threads in the middle of another engine's run. That loup_destroy's cudaFree used to invalidate the running
    engine's graph capture (CUDA's global capture mode): the run failed ("operation failed due to a previous error
    during capture") or the process crashed. Each run here captures its step graphs while the other engine goes."""
    small, big = srtio3(2), srtio3(4)
    for k, delay in enumerate((0.0, 0.005, 0.01, 0.02, 0.04, 0.06)):
        other = LoupEngine(sto_bundle)
        other.set_system(small.get_atomic_numbers(), small.get_masses())
        other.evaluate(small.positions, small.cell.array)
        holder = [other]
        del other

        def destroy(wait=delay, refs=holder):
            time.sleep(wait)
            refs.clear()                      # the last reference: loup_destroy runs in this thread

        eng = LoupEngine(sto_bundle)
        eng.set_system(big.get_atomic_numbers(), big.get_masses(), skin=0.5)
        eng.set_state(big.positions, maxwell_velocities(big, 300.0, k), big.cell.array)
        worker = threading.Thread(target=destroy)
        worker.start()
        st = eng.run_nve(60, 1.0)
        worker.join()
        assert not holder and st.dangerous_builds == 0 and 100.0 < st.final_temperature_k < 400.0, (k, delay)


def test_evaluate_after_md_matches_md_forces(sto_engine):
    at = _rattled(srtio3(3), 0.02, 8)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin=0.5)
    eng.set_state(at.positions, maxwell_velocities(at, 300.0, 9), at.cell.array)
    eng.run_langevin(50, 1.0, seed=3)
    pos, _, frc, e_md = eng.get_state()
    e_ev, f_ev, _ = eng.evaluate(pos, at.cell.array, compute_stress=True)
    assert abs(e_ev - e_md) / len(at) < 1e-6
    assert np.abs(f_ev - frc).max() < 1e-4
    # and MD continues from the evaluated positions with the kept velocities
    st = eng.run_nve(10, 1.0)
    assert np.isfinite(st.final_potential_energy_ev)


# ---------------------------------------------------------------------------------------------------------------
# Error paths: each must fail cleanly and leave the handle usable.


def _assert_still_usable(eng, at):
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    assert np.isfinite(e) and np.isfinite(f).all()


def test_unknown_species_rejected_and_previous_system_kept(sto_engine):
    at = srtio3(2)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    z = at.get_atomic_numbers().copy()
    z[0] = 11  # Na is not in the bundle
    with pytest.raises(RuntimeError, match=r"atomic number 11 \(atom 0\) is not in the bundle"):
        eng.set_system(z, at.get_masses())
    _assert_still_usable(eng, at)


def test_rejected_set_system_of_other_size_keeps_previous_system_usable(sto_engine):
    """A rejected set_system keeps the previous system, so later calls must still size their arrays for it."""
    at = srtio3(3)  # 135 atoms
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    small = srtio3(1)  # 5 atoms
    z = small.get_atomic_numbers().copy()
    z[0] = 11  # Na is not in the bundle
    with pytest.raises(RuntimeError, match="is not in the bundle, which was exported for 8, 22, 38"):
        eng.set_system(z, small.get_masses())
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    assert f.shape == (len(at), 3)
    assert np.isfinite(e) and np.isfinite(f).all()
    pos, vel, frc, _ = eng.get_state()
    assert pos.shape == vel.shape == frc.shape == (len(at), 3)


def test_system_beyond_the_free_memory_refused_and_handle_takes_one_again(sto_bundle, monkeypatch):
    """A system whose buffers do not fit the free device memory fails with out of memory, as on a native driver,
    instead of being allocated: under WSL 2 the allocation succeeds and pages out to system memory, and every step
    then runs at bus speed (src/model.hpp, device_malloc). LOUP_DEBUG_ALLOC_FREE caps the free memory the check
    sees. The engine takes a system again once the memory is there, with the forces of a fresh engine."""
    at = _rattled(srtio3(4), 0.02, 11)  # 320 atoms: the model's rows and the bin arrays are over 1 MiB each
    fresh = LoupEngine(sto_bundle)
    fresh.set_system(at.get_atomic_numbers(), at.get_masses())
    e_ref, f_ref, _ = fresh.evaluate(at.positions, at.cell.array)
    eng = LoupEngine(sto_bundle)
    monkeypatch.setenv("LOUP_DEBUG_ALLOC_FREE", "1")
    with pytest.raises(RuntimeError, match="out of memory"):
        eng.set_system(at.get_atomic_numbers(), at.get_masses())
    monkeypatch.delenv("LOUP_DEBUG_ALLOC_FREE")
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    e, f, _ = eng.evaluate(at.positions, at.cell.array)
    assert abs(e - e_ref) / len(at) < 1e-6
    assert np.abs(f - f_ref).max() < 1e-4


@pytest.mark.parametrize("bad", ["short_positions", "flat_cell", "short_masses", "short_velocities"])
def test_wrong_shaped_arrays_rejected_before_the_library_reads_them(sto_engine, bad):
    at = srtio3(2)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    with pytest.raises(ValueError, match="has shape"):
        if bad == "short_positions":
            eng.evaluate(at.positions[:-1], at.cell.array)
        elif bad == "flat_cell":
            eng.evaluate(at.positions, at.cell.array.diagonal())
        elif bad == "short_masses":
            eng.set_system(at.get_atomic_numbers(), at.get_masses()[:-1])
        else:
            eng.set_state(at.positions, np.zeros((len(at) - 1, 3)), at.cell.array)
    _assert_still_usable(eng, at)


@pytest.mark.parametrize("bad", ["zero", "nan", "negative"])
def test_bad_masses_rejected(sto_engine, bad):
    at = srtio3(2)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    m = at.get_masses().copy()
    m[3] = {"zero": 0.0, "nan": np.nan, "negative": -1.0}[bad]
    with pytest.raises(RuntimeError, match="atom 3 has mass .* amu; masses must be finite and positive"):
        eng.set_system(at.get_atomic_numbers(), m)
    _assert_still_usable(eng, at)


@pytest.mark.parametrize("bad", ["skin_nan", "skin_negative"])
def test_bad_skin_rejected(sto_engine, bad):
    at = srtio3(2)
    eng = sto_engine
    with pytest.raises(RuntimeError, match="skin must be finite and not negative"):
        eng.set_system(at.get_atomic_numbers(), at.get_masses(), skin={"skin_nan": np.nan, "skin_negative": -0.1}[bad])


@pytest.mark.parametrize("bad", ["singular_cell", "zero_cell", "nan_cell", "nan_position", "inf_position"])
def test_bad_geometry_rejected(sto_engine, bad):
    at = srtio3(2)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    pos, cell = at.positions.copy(), at.cell.array.copy()
    if bad == "singular_cell":
        cell[2] = cell[0] + cell[1]
    elif bad == "zero_cell":
        cell[:] = 0.0
    elif bad == "nan_cell":
        cell[1, 1] = np.nan
    elif bad == "nan_position":
        pos[5, 2] = np.nan
    else:
        pos[0, 0] = np.inf
    reason = {"singular_cell": "singular or zero cell", "zero_cell": "singular or zero cell",
              "nan_cell": "non-finite cell entry", "nan_position": r"non-finite position \(atom 5\)",
              "inf_position": r"non-finite position \(atom 0\)"}[bad]
    with pytest.raises(RuntimeError, match="loup_evaluate: " + reason):
        eng.evaluate(pos, cell)
    with pytest.raises(RuntimeError, match="loup_set_state: " + reason):
        eng.set_state(pos, None, cell)
    _assert_still_usable(eng, at)


def test_nan_velocity_rejected(sto_engine):
    at = srtio3(2)
    eng = sto_engine
    eng.set_system(at.get_atomic_numbers(), at.get_masses())
    v = np.zeros((len(at), 3))
    v[2, 1] = np.nan
    with pytest.raises(RuntimeError, match=r"non-finite velocity \(atom 2\)"):
        eng.set_state(at.positions, v, at.cell.array)


def test_md_without_system_fails(sto_engine):
    with pytest.raises(RuntimeError, match="no system is set"):
        sto_engine.run_nve(1, 1.0)


@pytest.mark.parametrize("frac", [0.0, 0.003, 0.5, 0.999])
def test_truncated_bundle_rejected(sto_bundle, tmp_path, frac):
    data = sto_bundle.read_bytes()
    bad = tmp_path / "truncated.loup"
    bad.write_bytes(data[: int(len(data) * frac)])
    with pytest.raises(RuntimeError, match="truncated .loup bundle"):
        LoupEngine(bad)


def test_bundle_with_trailing_bytes_rejected(sto_bundle, tmp_path):
    bad = tmp_path / "trailing.loup"
    bad.write_bytes(sto_bundle.read_bytes() + b"\0" * 16)
    with pytest.raises(RuntimeError, match="trailing bytes after the end marker"):
        LoupEngine(bad)


def test_missing_bundle_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="loup_create: Cannot open .loup file"):
        LoupEngine(tmp_path / "does_not_exist.loup")
