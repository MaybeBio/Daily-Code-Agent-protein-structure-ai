"""Output of a run: thermo rows and trajectory frames in chunks, their readers, and the background writer.

File names and formats are FastMACE's. A run writes ``thermo.<n>.csv`` and ``trajectory.<n>.traj`` (an ASE
trajectory) for n = 0, 1, ...; every restart point is a chunk boundary:

- ``restart_point()`` closes the current chunks, fsyncs them and their directory, opens the next pair and returns
  the indices the restart file stores: ``output_chunk`` (the last closed chunk) and ``output_rows`` and
  ``output_frames`` (rows and frames in chunks 0 to ``output_chunk``).
- Resume (``resume_from=`` those indices) checks the chunks up to ``output_chunk`` (present, with the stored
  numbers of rows and frames) before it touches anything, else ``RestartMismatch``; then it deletes the later
  chunks and opens chunk ``output_chunk + 1``. Nothing is ever rewritten.

Every chunk is complete on its own: each thermo chunk starts with the header, and a chunk without rows or frames
still has both files. ``read_thermo`` and ``read_frames`` join the chunks; ``ase.io.read(path, index=":")`` reads
one. This module imports ASE only where a frame is written or read.
"""
from __future__ import annotations

import csv
import errno
import math
import os
import queue
import re
import threading
from pathlib import Path

from .config import Output  # noqa: F401  (the record: lm.Output)
from .errors import InputError, NonFiniteError, RestartMismatch

THERMO_PATTERN = "thermo.{}.csv"
TRAJECTORY_PATTERN = "trajectory.{}.traj"
THERMO_HEADER = ("step", "time_ps", "phase", "target_K", "temperature_K", "potential_eV_atom", "kinetic_eV_atom",
                 "total_eV_atom")
NPT_COLUMNS = ("volume_A3_atom", "pressure_GPa")    # after THERMO_HEADER in a variable-cell run (as FastMACE)
CONSTANT_PHASE = "constant"          # the phase column of a run without a schedule
OUTPUT_KEYS = ("output_chunk", "output_rows", "output_frames")
_CHUNK = re.compile(r"^(?:thermo\.(\d+)\.csv|trajectory\.(\d+)\.traj)$")
# A directory fsync that the file system does not support (some FUSE and network mounts).
_UNSUPPORTED = frozenset({errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP})


# ------------------------------------------------------------------------------------------ durable writes

