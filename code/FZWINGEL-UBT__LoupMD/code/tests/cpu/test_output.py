"""Chunked output (plan task S3-T03): thermo CSV and ASE trajectory chunks, the readers, resume checks and the
background writer. Needs neither a GPU nor the library."""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest
from ase.build import bulk

from loupmd import output
from loupmd.errors import InputError, NonFiniteError, RestartMismatch


@pytest.fixture
def atoms():
    return bulk("NaCl", "rocksalt", a=5.64, cubic=True)


def _row(step, temperature=300.0):
    return (step, step * 1e-3, "constant", 300.0, temperature, -3.5, 0.04, -3.46)


def _frame(atoms, shift):
    rng = np.random.default_rng(shift)
    return dict(positions=atoms.positions + 0.01 * shift, velocities=rng.normal(size=atoms.positions.shape) * 0.01,
                forces=rng.normal(size=atoms.positions.shape), energy=-27.0 - shift)


def test_rows_and_frames_are_read_back(tmp_path, atoms):
    with output.ChunkedOutput(tmp_path, atoms) as out:
        for step in (0, 20, 40):
            out.write_row(_row(step))
            out.write_frame(**_frame(atoms, step))
        assert (out.chunk, out.rows, out.frames) == (0, 3, 3)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["thermo.0.csv", "trajectory.0.traj"]
    header, rows = output.read_thermo(tmp_path)
    assert header == list(output.THERMO_HEADER) == ["step", "time_ps", "phase", "target_K", "temperature_K",
                                                    "potential_eV_atom", "kinetic_eV_atom", "total_eV_atom"]
    assert [row[0] for row in rows] == ["0", "20", "40"] and rows[1][2] == "constant" and float(rows[1][4]) == 300.0
    frames = output.read_frames(tmp_path)
    assert len(frames) == 3
    for step, frame in zip((0, 20, 40), frames):
        want = _frame(atoms, step)
        assert np.array_equal(frame.positions, want["positions"])
        assert np.allclose(frame.get_momenta(), atoms.get_masses()[:, None] * want["velocities"])
        assert frame.get_potential_energy() == want["energy"] and np.array_equal(frame.get_forces(), want["forces"])
        assert np.array_equal(frame.numbers, atoms.numbers) and np.array_equal(frame.cell.array, atoms.cell.array)
        assert all(frame.pbc)


def test_a_restart_point_ends_the_chunk_and_the_readers_join_the_chunks(tmp_path, atoms):
    out = output.ChunkedOutput(tmp_path, atoms)
    out.write_row(_row(0))
    out.write_frame(**_frame(atoms, 0))
    assert out.restart_point() == {"output_chunk": 0, "output_rows": 1, "output_frames": 1}
    assert out.restart_point() == {"output_chunk": 1, "output_rows": 1, "output_frames": 1}     # an empty chunk
    out.write_row(_row(20))
    out.write_row(_row(40))
    out.write_frame(**_frame(atoms, 40))
    out.close()
    assert output.chunk_indices(tmp_path) == [0, 1, 2]
    assert (tmp_path / "thermo.1.csv").read_text().strip() == ",".join(output.THERMO_HEADER)   # complete on its own
    header, rows = output.read_thermo(tmp_path)
    assert [row[0] for row in rows] == ["0", "20", "40"] and len(output.read_frames(tmp_path)) == 2


def test_the_readers_work_while_the_run_is_writing(tmp_path, atoms):
    out = output.ChunkedOutput(tmp_path, atoms)
    out.write_row(_row(0))
    assert output.read_frames(tmp_path) == [] and len(output.read_thermo(tmp_path)[1]) == 1    # no frame yet
    out.write_frame(**_frame(atoms, 0))
    assert len(output.read_frames(tmp_path)) == 1
    out.close()


def test_a_cell_and_stress_go_into_the_frame(tmp_path, atoms):
    cell = atoms.cell.array * 1.01
    stress = np.array([[1.0, 0.4, 0.5], [0.4, 2.0, 0.6], [0.5, 0.6, 3.0]]) * 1e-3
    with output.ChunkedOutput(tmp_path, atoms) as out:
        out.write_frame(cell=cell, stress=stress, **_frame(atoms, 1))
    frame, = output.read_frames(tmp_path)
    assert np.allclose(frame.cell.array, cell) and np.allclose(frame.get_stress(voigt=False), stress)
    assert np.array_equal(atoms.cell.array, bulk("NaCl", "rocksalt", a=5.64, cubic=True).cell.array)   # not the caller's


