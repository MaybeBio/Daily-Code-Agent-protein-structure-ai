"""Config records: frozen dataclasses that are checked when they are made.

Names and defaults are FastMACE's wherever the feature exists (``Output``, the integrator's ``ensemble`` /
``scheme`` / ``timestep_fs`` / ``temperature_K``). Units at the API: fs, K, A, eV; friction per fs. A value outside
its range raises ``InputError`` naming the record and the field. ``from_mapping`` makes a record from a table of a
run file and refuses unknown keys by name.
"""
from __future__ import annotations

import dataclasses
import math
import os
import typing
from dataclasses import dataclass
from typing import Literal

from .errors import InputError, PlanRefused

# The 3x accuracy rule of the gate (PLAN.md section 2). These are the rule, so they are not settings: a quantity
# passes when LoupMD's deviation from MACE float64 is at most GATE_FACTOR times MACE's own float32 deviation, or
# below the floor.
GATE_FACTOR = 3.0
GATE_ENERGY_FLOOR_MEV_PER_ATOM = 0.01
GATE_FORCE_FLOOR_EV_PER_A = 1e-5
GATE_STRESS_FLOOR_EV_PER_A3 = 1e-7

# Integrator schemes of each ensemble, the first being its default. BUILT are those the engine has.
SCHEMES = {"nve": ("nve",), "nvt": ("langevin", "csvr", "nose_hoover", "berendsen"),
           "npt": ("baoab", "mtk", "berendsen")}
BUILT = {"nve": ("nve",), "nvt": ("langevin", "csvr", "nose_hoover", "berendsen"),
         "npt": ("baoab", "mtk", "berendsen")}
BAROSTAT_FIELDS = ("pressure_GPa", "taup_fs", "compressibility_per_GPa", "mask", "cell_mode")
CELL_MODES = ("hydrostatic", "full")


def _name(record, field):
    return f"{type(record).__name__}.{field}"


def _check_choices(record):
    hints = typing.get_type_hints(type(record))
    for field in dataclasses.fields(record):
        hint, value = hints[field.name], getattr(record, field.name)
        if typing.get_origin(hint) is Literal:
            choices = typing.get_args(hint)
            if not isinstance(value, str) or value not in choices:
                raise InputError(f"{_name(record, field.name)}: {value!r} is not one of {choices}")


def _is_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _positive(record, *fields):
    for field in fields:
        value = getattr(record, field)
        if not _is_number(value) or value <= 0:
            raise InputError(f"{_name(record, field)} must be positive and finite, got {value!r}")


def _not_negative(record, *fields):
    for field in fields:
        value = getattr(record, field)
        if not _is_number(value) or value < 0:
            raise InputError(f"{_name(record, field)} must be finite and not negative, got {value!r}")


def _count(record, field, optional=False, what="an int of at least 1", unit=""):
    value = getattr(record, field)
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputError(f"{_name(record, field)} must be {what}{' or None' if optional else ''}{unit}, got {value!r}")


# ----------------------------------------------------------------------------------------------- integrator

