"""``lm.integrators``: the integrator records a ``Simulation`` takes as ``integrator=``.

Names and arguments are FastMACE's (``fm.integrators``). Units: fs, K, friction per fs. A thermostat's temperature
and friction have no defaults: physics is not chosen silently. Each record maps onto an ``IntegratorConfig``
(``to_config``), which is what the engine runs: ``NVE``, ``Langevin``, ``CSVR``, ``NoseHooverChain`` and
``Berendsen`` at constant volume (``Berendsen`` with a pressure couples the cell too), and ``LangevinBAOAB`` and
``MTK`` at constant pressure.

``fixcm`` keeps the centre of mass at rest, as in FastMACE: ``"auto"`` (the default) is on, and off when the
structure has fixed atoms, which pin the frame already; ``True`` with fixed atoms is refused. Langevin's noise then
loses its mass-weighted mean every step (FastMACE's ``"mass_weighted"`` projection); the total momentum of NVE,
CSVR and the Nose-Hoover chain is removed at the start of every run call. The temperature counts three degrees
of freedom fewer, and so do the thermostats that count them (CSVR, the Nose-Hoover chain).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import IntegratorConfig
from .errors import InputError, PlanRefused

__all__ = ["Berendsen", "CSVR", "Langevin", "LangevinBAOAB", "MTK", "NVE", "NoseHooverChain"]


def resolve_fixcm(fixcm, fixed_atoms) -> bool:
    """A record's ``fixcm`` for a structure with (``fixed_atoms``) or without fixed atoms: ``"auto"`` is off with
    fixed atoms and on without; ``True`` with fixed atoms is refused."""
    if fixcm == "auto":
        return not fixed_atoms
    if fixcm and fixed_atoms:
        raise PlanRefused("fixcm=True with fixed atoms", why="the fixed atoms pin the frame already",
                          next_step="Leave fixcm at 'auto' (off with fixed atoms), or remove the FixAtoms constraint.")
    return bool(fixcm)


@dataclass(frozen=True, kw_only=True)
class NVE:
    """Velocity Verlet: ``lm.integrators.NVE(timestep_fs=1.0)``. The conserved quantity is E_kin + E_pot."""

    timestep_fs: float
    fixcm: bool | Literal["auto"] = "auto"

    def __post_init__(self):
        IntegratorConfig(ensemble="nve", timestep_fs=self.timestep_fs)      # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"NVE.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        return IntegratorConfig(ensemble="nve", timestep_fs=float(self.timestep_fs), seed=seed,
                                fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


@dataclass(frozen=True, kw_only=True)
class Langevin:
    """Langevin NVT: ``lm.integrators.Langevin(timestep_fs=0.5, temperature_K=300, friction_per_fs=0.002)``."""

    timestep_fs: float = 0.5
    temperature_K: float
    friction_per_fs: float
    fixcm: bool | Literal["auto"] = "auto"

    def __post_init__(self):
        IntegratorConfig(timestep_fs=self.timestep_fs, temperature_K=self.temperature_K,
                         friction_per_fs=self.friction_per_fs)               # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"Langevin.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        return IntegratorConfig(ensemble="nvt", timestep_fs=float(self.timestep_fs),
                                temperature_K=float(self.temperature_K),
                                friction_per_fs=float(self.friction_per_fs), seed=seed,
                                fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


@dataclass(frozen=True, kw_only=True)
class CSVR:
    """Canonical sampling through velocity rescaling (Bussi, Donadio, Parrinello), as ASE's ``Bussi``:
    ``lm.integrators.CSVR(timestep_fs=1.0, temperature_K=300, tau_fs=100)``.

    ``tau_fs`` is ASE's ``taut``. The conserved quantity is E_kin + E_pot minus the energy the thermostat has
    transferred. The velocities are rescaled, so the structure must move at the start (as ASE's ``Bussi``)."""

    timestep_fs: float
    temperature_K: float
    tau_fs: float
    fixcm: bool | Literal["auto"] = "auto"

    def __post_init__(self):
        IntegratorConfig(scheme="csvr", timestep_fs=self.timestep_fs, temperature_K=self.temperature_K,
                         tau_fs=self.tau_fs)                                 # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"CSVR.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        return IntegratorConfig(ensemble="nvt", scheme="csvr", timestep_fs=float(self.timestep_fs),
                                temperature_K=float(self.temperature_K), tau_fs=float(self.tau_fs), seed=seed,
                                fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


@dataclass(frozen=True, kw_only=True)
class NoseHooverChain:
    """Nose-Hoover chains, as ASE's ``NoseHooverChainNVT``:
    ``lm.integrators.NoseHooverChain(timestep_fs=1.0, temperature_K=300, tdamp_fs=100)``.

    ``tdamp_fs``, ``tchain`` and ``tloop`` are ASE's ``tdamp``, ``tchain`` and ``tloop``. The thermostat masses
    are made for ``temperature_K`` and stay when a schedule moves the target, as ASE's and FastMACE's. The
    conserved quantity is E_kin + E_pot plus the chain's energy. The degrees of freedom of the reported
    temperature stand where ASE counts 3 N: 3 N - 3 with the centre of mass at rest, 3 (N - fixed) with fixed
    atoms."""

    timestep_fs: float
    temperature_K: float
    tdamp_fs: float
    tchain: int = 3
    tloop: int = 1
    fixcm: bool | Literal["auto"] = "auto"

    def __post_init__(self):
        if (not isinstance(self.temperature_K, bool) and isinstance(self.temperature_K, (int, float))
                and self.temperature_K == 0):
            raise InputError(f"NoseHooverChain.temperature_K must be above 0 K (the thermostat masses are made "
                             f"for it), got {self.temperature_K!r}",
                             next_step="For a run that starts at 0 K give the temperature the masses should be "
                                       "made for here and the targets as a schedule.")
        IntegratorConfig(scheme="nose_hoover", timestep_fs=self.timestep_fs, temperature_K=self.temperature_K,
                         tau_fs=self.tdamp_fs, tchain=self.tchain, tloop=self.tloop)       # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"NoseHooverChain.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        return IntegratorConfig(ensemble="nvt", scheme="nose_hoover", timestep_fs=float(self.timestep_fs),
                                temperature_K=float(self.temperature_K), tau_fs=float(self.tdamp_fs),
                                tchain=self.tchain, tloop=self.tloop, seed=seed,
                                fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


@dataclass(frozen=True, kw_only=True)
class Berendsen:
    """Berendsen thermostat, as ASE's ``NVTBerendsen``:
    ``lm.integrators.Berendsen(timestep_fs=1.0, temperature_K=300, taut_fs=100)``; with ``pressure_GPa``,
    ``taup_fs`` and ``compressibility_per_GPa`` also Berendsen's barostat, as ASE's ``NPTBerendsen``
    (experimental):
    ``lm.integrators.Berendsen(timestep_fs=1.0, temperature_K=300, taut_fs=100, pressure_GPa=0.0,
    taup_fs=1000, compressibility_per_GPa=0.006)``.

    Not canonical: for equilibration only. ``taut_fs`` and ``taup_fs`` are ASE's ``taut`` and ``taup``,
    ``compressibility_per_GPa`` the material's compressibility (ASE's ``compressibility_au`` times
    ``units.GPa``). Without ``mask`` the cell keeps its shape; ``mask=(1, 1, 0)`` lets the first two cell
    vectors follow their own stress and leaves the third alone (ASE's ``Inhomogeneous_NPTBerendsen``). The
    barostat makes one force call per step: the first kick of a step uses the forces of the cell before its
    scaling, where ASE's classes evaluate again. Not with fixed atoms."""

    timestep_fs: float
    temperature_K: float
    taut_fs: float
    pressure_GPa: float | None = None
    taup_fs: float | None = None
    compressibility_per_GPa: float | None = None
    mask: tuple | None = None
    fixcm: bool | Literal["auto"] = "auto"

    def __post_init__(self):
        self._config(seed=0, fixcm=False)                                    # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"Berendsen.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    @property
    def barostat(self) -> bool:
        return any(getattr(self, name) is not None
                   for name in ("pressure_GPa", "taup_fs", "compressibility_per_GPa", "mask"))

    def _config(self, *, seed, fixcm) -> IntegratorConfig:
        if not self.barostat:
            return IntegratorConfig(ensemble="nvt", scheme="berendsen", timestep_fs=self.timestep_fs,
                                    temperature_K=self.temperature_K, tau_fs=self.taut_fs, seed=seed, fixcm=fixcm)
        return IntegratorConfig(ensemble="npt", scheme="berendsen", timestep_fs=self.timestep_fs,
                                temperature_K=self.temperature_K, tau_fs=self.taut_fs,
                                pressure_GPa=self.pressure_GPa, taup_fs=self.taup_fs,
                                compressibility_per_GPa=self.compressibility_per_GPa, mask=self.mask, seed=seed,
                                fixcm=fixcm)

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        if self.barostat and fixed_atoms:
            raise PlanRefused("Berendsen's barostat with fixed atoms",
                              why="the cell's scaling would move the fixed atoms",
                              next_step="Leave the barostat's fields out, or free the atoms.")
        return self._config(seed=seed, fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


@dataclass(frozen=True, kw_only=True)
class LangevinBAOAB:
    """Langevin BAOAB NPT, as ASE's ``LangevinBAOAB`` with a barostat (experimental):
    ``lm.integrators.LangevinBAOAB(timestep_fs=1.0, temperature_K=300, friction_per_fs=0.002, pressure_GPa=0.0)``.

    BAOAB Langevin dynamics for the atoms (Leimkuhler and Matthews) and a Langevin-Hoover barostat for the cell
    (Quigley and Probert). ``friction_per_fs`` is the thermostat's friction (ASE's ``T_tau`` is its inverse);
    ``cell_mode`` is ``"hydrostatic"`` (the cell keeps its shape; ASE's ``hydrostatic=True``) or ``"full"``;
    ``barostat_tau_fs`` is ASE's ``P_tau`` (``None``: ASE's default, 20 ``T_tau``). The barostat's mass is ASE's
    heuristic. In the full-cell mode the barostat's drag on the velocities is Quigley and Probert's; ASE 3.27
    adds its trace term to all nine elements. ``fixcm`` is ``False`` only, as for ASE's class.

    FastMACE's record also takes ``external_stress_GPa``, ``barostat_mass_factor``,
    ``disable_cell_langevin``, ``max_volume_ratio`` and ``max_cell_length_A``; here the target is a pressure,
    the mass factor 1, the cell's thermostat on, and the run stops once the volume leaves a twentieth to
    twenty times its start (the values FastMACE defaults to); other values are refused by name."""

    timestep_fs: float
    temperature_K: float
    friction_per_fs: float
    pressure_GPa: float = 0.0
    external_stress_GPa: float | tuple | None = None
    cell_mode: Literal["hydrostatic", "full"] = "hydrostatic"
    barostat_tau_fs: float | None = None
    barostat_mass_factor: float = 1.0
    disable_cell_langevin: bool = False
    fixcm: bool = False
    max_volume_ratio: float | None = 20.0
    max_cell_length_A: float | None = 1000.0

    barostat = True

    def __post_init__(self):
        for name, default, why in (
                ("external_stress_GPa", None, "the target is a pressure (pressure_GPa)"),
                ("barostat_mass_factor", 1.0, "the barostat's mass is ASE's heuristic"),
                ("disable_cell_langevin", False, "the cell's thermostat is always on"),
                ("max_volume_ratio", 20.0, "the run stops outside a twentieth to twenty times its first volume"),
                ("max_cell_length_A", 1000.0, "there is no limit on a cell vector's length beside the volume's")):
            if getattr(self, name) != default or isinstance(getattr(self, name), bool) != isinstance(default, bool):
                raise PlanRefused(f"LangevinBAOAB.{name}={getattr(self, name)!r} is not in this version",
                                  why=why, next_step=f"Leave {name} at {default!r}.")
        if self.fixcm is not False:
            raise InputError(f"LangevinBAOAB.fixcm must be False, got {self.fixcm!r}",
                             why="BAOAB, as ASE's LangevinBAOAB, does not remove the centre of mass's motion")
        self._config(seed=0)                                                 # checks the values

    def _config(self, *, seed) -> IntegratorConfig:
        return IntegratorConfig(ensemble="npt", scheme="baoab", timestep_fs=self.timestep_fs,
                                temperature_K=self.temperature_K, friction_per_fs=self.friction_per_fs,
                                pressure_GPa=self.pressure_GPa, taup_fs=self.barostat_tau_fs,
                                cell_mode=self.cell_mode, seed=seed, fixcm=False)

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        if fixed_atoms:
            raise PlanRefused("LangevinBAOAB with fixed atoms", why="the cell's scaling would move the fixed atoms",
                              next_step="Free the atoms, or use a thermostat alone (Langevin).")
        return self._config(seed=seed)


@dataclass(frozen=True, kw_only=True)
class MTK:
    """Martyna-Tobias-Klein NPT with Nose-Hoover chains on the atoms and on the cell, as ASE's
    ``IsotropicMTKNPT`` (``cell_mode="hydrostatic"``) and ``MTKNPT`` (``"full"``); experimental:
    ``lm.integrators.MTK(timestep_fs=1.0, temperature_K=300, pressure_GPa=0.0, tdamp_fs=100, pdamp_fs=1000)``.

    ``tdamp_fs``, ``pdamp_fs``, ``tchain``, ``pchain``, ``tloop`` and ``ploop`` are ASE's ``tdamp``, ``pdamp``,
    ``tchain``, ``pchain``, ``tloop`` and ``ploop`` (chains of at most 8 links). Deterministic; the conserved
    quantity is E_pot + E_kin plus both chains' energies, the cell's kinetic energy and P V. The masses of both
    chains and of the cell are made for ``temperature_K`` and stay when a schedule moves the target. The degrees
    of freedom stand where ASE counts 3 N: 3 N - 3 with the centre of mass at rest (``fixcm``). FastMACE's record
    has a ``dof`` field beside ``fixcm``; here the count follows ``fixcm`` alone."""

    timestep_fs: float
    temperature_K: float
    pressure_GPa: float
    tdamp_fs: float
    pdamp_fs: float
    tchain: int = 3
    pchain: int = 3
    tloop: int = 1
    ploop: int = 1
    cell_mode: Literal["hydrostatic", "full"] = "hydrostatic"
    fixcm: bool | Literal["auto"] = "auto"

    barostat = True

    def __post_init__(self):
        self._config(seed=0, fixcm=False)                                    # checks the values
        if not isinstance(self.fixcm, bool) and self.fixcm != "auto":
            raise InputError(f"MTK.fixcm must be True, False or 'auto', got {self.fixcm!r}")

    def _config(self, *, seed, fixcm) -> IntegratorConfig:
        return IntegratorConfig(ensemble="npt", scheme="mtk", timestep_fs=self.timestep_fs,
                                temperature_K=self.temperature_K, pressure_GPa=self.pressure_GPa,
                                tau_fs=self.tdamp_fs, taup_fs=self.pdamp_fs, tchain=self.tchain, pchain=self.pchain,
                                tloop=self.tloop, ploop=self.ploop, cell_mode=self.cell_mode, seed=seed, fixcm=fixcm)

    def to_config(self, *, seed: int, fixed_atoms: bool = False) -> IntegratorConfig:
        if fixed_atoms:
            raise PlanRefused("MTK with fixed atoms", why="the cell's scaling would move the fixed atoms",
                              next_step="Free the atoms, or use a thermostat alone (NoseHooverChain).")
        return self._config(seed=seed, fixcm=resolve_fixcm(self.fixcm, fixed_atoms))


RECORDS = {"NVE": NVE, "Langevin": Langevin, "CSVR": CSVR, "NoseHooverChain": NoseHooverChain,
           "Berendsen": Berendsen, "LangevinBAOAB": LangevinBAOAB, "MTK": MTK}


def to_data(record) -> dict:
    """An integrator record as a table: ``{"type": "CSVR", "timestep_fs": ..., ...}`` (a run file's
    ``[integrator]``)."""
    import dataclasses

    if type(record) not in RECORDS.values():
        raise InputError(f"integrator must be an lm.integrators record, got {type(record).__name__}")
    return {"type": type(record).__name__, **dataclasses.asdict(record)}


def from_data(data, *, timestep_fs=None, temperature_K=None):
    """The record of a table (``to_data``). ``timestep_fs`` and ``temperature_K`` fill those fields where the
    table leaves them out (a run file states them once, outside the table). Unknown keys are refused by name."""
    import dataclasses
    from collections.abc import Mapping

    if not isinstance(data, Mapping):
        raise InputError(f"[integrator] is not a table of keys and values, got {type(data).__name__}")
    data = dict(data)
    kind = data.pop("type", None)
    if kind not in RECORDS:
        raise InputError(f"[integrator] type {kind!r} is not one of {', '.join(RECORDS)}",
                         why="the other integrators of FastMACE are not in this version")
    names = [field.name for field in dataclasses.fields(RECORDS[kind])]
    unknown = [key for key in data if key not in names]
    if unknown:
        raise InputError(f"unknown key{'s' if len(unknown) > 1 else ''} {', '.join(repr(k) for k in unknown)} in "
                         f"[integrator] of type {kind}", next_step=f"Its keys: type, {', '.join(names)}.")
    for name, value in (("timestep_fs", timestep_fs), ("temperature_K", temperature_K)):
        if name in names and name not in data and value is not None:
            data[name] = value
    missing = [field.name for field in dataclasses.fields(RECORDS[kind])
               if field.default is dataclasses.MISSING and field.name not in data]
    if missing:
        raise InputError(f"[integrator] of type {kind} lacks {', '.join(missing)}",
                         why="a thermostat's temperature, friction and time constant have no defaults")
    return RECORDS[kind](**data)
