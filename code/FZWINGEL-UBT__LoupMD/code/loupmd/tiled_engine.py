"""The engine of a ``Simulation`` whose system does not fit the GPU whole (plan task S5-T12, PLAN.md D65).

:class:`TiledEngine` has the interface ``Simulation`` uses of ``LoupEngine`` and gets its forces from the tiled call,
which keeps its tile lists across steps until an atom has moved skin/2 (S5-T06).

The integrator runs on the device when the library has it (``loup_tiled_run``, PLAN.md O31): positions, velocities
and forces stay on the GPU between steps, and NVE, Langevin, CSVR, the Nose-Hoover chain and Berendsen NVT run with
the whole-system loop's kernels (the same noise streams). Without it, with a dispersion term, or with
``LOUP_TILED_HOST_MD=1``, the host loop runs: velocity Verlet (NVE) and ASE's Langevin step, with fixed atoms and the
centre of mass held at rest as the device loop does; its Langevin noise is its own random stream (seeded from the
run's seed and the step), so a host run does not repeat a device run's trajectory. A restart continues either
stream. The barostats (Berendsen, Langevin BAOAB, MTK) run on the device loop of a library that has them
(``loup_tiled_get_cell``, LAMMPS_TILED_PLAN.md LT6 (a)): the tile lists stay across the cell's changes. The host
loop keeps the cell fixed and refuses them.

A dispersion term (``set_dispersion``, PLAN.md S6-D09, D76) is computed for the whole system by the library's D3
term kept across calls (``loupmd._d3.Term``): it needs no neighbour list and holds about 200 bytes per atom, so it
fits where the model has to be tiled. Its energy, forces and stress are added to the tiled call's.
"""
from __future__ import annotations

import os
import struct
import time

import numpy as np

from . import _core
from .errors import BackendError, PlanRefused

_MAGIC = b"LOUPTILE"
_VERSION = 2                                 # 2: the integrator state block and its kind follow the cell
_HEAD = "<8sIqq"
_SUPPORTED = {_core.LOUP_NVE: "NVE", _core.LOUP_LANGEVIN: "Langevin"}
_DEVICE_KINDS = {_core.LOUP_NVE, _core.LOUP_LANGEVIN, _core.LOUP_CSVR, _core.LOUP_NHC, _core.LOUP_BERENDSEN_NVT}
_NPT_KINDS = {_core.LOUP_BERENDSEN_NPT, _core.LOUP_BAOAB_NPT, _core.LOUP_MTK_NPT}   # LT6 (a): the device loop only
_SLOTS = _core.TILED_STATE_SLOTS


