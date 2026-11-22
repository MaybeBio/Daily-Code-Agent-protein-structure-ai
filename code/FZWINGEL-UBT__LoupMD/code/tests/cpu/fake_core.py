"""The fake engine of the CPU tests: what the package uses of ``loupmd._core.LoupEngine``, on a harmonic potential.

Every atom sits on a spring to its lattice site, integrated with velocity Verlet in numpy, with the engine's
thermo buffer, state block and step counters. Deterministic, so runs can be compared exactly; needs neither a
GPU nor the library. ``loupmd.load(..., engine_factory=SpringEngine)`` puts it in the real engine's place.
"""
from __future__ import annotations

import pickle

import numpy as np
from ase import units

from loupmd import _core
from loupmd.errors import BackendError

K = 2.0          # eV/A^2: every atom on a spring to its lattice site


class SpringEngine:
    """NVE (and "Langevin" without noise or friction) on springs. Mirrors what Simulation uses of LoupEngine."""

    made = []
    poison_at = None      # an md step whose energy is reported as NaN
    step_disp = 0.01      # A: what step_displacement() reports

    def __init__(self, bundle, device_id=0):
        self.bundle, self.device_id = bundle, device_id
        self.log, self.rows, self.md_steps, self.forces_current, self.targets = [], [], 0, False, []
        self.total_steps = 0                       # survives set_state and import_state: for the tests only
        SpringEngine.made.append(self)

    # --- system and state
    def set_system(self, numbers, masses, skin=0.5):
        self.numbers, self.masses, self.n = np.array(numbers), np.array(masses, dtype=float), len(numbers)
        self.skins = getattr(self, "skins", []) + [skin]       # every set_system of this handle

    def step_displacement(self):
        return SpringEngine.step_disp

    def set_state(self, positions, velocities, cell):
        self.sites = getattr(self, "sites", None)
        self.pos, self.vel, self.cell = np.array(positions, dtype=float), np.array(velocities, dtype=float), np.array(cell)
        if self.sites is None:
            self.sites = self.pos.copy()
        self.md_steps, self.rows, self.forces_current = 0, [], False
        self.log.append("set_state")

    def set_dispersion(self, record=None):
        """Records the dispersion term the run installs (the springs have none)."""
        self.dispersion = record
        self.log.append(("dispersion", None if record is None else record.damping))

    def set_fixed_atoms(self, fixed=None):
        self.fixed = None if fixed is None else np.asarray(fixed, dtype=bool)
        self.log.append(("fixed", 0 if fixed is None else int(self.fixed.sum())))

    def _inverse_mass(self):
        inverse = 1.0 / self.masses[:, None]
        if getattr(self, "fixed", None) is not None:
            inverse = np.where(self.fixed[:, None], 0.0, inverse)
            self.vel[self.fixed] = 0.0
        return inverse

    def _forces(self):
        return -K * (self.pos - self.sites)

    def _energy(self):
        return 0.5 * K * float(((self.pos - self.sites) ** 2).sum()) - 3.0 * self.n

    def evaluate(self, positions, cell, compute_stress=True):
        assert np.array_equal(positions, self.pos)
        self.forces_current = True
        self.log.append("evaluate")
        return self._energy(), self._forces(), None

    def evaluate_energy(self, positions, cell):
        """The energy-only call: as the real engine's, the device positions are these afterwards and the forces
        are stale."""
        self.pos = np.array(positions, dtype=float)
        self.forces_current = False
        self.log.append("evaluate_energy")
        return self._energy()

    # --- dynamics
    def run(self, n_steps, it):
        assert n_steps > 0
        if not self.forces_current:
            self.log.append("force pass")
        dt = it.dt_fs * units.fs
        inverse_mass = self._inverse_mass()
        dof = (3 * (self.n - (int(self.fixed.sum()) if getattr(self, "fixed", None) is not None else 0))
               - (3 if it.fix_com else 0))
        forces = self._forces()
        for _ in range(n_steps):
            self.vel += 0.5 * dt * forces * inverse_mass
            self.pos += dt * self.vel
            forces = self._forces()
            self.vel += 0.5 * dt * forces * inverse_mass
            self.md_steps += 1
            self.total_steps += 1
            if it.thermo_every and self.md_steps % it.thermo_every == 0:
                e_kin = 0.5 * float((self.masses[:, None] * self.vel ** 2).sum())
                e_pot = float("nan") if self.md_steps == SpringEngine.poison_at else self._energy()
                self.rows.append((self.md_steps, e_pot, e_kin, 2 * e_kin / (dof * units.kB), 0.0, 0.0,
                                  e_pot + e_kin))
        self.forces_current = True
        self.log.append(("run", n_steps, it.kind, it.thermo_every))
        self.targets.append((n_steps, it.temp_k, it.temp_rate_k_per_step))
        self.fix_com = bool(it.fix_com)
        return _core.LoupMDStats(step_ms=0.5, rebuilds=1, final_temperature_k=300.0, pipelined_steps=n_steps - 1)

    def thermo_pending(self):
        return len(self.rows)

    def read_thermo(self, max_rows=None):
        out = np.array(self.rows, dtype=_core.THERMO_DTYPE)
        self.rows = []
        return out

    def get_state(self):
        return self.pos.copy(), self.vel.copy(), self._forces(), self._energy()

    def export_state(self):
        return pickle.dumps((self.n, self.pos, self.vel, self.cell, self.sites))

    def import_state(self, blob):
        n, pos, vel, cell, sites = pickle.loads(blob)
        if n != self.n:
            raise BackendError(f"loup_import_state: the state blob holds {n} atoms, the system {self.n}",
                               call="loup_import_state")
        self.pos, self.vel, self.cell, self.sites = pos.copy(), vel.copy(), cell.copy(), sites.copy()
        self.md_steps, self.rows, self.forces_current = 0, [], False
        self.log.append("import_state")