def fsync_file(path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_directory(path) -> None:
    """So that the names created, renamed or deleted in a directory are on disk; skipped where the file system
    does not support it."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in _UNSUPPORTED:
            raise
    finally:
        os.close(fd)


def write_atomically(path, write) -> Path:
    """``write(handle)`` fills a temporary binary file next to ``path``, which is fsynced and renamed over
    ``path``; then the directory is fsynced. If anything fails before the rename, ``path`` is left as it was."""
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "wb") as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    fsync_directory(path.parent)
    return path


# ------------------------------------------------------------------------------------------------- readers

def chunk_paths(directory, index):
    """The thermo and trajectory files of chunk ``index``."""
    directory = Path(directory)
    return directory / THERMO_PATTERN.format(index), directory / TRAJECTORY_PATTERN.format(index)


def chunk_files(directory) -> dict:
    """Every chunk file in ``directory``, by chunk index (sorted)."""
    found = {}
    for path in Path(directory).iterdir():
        match = _CHUNK.match(path.name)
        if match:
            found.setdefault(int(match.group(1) or match.group(2)), []).append(path)
    return {index: sorted(found[index]) for index in sorted(found)}


def chunk_indices(directory) -> list:
    return list(chunk_files(directory))


def _thermo_rows(path):
    with Path(path).open(newline="") as handle:
        rows = list(csv.reader(handle))
    return (rows[0], rows[1:]) if rows else ([], [])


def _frame_count(path) -> int:
    from ase.io.trajectory import Trajectory

    if Path(path).stat().st_size == 0:          # the chunk a run is writing, before its first frame
        return 0
    with Trajectory(str(path)) as trajectory:
        return len(trajectory)


def read_thermo(directory):
    """The header and every thermo row over all chunks, in order (rows as lists of strings)."""
    header, rows = [], []
    for index in chunk_indices(directory):
        path = chunk_paths(directory, index)[0]
        if path.is_file():
            chunk_header, chunk_rows = _thermo_rows(path)
            header = header or chunk_header
            rows += chunk_rows
    return header, rows


def read_frames(directory) -> list:
    """Every trajectory frame over all chunks, in order, as ``Atoms`` with momenta, energy and forces."""
    from ase.io import read

    frames = []
    for index in chunk_indices(directory):
        path = chunk_paths(directory, index)[1]
        if path.is_file() and _frame_count(path):
            frames += read(path, index=":")
    return frames


# ------------------------------------------------------------------------------------------------- writer

def _check_resume(directory, indices):
    """The chunk files to delete on resume; ``RestartMismatch`` if the outputs do not fit the restart."""
    if not indices or any(key not in indices for key in OUTPUT_KEYS):
        raise RestartMismatch(f"the restart in {directory} has no output chunk indices",
                              why="without them the outputs after its step cannot be found",
                              next_step="Start a new run in a new directory.")
    last, rows, frames = (int(indices[key]) for key in OUTPUT_KEYS)
    counted_rows = counted_frames = 0
    for index in range(last + 1):
        thermo, trajectory = chunk_paths(directory, index)
        for path in (thermo, trajectory):
            if not path.is_file():
                raise RestartMismatch(
                    f"output chunk {path.name} is missing in {directory}",
                    why=f"the restart's outputs end with chunk {last}; without every chunk up to it the trajectory "
                        "and thermo files would have a gap",
                    next_step="Restore the missing chunk, or start a new run in a new directory.")
        counted_rows += len(_thermo_rows(thermo)[1])
        counted_frames += _frame_count(trajectory)
    if (counted_rows, counted_frames) != (rows, frames):
        raise RestartMismatch(
            f"output chunks 0-{last} in {directory} hold {counted_rows} rows and {counted_frames} frames; the "
            f"restart expects {rows} rows and {frames} frames",
            why="the chunks up to the restart point were changed after the restart was written",
            next_step="Restore the chunks, or start a new run in a new directory.")
    later = [path for index, paths in chunk_files(directory).items() if index > last for path in paths]
    blocked = [path for path in later if not os.access(path, os.W_OK)]
    if not os.access(directory, os.W_OK | os.X_OK):
        blocked = [directory]
    if blocked:
        raise RestartMismatch(
            f"cannot delete the output chunks after the restart in {directory}",
            why=f"the outputs are ahead of the restart (chunk {last}) and {', '.join(map(str, blocked))} is "
                "read-only, so they cannot be removed; nothing was changed",
            next_step="Make the run directory writable, or copy it and resume the copy.")
    return later


class ChunkedOutput:
    """The thermo rows and trajectory frames of one run, in chunks that end at restart points.

    ``atoms`` gives the frames their atomic numbers, masses, cell and boundary conditions (a copy is kept).
    ``resume_from`` is what ``restart_point`` returned for the restart a resumed run starts from; ``None`` starts a
    new run, which refuses a directory that already holds chunks.
    """

    def __init__(self, directory, atoms, header=THERMO_HEADER, *, resume_from=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.atoms = atoms.copy()
        self.header = list(header)
        self._masses = self.atoms.get_masses()[:, None]
        self._thermo = self._csv = self._trajectory = None
        if resume_from is None:
            existing = chunk_files(self.directory)
            if existing:
                names = ", ".join(path.name for paths in existing.values() for path in paths)
                raise InputError(f"{self.directory} already holds output chunks ({names})",
                                 next_step="Resume the run, or use a new directory.")
            self.chunk, self.rows, self.frames = 0, 0, 0
        else:
            for path in _check_resume(self.directory, resume_from):
                path.unlink()
            self.chunk = int(resume_from["output_chunk"]) + 1
            self.rows, self.frames = int(resume_from["output_rows"]), int(resume_from["output_frames"])
        self._open()

    def _open(self):
        from ase.io.trajectory import Trajectory

        thermo, trajectory = chunk_paths(self.directory, self.chunk)
        self._trajectory = Trajectory(str(trajectory), "w", self.atoms)
        self._thermo = thermo.open("w", newline="")
        self._csv = csv.writer(self._thermo)
        self._csv.writerow(self.header)
        self._thermo.flush()                     # a chunk opened at a restart point is complete on disk

    def write_row(self, row):
        """One thermo row (a sequence in the header's order). A non-finite number raises ``NonFiniteError``
        before anything is written."""
        for name, value in zip(self.header, row):
            if isinstance(value, float) and not math.isfinite(value) and name != "target_K":
                raise NonFiniteError(f"non-finite {name} ({value}) at step {row[0]}",
                                     why="the run stops at a non-finite value; it is never patched over")
        self._csv.writerow(list(row))
        self._thermo.flush()
        self.rows += 1

    def write_frame(self, positions, velocities, forces, energy, cell=None, stress=None):
        """One trajectory frame: positions in A, velocities in ASE units (as ``LoupEngine.get_state`` gives
        them), forces in eV/A, the potential energy in eV; ``cell`` and ``stress`` (3x3) for variable-cell runs."""
        from ase.calculators.singlepoint import SinglePointCalculator

        atoms, extra = self.atoms, {}
        if cell is not None:
            atoms.set_cell(cell)
        if stress is not None:
            from ase.stress import full_3x3_to_voigt_6_stress

            extra["stress"] = full_3x3_to_voigt_6_stress(stress)
        atoms.set_positions(positions)
        atoms.set_momenta(self._masses * velocities)
        atoms.calc = SinglePointCalculator(atoms, energy=float(energy), forces=forces, **extra)
        self._trajectory.write(atoms)
        self.frames += 1

    def set_composition(self, numbers, masses):
        """The atoms' elements and masses from the next frame on (``Simulation.update``); the trajectory writes
        them with that frame."""
        import numpy as np

        self.atoms.numbers = np.asarray(numbers)
        self.atoms.set_masses(np.asarray(masses, dtype=float))
        self._masses = self.atoms.get_masses()[:, None]

    def restart_point(self) -> dict:
        """Close the current chunk durably and open the next; returns the indices for the restart file. Call it
        after the background writer was drained."""
        self._close_durably()
        indices = dict(output_chunk=self.chunk, output_rows=self.rows, output_frames=self.frames)
        self.chunk += 1
        self._open()
        return indices

    def flush(self):
        self._thermo.flush()

    def close(self):
        if self._thermo is not None:
            self._close_durably()
            self._thermo = self._csv = self._trajectory = None

    def _close_durably(self):
        self._trajectory.close()
        self._thermo.close()
        for path in chunk_paths(self.directory, self.chunk):
            fsync_file(path)
        fsync_directory(self.directory)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------------------------------------- the background writer

class AsyncWriter:
    """Runs write jobs on one background thread, in the order they were submitted, so the engine's next chunk of
    steps runs while the last one's rows and frames go to disk.

    The first job that raises stops the writer: its error is raised to the caller by the next ``submit``,
    ``drain`` or ``close``, and the jobs after it are not run. ``drain`` returns when everything submitted is
    written; call it before a restart point and at the end of a run.
    """

    def __init__(self):
        self._jobs = queue.Queue()
        self._error = None
        self._closed = False
        self._thread = threading.Thread(target=self._work, name="loupmd-output", daemon=True)
        self._thread.start()

    def _work(self):
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                if self._error is None:
                    function, args = job
                    function(*args)
            except BaseException as error:  # noqa: BLE001  (handed to the caller's thread)
                self._error = error
            finally:
                self._jobs.task_done()

    def _raise(self):
        if self._error is not None:
            raise self._error

    def submit(self, function, *args):
        self._raise()
        if self._closed:
            raise InputError("the output writer is closed")
        self._jobs.put((function, args))

    def drain(self):
        self._jobs.join()
        self._raise()

    def close(self, raise_errors=True):
        if not self._closed:
            self._closed = True
            self._jobs.put(None)
            self._thread.join()
        if raise_errors:
            self._raise()

    def __len__(self):
        return self._jobs.unfinished_tasks