class TiledEngine:
    """Engine interface over ``engine.evaluate_tiled``: ``engine`` is a ``LoupEngine`` with no system set."""

    def __init__(self, engine, receivers: int = 0, memory_fraction: float = 0.9, wavefront: bool = False):
        self._eng = engine
        self.receivers = int(receivers)          # 0 until the first call takes the plan's cap
        self.memory_fraction = float(memory_fraction)
        self.mode = _core.LOUP_EXEC_WAVEFRONT if wavefront else _core.LOUP_EXEC_TILED
        self.wavefront = False                   # whether the last call ran the wavefront schedule (S5-T08)
        self.tiles = 0
        self._n = 0
        if hasattr(engine, "info"):            # what callers ask with hasattr (the record's kernel path)
            self.info = engine.info
        self.dispersion = None
        self._d3 = None
        self._dev = False                        # the device's tiled MD state is the current one
        self._host = True                        # the host arrays are the current state
        self._v0 = None                          # V0 of a barostat's volume limits (set_reference_volume)

    # ------------------------------------------------------------------------------------------------- system
    def set_system(self, numbers, masses, skin=0.5):
        self._numbers = np.ascontiguousarray(numbers, dtype=np.int32)
        self._masses = np.asarray(masses, dtype=np.float64)
        self._n = len(self._numbers)
        self.skin = float(skin)
        self._fixed = None
        self._pos = self._vel = self._cell = None
        self._forces = self._energy = None
        self._md_steps = 0
        self._noise_step = 0                     # the Langevin stream's position: kept by restarts, as the device's
        self._rows = []
        self._step_disp = 0.0
        self._int_state = np.zeros(_SLOTS)
        self._int_kind = -1
        self._dev, self._host = False, True
        self._close_d3()
        self._eng.set_execution(self.mode, self.receivers, self.memory_fraction)

    def set_dispersion(self, record=None):
        """The D3 term of a resolved record added to every force call (``None``: removed)."""
        self._close_d3()
        self._pull()
        self.dispersion = record
        self._forces = self._energy = None
        self._dev = False

    def _close_d3(self):
        if self._d3 is not None:
            self._d3.close()
            self._d3 = None

    def set_fixed_atoms(self, fixed=None):
        self._pull()
        self._dev = False
        self._fixed = None if fixed is None else np.asarray(fixed, dtype=bool).copy()
        if self._fixed is not None and self._vel is not None:
            self._vel[self._fixed] = 0.0

    def set_reference_volume(self, volume):
        """V0 of a barostat's volume limits: passed to the device state now, or when it is sent."""
        self._v0 = float(volume)
        if self._dev:
            self._eng.set_reference_volume(self._v0)

    def _barostats(self) -> bool:
        return hasattr(self._eng, "has_tiled_barostats") and self._eng.has_tiled_barostats()

    def set_state(self, positions, velocities, cell):
        self._pos = np.array(positions, dtype=np.float64)
        self._vel = np.array(velocities, dtype=np.float64)
        self._cell = np.array(cell, dtype=np.float64)
        if self._fixed is not None:
            self._vel[self._fixed] = 0.0
        self._forces = self._energy = None
        self._md_steps = 0
        self._dev, self._host = False, True

    def get_cell(self):
        if not self._host and self._barostats():  # a barostat on the device moves the cell
            return self._eng.tiled_get_cell()
        return self._cell.copy()

    # ------------------------------------------------------------------------------------------------- device state
    def _device_md(self, kind=None) -> bool:
        """Whether this run goes to the device loop."""
        if os.environ.get("LOUP_TILED_HOST_MD") == "1" or self.dispersion is not None:
            return False
        if not (hasattr(self._eng, "has_tiled_md") and self._eng.has_tiled_md()):
            return False
        return kind is None or kind in _DEVICE_KINDS or (kind in _NPT_KINDS and self._barostats())

    def runs_barostats(self) -> bool:
        """Whether a barostat's run goes to the device loop (the host loop refuses it)."""
        return self._device_md(_core.LOUP_MTK_NPT)

    @property
    def integrator_on(self) -> str:
        """Where the run's integrator runs: ``"device"`` (``loup_tiled_run``) or ``"host"``."""
        return "device" if self._device_md() else "host"

    def _pull(self):
        """The device's state into the host arrays (when the device holds a newer one)."""
        if self._host:
            return
        pos, vel, frc, e, step, ist, kind = self._eng.tiled_get_state()
        self._pos, self._vel, self._forces, self._energy = pos, vel, frc, e
        if self._barostats():
            self._cell = self._eng.tiled_get_cell()
        self._stress = None
        self._noise_step, self._int_state, self._int_kind = step, ist, kind
        self._host = True

    def _push(self):
        """The host state onto the device (when the device's is not current)."""
        if self._dev:
            return
        self._eng.tiled_set_state(self._numbers, self._masses, self._pos, self._vel, self._cell, fixed=self._fixed,
                                  receivers=self.receivers, skin=self.skin, noise_step=self._noise_step,
                                  int_state=self._int_state if self._int_kind >= 0 else None,
                                  int_state_kind=self._int_kind)
        if self._v0 is not None and self._barostats():
            self._eng.set_reference_volume(self._v0)
        self._dev = True

    # ------------------------------------------------------------------------------------------------- forces
    def _force_call(self, stress=True):
        e, f, s, tiles = self._eng.evaluate_tiled(self._numbers, self._pos, self._cell, self.receivers,
                                                  skin=self.skin, compute_stress=stress)
        done = self._eng.last_execution()
        if not self.receivers:
            self.receivers = int(done.receivers)
        self.wavefront = done.mode == _core.LOUP_EXEC_WAVEFRONT
        self.tiles = int(tiles)
        if not np.isfinite(e):
            raise BackendError(f"loup_run: non-finite energy ({e}) in the tiled call", call="loup_run")
        if self.dispersion is not None:
            from . import _d3

            if self._d3 is None:
                self._d3 = _d3.Term(self.dispersion, self._numbers, self._cell)
            de, df, ds = self._d3.compute(self._pos, self._cell, stress=s is not None)
            e, f = e + de, f + df
            if s is not None:
                s = s + ds
        self._energy, self._forces, self._stress = float(e), f, s
        return self._energy, f, s

    def evaluate(self, positions, cell, compute_stress=True):
        self._pull()
        self._pos = np.array(positions, dtype=np.float64)
        self._cell = np.array(cell, dtype=np.float64)
        self._dev = False
        e, f, s = self._force_call(stress=bool(compute_stress))
        return e, f.copy(), (s.copy() if compute_stress else None)

    def last_execution(self):
        return self._eng.last_execution()

    # ------------------------------------------------------------------------------------------------- dynamics
    def _dof(self, fix_com):
        free = self._n - (int(self._fixed.sum()) if self._fixed is not None else 0)
        return 3 * free - (3 if fix_com else 0)

    def run(self, n_steps, it):
        from ase import units

        if n_steps <= 0:
            raise BackendError(f"loup_run: n_steps must be positive, got {n_steps}", call="loup_run")
        if it.kind not in _DEVICE_KINDS | _NPT_KINDS:
            raise PlanRefused(f"integrator kind {it.kind} in tiled mode", why="the tiled mode has no such integrator",
                              next_step="Use NVE, an NVT or an NPT integrator of loupmd.integrators.")
        if self._device_md(it.kind):
            return self._run_device(n_steps, it)
        if it.kind in _NPT_KINDS:
            raise PlanRefused(f"a barostat (integrator kind {it.kind}) in tiled mode on the host loop",
                              why="the host loop (with a dispersion term, LOUP_TILED_HOST_MD=1, or a library without "
                                  "the tiled barostats) keeps the cell fixed",
                              next_step="Run without the dispersion term or LOUP_TILED_HOST_MD, or a cell that fits "
                                        "the GPU whole.")
        if it.kind not in _SUPPORTED:
            raise PlanRefused(f"integrator kind {it.kind} in tiled mode on the host loop",
                              why="the host loop (with a dispersion term, LOUP_TILED_HOST_MD=1, or a library without "
                                  "loup_tiled_run) integrates NVE and Langevin only",
                              next_step="Use NVE or Langevin, or a cell that fits the GPU whole.")
        self._pull()
        self._dev = False
        if self._forces is None:
            self._force_call(stress=False)
        dt = it.dt_fs * units.fs
        m = self._masses[:, None]
        inv_m = 1.0 / m
        if self._fixed is not None:
            inv_m = np.where(self._fixed[:, None], 0.0, inv_m)
        fix_com = bool(it.fix_com)
        total_mass = float(self._masses.sum())
        dof = self._dof(fix_com)
        v, x = self._vel, self._pos
        if fix_com and it.kind == _core.LOUP_NVE:
            v -= (self._masses[:, None] * v).sum(axis=0) / total_mass
        # SPDX-SnippetBegin
        # SPDX-License-Identifier: LGPL-2.1-or-later
        # Provenance: the Langevin and velocity-Verlet steps, up to the end marker, follow ASE 3.27's
        # ase/md/langevin.py and ase/md/verlet.py (LGPL-2.1-or-later, (c) the ASE developers,
        # https://gitlab.com/ase/ase); see NOTICE.md.
        langevin = it.kind == _core.LOUP_LANGEVIN
        if langevin:
            fr = it.friction_per_fs / units.fs
            c1 = dt / 2.0 - dt * dt * fr / 8.0
            c2 = dt * fr / 2.0 - dt * dt * fr * fr / 8.0
        largest = 0.0
        t0 = time.perf_counter()
        for i in range(1, n_steps + 1):
            f = self._forces
            if langevin:
                target = max(it.temp_k + i * it.temp_rate_k_per_step, 0.0)
                sigma = np.sqrt(2.0 * units.kB * target * fr / m)
                c3 = np.sqrt(dt) * sigma / 2.0 - dt ** 1.5 * fr * sigma / 8.0
                c5 = dt ** 1.5 * sigma / (2.0 * np.sqrt(3.0))
                c4 = fr / 2.0 * c5
                rng = np.random.default_rng([int(it.seed), self._noise_step])
                xi, eta = rng.standard_normal((self._n, 3)), rng.standard_normal((self._n, 3))
                rnd_pos = c5 * eta
                rnd_vel = c3 * xi - c4 * eta
                if self._fixed is not None:
                    rnd_pos[self._fixed] = 0.0
                    rnd_vel[self._fixed] = 0.0
                if fix_com:
                    rnd_pos -= (m * rnd_pos).sum(axis=0) / total_mass
                    rnd_vel -= (m * rnd_vel).sum(axis=0) / total_mass
                v += c1 * f * inv_m - c2 * v + rnd_vel
                step = dt * v + rnd_pos
                if self._fixed is not None:
                    step[self._fixed] = 0.0
                    v[self._fixed] = 0.0
                x += step
                e, f, _ = self._force_call(stress=False)
                v += c1 * f * inv_m - c2 * v + rnd_vel
                if fix_com:
                    v -= (m * v).sum(axis=0) / total_mass
                self._noise_step += 1
            else:
                v += 0.5 * dt * f * inv_m
                step = dt * v
                x += step
                e, f, _ = self._force_call(stress=False)
                v += 0.5 * dt * f * inv_m
            # SPDX-SnippetEnd
            largest = max(largest, float(np.sqrt((step * step).sum(axis=1).max())))
            self._md_steps += 1
            if it.thermo_every and self._md_steps % it.thermo_every == 0:
                e_kin = 0.5 * float((m * v * v).sum())
                self._rows.append((self._md_steps, e, e_kin, 2.0 * e_kin / (dof * units.kB) if dof > 0 else 0.0,
                                   0.0, abs(float(np.linalg.det(self._cell))), e + e_kin))
        wall = (time.perf_counter() - t0) * 1e3 / n_steps
        self._step_disp = largest
        e_kin = 0.5 * float((m * v * v).sum())
        stats = _core.LoupMDStats()
        stats.step_ms = wall
        stats.rebuilds = 0
        stats.final_potential_energy_ev = self._energy
        stats.final_kinetic_energy_ev = e_kin
        stats.final_temperature_k = 2.0 * e_kin / (dof * units.kB) if dof > 0 else 0.0
        stats.pipelined_steps = 0
        stats.dangerous_builds = 0
        return stats

    def _run_device(self, n_steps, it):
        if it.fix_com and self._fixed is not None and self._fixed.any():
            raise PlanRefused("fix_com with fixed atoms in tiled mode", why="the tiled device loop refuses both",
                              next_step="Drop fix_com: fixed atoms already hold the system in place.")
        self._push()
        every = int(it.thermo_every)
        stats, rows, step = self._eng.tiled_run(n_steps, it, max_rows=n_steps // every if every > 0 else 0)
        self._host = False
        done = self._eng.last_execution()
        if not self.receivers:
            self.receivers = int(done.receivers)
        self.wavefront = done.mode == _core.LOUP_EXEC_WAVEFRONT
        self.tiles = int(done.tiles)
        self._step_disp = step
        self._energy = stats.final_potential_energy_ev
        for r in rows:                           # the device counts as this engine does (both restart together)
            self._rows.append((int(r["step"]), float(r["e_pot"]), float(r["e_kin"]), float(r["temp_k"]),
                               float(r["pressure_gpa"]), float(r["volume_a3"]), float(r["conserved"])))
        self._md_steps += n_steps
        return stats

    def step_displacement(self):
        return self._step_disp

    def thermo_pending(self):
        return len(self._rows)

    def read_thermo(self, max_rows=None):
        rows, self._rows = self._rows, []
        return np.array(rows, dtype=_core.THERMO_DTYPE)

    def get_state(self):
        self._pull()
        if self._forces is None:
            self._force_call()
        return self._pos.copy(), self._vel.copy(), self._forces.copy(), self._energy

    # ------------------------------------------------------------------------------------------------- restarts
    def export_state(self) -> bytes:
        self._pull()
        head = struct.pack(_HEAD, _MAGIC, _VERSION, self._n, self._noise_step)
        ist = np.ascontiguousarray(self._int_state, dtype=np.float64)
        return (head + self._pos.tobytes() + self._vel.tobytes() + self._cell.tobytes() + ist.tobytes()
                + struct.pack("<i", int(self._int_kind)))

    def import_state(self, blob):
        blob = bytes(blob)
        size = struct.calcsize(_HEAD)
        if len(blob) < size:
            raise BackendError("loup_import_state: the state block is too short for the tiled mode",
                               call="loup_import_state")
        magic, version, n, noise = struct.unpack(_HEAD, blob[:size])
        if magic != _MAGIC or version not in (1, _VERSION):
            raise BackendError("loup_import_state: not a tiled-mode state block (written by the whole-system "
                               "engine, or another version)", call="loup_import_state")
        tail = 8 * _SLOTS + 4 if version == 2 else 0
        if n != self._n or len(blob) != size + 8 * (6 * n + 9) + tail:
            raise BackendError(f"loup_import_state: the state block holds {n} atoms, the system {self._n}",
                               call="loup_import_state")
        a = np.frombuffer(blob[size:size + 8 * (6 * n + 9)], dtype=np.float64)
        pos, vel, cell = a[:3 * n].reshape(n, 3), a[3 * n:6 * n].reshape(n, 3), a[6 * n:].reshape(3, 3)
        if version == 2:
            ist = np.frombuffer(blob[size + 8 * (6 * n + 9):-4], dtype=np.float64).copy()
            kind = struct.unpack("<i", blob[-4:])[0]
        else:
            ist, kind = np.zeros(_SLOTS), -1
        # The engine's own state again (a Simulation restarts the step count this way on a thermo step): the forces
        # stay, and the device keeps its state, so no tiled call is repeated.
        self._pull()
        same = (self._forces is not None and self._pos is not None and np.array_equal(pos, self._pos)
                and np.array_equal(cell, self._cell))
        unchanged = (same and np.array_equal(vel, self._vel) and int(noise) == self._noise_step
                     and kind == self._int_kind and np.array_equal(ist, self._int_state))
        self._pos, self._cell, self._vel = pos.copy(), cell.copy(), vel.copy()
        self._noise_step, self._int_state, self._int_kind = int(noise), ist, int(kind)
        if not same:
            self._forces = self._energy = None
        if not unchanged:
            self._dev = False
        elif self._dev:                          # the device keeps its state; its step count starts anew too
            self._eng.tiled_set_state(self._numbers, self._masses, None, None, self._cell)
        self._md_steps = 0
        self._rows = []