@dataclass(frozen=True)
class IntegratorConfig:
    """What the engine integrates with. ``scheme=None`` takes the ensemble's default (``nve``; ``langevin`` for
    NVT). A thermostat's temperature, friction and time constant have no defaults: physics is not chosen silently.
    ``tau_fs`` is the time constant of the thermostats that have one (``csvr``: ASE's ``taut``; ``nose_hoover``:
    ASE's ``tdamp``). The Nose-Hoover chain has ``tchain`` thermostats and ``tloop`` sub-steps per half step
    (ASE's defaults 3 and 1); its thermostat masses are made for ``mass_temperature_K``, by default the
    ``temperature_K`` the record is made with, and stay when a schedule moves the target.

    Ensemble ``npt``, scheme ``baoab`` (the default; ASE's ``LangevinBAOAB`` with a barostat): ``temperature_K``,
    ``friction_per_fs`` (ASE's ``T_tau`` is its inverse) and ``pressure_GPa``; ``taup_fs`` is ASE's ``P_tau``
    (``None``: 20 ``T_tau``), ``cell_mode`` ``"hydrostatic"`` (the shape is kept) or ``"full"``. Scheme ``mtk``
    (ASE's ``IsotropicMTKNPT`` and ``MTKNPT``): ``temperature_K``, ``pressure_GPa``, ``tau_fs`` and ``taup_fs``
    (ASE's ``tdamp`` and ``pdamp``), the chains ``tchain`` x ``tloop`` and ``pchain`` x ``ploop`` (ASE's defaults
    3 and 1, at most 8 links), ``mass_temperature_K`` and ``cell_mode`` as above. Scheme
    ``berendsen`` (ASE's ``NPTBerendsen``) takes ``pressure_GPa``, ``taup_fs`` and the material's
    ``compressibility_per_GPa``; none has a default. Its ``mask`` (three 0 / 1 entries) lets each cell vector
    follow its own stress and leaves the masked ones alone (ASE's ``Inhomogeneous_NPTBerendsen``); without it
    the cell keeps its shape."""

    ensemble: Literal["nve", "nvt", "npt"] = "nvt"
    scheme: str | None = None
    timestep_fs: float = 0.5
    temperature_K: float | None = None
    friction_per_fs: float | None = None       # Langevin
    tau_fs: float | None = None                # CSVR, Nose-Hoover chain: the thermostat's time constant
    tchain: int | None = None                  # Nose-Hoover chain: thermostats in the chain
    tloop: int | None = None                   # Nose-Hoover chain: sub-steps per half step
    mass_temperature_K: float | None = None    # Nose-Hoover chain: the temperature of the thermostat masses
    pressure_GPa: float | None = None          # NPT: the barostat's target
    taup_fs: float | None = None               # NPT: the barostat's time constant
    compressibility_per_GPa: float | None = None   # Berendsen NPT: the material's compressibility
    mask: tuple | None = None                  # Berendsen NPT: the cell vectors the barostat scales, each by its own
    cell_mode: str | None = None               # BAOAB and MTK NPT: "hydrostatic" or "full"
    pchain: int | None = None                  # MTK NPT: links of the barostat's chain
    ploop: int | None = None                   # MTK NPT: sub-steps of the barostat's chain per half step
    seed: int = 20261001
    fixcm: bool = False                        # keep the centre of mass at rest (three degrees of freedom fewer)

    def __post_init__(self):
        _check_choices(self)
        scheme = self.scheme if self.scheme is not None else (SCHEMES[self.ensemble][0])
        if scheme not in SCHEMES[self.ensemble]:
            raise InputError(f"{_name(self, 'scheme')}: scheme {scheme!r} is not a scheme of ensemble "
                             f"{self.ensemble!r}", next_step=f"Its schemes: {', '.join(SCHEMES[self.ensemble])}.")
        if scheme not in BUILT[self.ensemble]:
            built = ", ".join(dict.fromkeys(name for names in BUILT.values() for name in names))
            raise InputError(f"{_name(self, 'scheme')}: {self.ensemble} with scheme {scheme!r} is not in this version",
                             next_step=f"Built schemes: {built}.")
        object.__setattr__(self, "scheme", scheme)
        _positive(self, "timestep_fs")
        if not isinstance(self.fixcm, bool):
            raise InputError(f"{_name(self, 'fixcm')} must be a bool, got {self.fixcm!r}")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or not 0 <= self.seed < 2 ** 64:
            raise InputError(f"{_name(self, 'seed')} must be an int from 0 to 2**64 - 1, got {self.seed!r}")
        if scheme not in ("nose_hoover", "mtk"):
            for field in ("tchain", "tloop", "mass_temperature_K"):
                if getattr(self, field) is not None:
                    raise InputError(f"{_name(self, field)} belongs to the Nose-Hoover chain (scheme 'nose_hoover'), "
                                     f"got {getattr(self, field)!r} with scheme {scheme!r}")
        if scheme != "mtk":
            for field in ("pchain", "ploop"):
                if getattr(self, field) is not None:
                    raise InputError(f"{_name(self, field)} belongs to the MTK barostat's chain (scheme 'mtk'), got "
                                     f"{getattr(self, field)!r} with scheme {scheme!r}")
        if scheme == "nve":
            for field in ("temperature_K", "friction_per_fs", "tau_fs"):
                if getattr(self, field) is not None:
                    raise InputError(f"{_name(self, field)}: NVE has no thermostat, got {getattr(self, field)!r}")
        elif scheme == "mtk":
            missing = [name for name in ("temperature_K", "pressure_GPa", "tau_fs", "taup_fs")
                       if getattr(self, name) is None]
            if missing:
                raise InputError(f"IntegratorConfig: MTK NPT needs {', '.join(missing)}",
                                 why="temperature, pressure and the two time constants (ASE's tdamp and pdamp) have "
                                     "no defaults")
            for field, owner in (("friction_per_fs", "its thermostat is a Nose-Hoover chain with a time constant"),
                                 ("compressibility_per_GPa", "it belongs to Berendsen's barostat"),
                                 ("mask", "it belongs to Berendsen's barostat")):
                if getattr(self, field) is not None:
                    raise InputError(f"{_name(self, field)} is not a setting of MTK NPT ({owner}), got "
                                     f"{getattr(self, field)!r}")
            _positive(self, "temperature_K", "tau_fs", "taup_fs")
            if not _is_number(self.pressure_GPa):
                raise InputError(f"{_name(self, 'pressure_GPa')} must be finite, got {self.pressure_GPa!r}")
            for field, default, most in (("tchain", 3, 8), ("pchain", 3, 8), ("tloop", 1, 100), ("ploop", 1, 100)):
                if getattr(self, field) is None:
                    object.__setattr__(self, field, default)
                value = getattr(self, field)
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
                    raise InputError(f"{_name(self, field)} must be an int from 1 to {most}, got {value!r}")
            if self.mass_temperature_K is None:
                object.__setattr__(self, "mass_temperature_K", self.temperature_K)
            _positive(self, "mass_temperature_K")
            if self.cell_mode is None:
                object.__setattr__(self, "cell_mode", "hydrostatic")
            if self.cell_mode not in CELL_MODES:
                raise InputError(f"{_name(self, 'cell_mode')} must be one of {CELL_MODES}, got {self.cell_mode!r}")
        elif scheme == "baoab":
            if self.temperature_K is None or self.friction_per_fs is None or self.pressure_GPa is None:
                raise InputError("IntegratorConfig: Langevin BAOAB NPT needs temperature_K, friction_per_fs and "
                                 "pressure_GPa", why="none has a default")
            for field, owner in (("tau_fs", "the thermostat has a friction, not a time constant"),
                                 ("compressibility_per_GPa", "it belongs to Berendsen's barostat"),
                                 ("mask", "it belongs to Berendsen's barostat")):
                if getattr(self, field) is not None:
                    raise InputError(f"{_name(self, field)} is not a setting of Langevin BAOAB NPT ({owner}), got "
                                     f"{getattr(self, field)!r}")
            _not_negative(self, "temperature_K")
            _positive(self, "friction_per_fs")
            if not _is_number(self.pressure_GPa):
                raise InputError(f"{_name(self, 'pressure_GPa')} must be finite, got {self.pressure_GPa!r}")
            if self.taup_fs is not None:
                _positive(self, "taup_fs")
            if self.cell_mode is None:
                object.__setattr__(self, "cell_mode", "hydrostatic")
            if self.cell_mode not in CELL_MODES:
                raise InputError(f"{_name(self, 'cell_mode')} must be one of {CELL_MODES}, got {self.cell_mode!r}")
            if self.fixcm:
                raise InputError(f"{_name(self, 'fixcm')} must be False for Langevin BAOAB NPT",
                                 why="BAOAB, as ASE's LangevinBAOAB, does not remove the centre of mass's motion")
        elif scheme == "langevin":
            if self.temperature_K is None or self.friction_per_fs is None:
                raise InputError("IntegratorConfig: Langevin needs temperature_K and friction_per_fs",
                                 why="neither has a default")
            if self.tau_fs is not None:
                raise InputError(f"{_name(self, 'tau_fs')}: Langevin has a friction, not a time constant, got "
                                 f"{self.tau_fs!r}")
            _not_negative(self, "temperature_K")
            _positive(self, "friction_per_fs")
        elif scheme == "csvr":
            if self.temperature_K is None or self.tau_fs is None:
                raise InputError("IntegratorConfig: CSVR needs temperature_K and tau_fs", why="neither has a default")
            if self.friction_per_fs is not None:
                raise InputError(f"{_name(self, 'friction_per_fs')}: CSVR has a time constant (tau_fs), not a "
                                 f"friction, got {self.friction_per_fs!r}")
            _not_negative(self, "temperature_K")
            _positive(self, "tau_fs")
        elif scheme == "berendsen":
            if self.temperature_K is None or self.tau_fs is None:
                raise InputError("IntegratorConfig: the Berendsen thermostat needs temperature_K and tau_fs (ASE's "
                                 "taut)", why="neither has a default")
            if self.friction_per_fs is not None:
                raise InputError(f"{_name(self, 'friction_per_fs')}: the Berendsen thermostat has a time constant "
                                 f"(tau_fs), not a friction, got {self.friction_per_fs!r}")
            _not_negative(self, "temperature_K")
            _positive(self, "tau_fs")
            if self.tau_fs < self.timestep_fs:
                raise InputError(f"{_name(self, 'tau_fs')} must be at least the timestep for the Berendsen "
                                 f"thermostat, got {self.tau_fs!r} fs with timestep_fs = {self.timestep_fs!r}")
            if self.ensemble == "npt":
                missing = [name for name in BAROSTAT_FIELDS[:3] if getattr(self, name) is None]
                if missing:
                    raise InputError(f"IntegratorConfig: the Berendsen barostat needs {', '.join(missing)}",
                                     why="pressure, time constant and compressibility have no defaults")
                if not _is_number(self.pressure_GPa):
                    raise InputError(f"{_name(self, 'pressure_GPa')} must be finite, got {self.pressure_GPa!r}")
                _positive(self, "taup_fs", "compressibility_per_GPa")
                if self.mask is not None:
                    mask = tuple(self.mask) if isinstance(self.mask, (tuple, list)) else None
                    if mask is None or len(mask) != 3 or any(isinstance(m, bool) or m not in (0, 1) for m in mask):
                        raise InputError(f"{_name(self, 'mask')} must be three entries of 0 or 1, got {self.mask!r}")
                    if not any(mask):
                        raise InputError(f"{_name(self, 'mask')} frees no axis: (0, 0, 0) is a run at fixed cell",
                                         next_step="Use ensemble 'nvt' for that.")
                    object.__setattr__(self, "mask", tuple(int(m) for m in mask))
                if self.cell_mode is not None:
                    raise InputError(f"{_name(self, 'cell_mode')} belongs to Langevin BAOAB and MTK NPT; Berendsen's "
                                     f"barostat keeps the shape or takes a mask, got {self.cell_mode!r}")
        elif scheme == "nose_hoover":
            if self.temperature_K is None or self.tau_fs is None:
                raise InputError("IntegratorConfig: the Nose-Hoover chain needs temperature_K and tau_fs (ASE's "
                                 "tdamp)", why="neither has a default")
            if self.friction_per_fs is not None:
                raise InputError(f"{_name(self, 'friction_per_fs')}: the Nose-Hoover chain has a time constant "
                                 f"(tau_fs), not a friction, got {self.friction_per_fs!r}")
            _not_negative(self, "temperature_K")
            _positive(self, "tau_fs")
            for field, default, most in (("tchain", 3, 16), ("tloop", 1, 100)):
                if getattr(self, field) is None:
                    object.__setattr__(self, field, default)
                value = getattr(self, field)
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= most:
                    raise InputError(f"{_name(self, field)} must be an int from 1 to {most}, got {value!r}")
            if self.mass_temperature_K is None:
                object.__setattr__(self, "mass_temperature_K", self.temperature_K)
            _positive(self, "mass_temperature_K")
        if self.ensemble != "npt":
            given = [name for name in BAROSTAT_FIELDS if getattr(self, name) is not None]
            if given:
                raise InputError(f"IntegratorConfig: {', '.join(given)} belong{'s' if len(given) == 1 else ''} to a "
                                 f"barostat, and the ensemble is {self.ensemble!r}",
                                 next_step="ensemble='npt' with scheme 'berendsen'.")

    def to_struct(self, thermo_every: int = 0, temperature_K=None, rate_K_per_step: float = 0.0):
        """The ``LoupIntegrator`` of this record for ``loup_run``; ``thermo_every`` is the output's cadence. A
        schedule passes the call's starting target and its change per step (``temperature_K``,
        ``rate_K_per_step``): step i of the call runs at ``temperature_K + i * rate_K_per_step``."""
        from . import _core

        if self.scheme == "nve":
            return _core.integrator(_core.LOUP_NVE, self.timestep_fs, thermo_every=int(thermo_every),
                                    fix_com=int(self.fixcm))
        temperature = self.temperature_K if temperature_K is None else temperature_K
        if self.scheme == "mtk":
            return _core.integrator(_core.LOUP_MTK_NPT, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step), tau_t_fs=float(self.tau_fs),
                                    tau_p_fs=float(self.taup_fs), pressure_gpa=float(self.pressure_GPa),
                                    mass_temp_k=float(self.mass_temperature_K), chain_length=int(self.tchain),
                                    chain_loops=int(self.tloop), p_chain_length=int(self.pchain),
                                    p_chain_loops=int(self.ploop),
                                    cell_mode=(_core.LOUP_CELL_FULL if self.cell_mode == "full"
                                               else _core.LOUP_CELL_HYDROSTATIC),
                                    thermo_every=int(thermo_every), fix_com=int(self.fixcm))
        if self.scheme == "baoab":
            return _core.integrator(_core.LOUP_BAOAB_NPT, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step),
                                    friction_per_fs=float(self.friction_per_fs),
                                    pressure_gpa=float(self.pressure_GPa),
                                    tau_p_fs=0.0 if self.taup_fs is None else float(self.taup_fs),
                                    cell_mode=(_core.LOUP_CELL_FULL if self.cell_mode == "full"
                                               else _core.LOUP_CELL_HYDROSTATIC),
                                    seed=self.seed, thermo_every=int(thermo_every))
        if self.scheme == "berendsen" and self.ensemble == "npt":
            cell = ({} if self.mask is None else
                    dict(cell_mode=_core.LOUP_CELL_FULL, cell_mask=tuple(int(m) for m in self.mask)))
            return _core.integrator(_core.LOUP_BERENDSEN_NPT, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step), tau_t_fs=float(self.tau_fs),
                                    pressure_gpa=float(self.pressure_GPa), tau_p_fs=float(self.taup_fs),
                                    compressibility_per_gpa=float(self.compressibility_per_GPa),
                                    thermo_every=int(thermo_every), fix_com=int(self.fixcm), **cell)
        if self.scheme == "berendsen":
            return _core.integrator(_core.LOUP_BERENDSEN_NVT, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step), tau_t_fs=float(self.tau_fs),
                                    thermo_every=int(thermo_every), fix_com=int(self.fixcm))
        if self.scheme == "nose_hoover":
            return _core.integrator(_core.LOUP_NHC, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step), tau_t_fs=float(self.tau_fs),
                                    mass_temp_k=float(self.mass_temperature_K), chain_length=int(self.tchain),
                                    chain_loops=int(self.tloop), thermo_every=int(thermo_every),
                                    fix_com=int(self.fixcm))
        if self.scheme == "csvr":
            return _core.integrator(_core.LOUP_CSVR, self.timestep_fs, temp_k=float(temperature),
                                    temp_rate_k_per_step=float(rate_K_per_step), tau_t_fs=float(self.tau_fs),
                                    seed=self.seed, thermo_every=int(thermo_every), fix_com=int(self.fixcm))
        return _core.integrator(_core.LOUP_LANGEVIN, self.timestep_fs, temp_k=float(temperature),
                                temp_rate_k_per_step=float(rate_K_per_step),
                                friction_per_fs=float(self.friction_per_fs), seed=self.seed,
                                thermo_every=int(thermo_every), fix_com=int(self.fixcm))