def test_a_new_run_refuses_a_directory_that_holds_chunks(tmp_path, atoms):
    output.ChunkedOutput(tmp_path, atoms).close()
    with pytest.raises(InputError) as caught:
        output.ChunkedOutput(tmp_path, atoms)
    assert "already holds output chunks (thermo.0.csv, trajectory.0.traj)" in str(caught.value)
    assert "Next: Resume the run, or use a new directory." in str(caught.value)


def test_a_non_finite_row_is_refused_before_it_is_written(tmp_path, atoms):
    with output.ChunkedOutput(tmp_path, atoms) as out:
        out.write_row(_row(0))
        with pytest.raises(NonFiniteError, match="step 20"):
            out.write_row(_row(20, temperature=float("nan")))
        assert out.rows == 1
    assert len(output.read_thermo(tmp_path)[1]) == 1


def _three_chunks(directory, atoms):
    out = output.ChunkedOutput(directory, atoms)
    out.write_row(_row(0))
    out.write_frame(**_frame(atoms, 0))
    first = out.restart_point()
    out.write_row(_row(20))
    out.write_frame(**_frame(atoms, 20))
    second = out.restart_point()
    out.write_row(_row(40))                       # written after the last restart point: lost on resume
    out.close()
    return first, second


def test_resume_deletes_what_came_after_the_restart_and_goes_on_in_the_next_chunk(tmp_path, atoms):
    first, second = _three_chunks(tmp_path, atoms)
    assert second == {"output_chunk": 1, "output_rows": 2, "output_frames": 2}
    out = output.ChunkedOutput(tmp_path, atoms, resume_from=first)
    assert (out.chunk, out.rows, out.frames) == (1, 1, 1) and output.chunk_indices(tmp_path) == [0, 1]
    out.write_row(_row(20))
    out.close()
    assert [row[0] for row in output.read_thermo(tmp_path)[1]] == ["0", "20"]
    assert len(output.read_frames(tmp_path)) == 1


def test_resume_refuses_outputs_that_do_not_fit_the_restart(tmp_path, atoms):
    first, second = _three_chunks(tmp_path, atoms)
    with pytest.raises(RestartMismatch, match="has no output chunk indices"):
        output.ChunkedOutput(tmp_path, atoms, resume_from={"output_chunk": 1})
    with pytest.raises(RestartMismatch, match="hold 2 rows and 2 frames; the restart expects 5 rows and 2 frames"):
        output.ChunkedOutput(tmp_path, atoms, resume_from=dict(second, output_rows=5))
    (tmp_path / "trajectory.0.traj").unlink()
    with pytest.raises(RestartMismatch, match="output chunk trajectory.0.traj is missing"):
        output.ChunkedOutput(tmp_path, atoms, resume_from=second)
    assert output.chunk_indices(tmp_path) == [0, 1, 2]                 # nothing was deleted by a refused resume


# ------------------------------------------------------------------------------------- the background writer

def test_the_background_writer_keeps_the_order_and_drain_waits(tmp_path, atoms):
    written, gate = [], threading.Event()

    def slow(value):
        gate.wait(5.0)
        written.append(value)

    writer = output.AsyncWriter()
    for value in range(5):
        writer.submit(slow if value == 0 else written.append, value)
    assert written == [] and len(writer) == 5                      # the caller is not held up by the first job
    gate.set()
    writer.drain()
    assert written == [0, 1, 2, 3, 4] and len(writer) == 0
    writer.close()
    with pytest.raises(InputError, match="closed"):
        writer.submit(written.append, 9)


def test_an_error_of_a_write_reaches_the_caller_and_stops_the_later_writes():
    written = []

    def fail(value):
        raise NonFiniteError(f"non-finite energy at step {value}")

    writer = output.AsyncWriter()
    writer.submit(written.append, 1)
    writer.submit(fail, 2)
    writer.submit(written.append, 3)
    with pytest.raises(NonFiniteError, match="step 2"):
        writer.drain()
    assert written == [1]
    with pytest.raises(NonFiniteError, match="step 2"):                # and every later call
        writer.submit(written.append, 4)
    writer.close(raise_errors=False)


def test_chunked_output_through_the_background_writer(tmp_path, atoms):
    out = output.ChunkedOutput(tmp_path, atoms)
    writer = output.AsyncWriter()
    for step in range(0, 200, 20):
        writer.submit(out.write_row, _row(step))
        writer.submit(lambda step=step: out.write_frame(**_frame(atoms, step)))
    writer.drain()
    indices = out.restart_point()
    writer.close()
    out.close()
    assert indices == {"output_chunk": 0, "output_rows": 10, "output_frames": 10}
    assert [int(row[0]) for row in output.read_thermo(tmp_path)[1]] == list(range(0, 200, 20))
    started = time.perf_counter()
    assert len(output.read_frames(tmp_path)) == 10 and time.perf_counter() - started < 5.0