# --------------------------------------------------------------------------------------------------- output

@dataclass(frozen=True)
class Output:
    """Output directory and cadences in MD steps (FastMACE's record and defaults). ``trajectory_every`` and
    ``restart_every`` may be ``None`` (no trajectory, no restart files); thermo rows are always written.
    ``directory`` is kept as given, as a string."""

    directory: str
    trajectory_every: int | None = 20
    thermo_every: int = 20
    restart_every: int | None = 10_000

    def __post_init__(self):
        directory = os.fspath(self.directory) if isinstance(self.directory, os.PathLike) else self.directory
        if not isinstance(directory, str) or not directory:
            raise InputError(f"Output.directory must be a non-empty path, got {self.directory!r}")
        object.__setattr__(self, "directory", directory)
        _count(self, "trajectory_every", optional=True, what="a positive int", unit=" (steps)")
        _count(self, "thermo_every", what="a positive int", unit=" (steps)")
        _count(self, "restart_every", optional=True, what="a positive int", unit=" (steps)")


# ------------------------------------------------------------------------------------------------- the gate

@dataclass(frozen=True)
class GateConfig:
    """How the accuracy gate samples the user's structure and where its references run. Whether it runs is
    ``check=``; the rule itself is fixed (``GATE_FACTOR`` and the floors above)."""

    rattle_A: float = 0.05                    # standard deviation of the displacement of each copy
    copies: int = 2                           # rattled copies gated
    strain: float = 0.02                      # two strained copies more for NPT
    reference_device: Literal["auto", "cuda", "cpu"] = "auto"   # auto: the GPU, then the CPU when memory runs out
    cpu_float64_time_limit_s: float = 300.0   # the CPU is tried only if its estimated time is within this; 0: never

    def __post_init__(self):
        _check_choices(self)
        _positive(self, "rattle_A", "strain")
        _count(self, "copies")
        _not_negative(self, "cpu_float64_time_limit_s")


# ------------------------------------------------------------------------------------------------- capacity

@dataclass(frozen=True)
class CapacityConfig:
    """How a system that may not fit the GPU whole is run (``capacity=``; the tiled modes are Stage 5)."""

    mode: Literal["auto", "whole", "tiled", "wavefront"] = "auto"
    memory_fraction: float = 0.9              # of the free GPU memory the plan may use
    receivers: int | None = None              # receiving atoms per tile; None: from the memory plan
    state: Literal["auto", "device", "host"] = "auto"           # where the layer states of a tiled run live

    def __post_init__(self):
        _check_choices(self)
        if not _is_number(self.memory_fraction) or not 0.0 < self.memory_fraction <= 1.0:
            raise InputError(f"CapacityConfig.memory_fraction must be above 0 and at most 1, got "
                             f"{self.memory_fraction!r}")
        _count(self, "receivers", optional=True)

    @property
    def exec_mode(self) -> int:
        """The ``LOUP_EXEC_*`` constant of ``mode``."""
        from . import _core

        return {"auto": _core.LOUP_EXEC_AUTO, "whole": _core.LOUP_EXEC_WHOLE, "tiled": _core.LOUP_EXEC_TILED,
                "wavefront": _core.LOUP_EXEC_WAVEFRONT}[self.mode]


# ---------------------------------------------------------------------------------------------- from_mapping

def from_mapping(record_class, mapping, section=None):
    """``record_class(**mapping)`` for a table of a run file. Unknown keys are refused by name, all at once, with
    the keys the record has; a required key that is missing is named too."""
    where = f"[{section}]" if section else record_class.__name__
    if not isinstance(mapping, typing.Mapping):
        raise InputError(f"{where} is not a table of keys and values, got {type(mapping).__name__}")
    fields = dataclasses.fields(record_class)
    names = [f.name for f in fields]
    unknown = [key for key in mapping if key not in names]
    if unknown:
        listing = ", ".join(repr(key) for key in unknown)
        raise InputError(f"unknown key{'s' if len(unknown) > 1 else ''} {listing} in {where}",
                         next_step=f"Keys of {where}: {', '.join(names)}.")
    required = [f.name for f in fields
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING]
    missing = [name for name in required if name not in mapping]
    if missing:
        raise InputError(f"{where} lacks {', '.join(missing)}")
    return record_class(**mapping)


@dataclass(frozen=True)
class Workload:
    """FastMACE's planner workload, for code that passes one: LoupMD has one execution plan, so only
    ``reproducible`` is kept, and only ``False``. The bitwise-reproducible mode was cut (PLAN.md decision A3)."""

    reproducible: bool = False

    def __post_init__(self):
        if self.reproducible:
            raise PlanRefused("Workload(reproducible=True): the bitwise-reproducible mode is not in LoupMD",
                              why="it was cut from the release (PLAN.md decision A3): float32 atomic sums on the GPU "
                                  "differ in their last bits from run to run",
                              next_step="Leave reproducible at False. The seed fixes the thermostat's noise, and a "
                                        "restart (Simulation.resume) continues a run from its saved state.")
