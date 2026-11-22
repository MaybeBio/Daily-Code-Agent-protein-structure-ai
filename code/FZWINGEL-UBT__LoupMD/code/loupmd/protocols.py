"""``lm.protocols``: temperature schedules (ramps and holds) and the run profiles.

Ported from FastMACE (``fastmace/protocols/schedule.py`` and ``profiles.py``), with the same names, arguments and
rounding, so a schedule means the same run in both codes:

- A ``Schedule`` is timestep-free: segments in ps. ``Schedule.resolve(timestep_fs)`` rounds each segment to whole
  steps (half up) and records the boundaries, the total and the rounded durations and rates.
- The target is piecewise linear in the step. Step ``n`` of a segment uses the target at the step's end point, so
  the target changes every step on a ramp and never on a hold. Each ramp interpolates from its colder end.
- ``ScheduleState`` is the schedule position: what a restart stores.
- ``PROFILES`` holds the profiles ``slow``, ``fast``, ``ultrafast`` and ``anneal`` as data. Their relaxation and
  quench settings are data only here (PLAN.md Stage 4 runs them).

A profile's ensemble is NVT or NPT at a constant pressure; pressure schedules are refused.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from .errors import InputError

KINDS = ("ramp", "hold")


def _temperature(value, name) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{name} must be a number of kelvin, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise InputError(f"{name} must be finite and at least 0 K, got {value}")
    return value


def _positive(value, name) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{name} must be a number, got {value!r}")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise InputError(f"{name} must be positive and finite, got {value}")
    return value


def _count(value, name) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"{name} must be an int, got {value!r}")
    return value


@dataclass(frozen=True)
class Segment:
    """One ramp or hold as requested: ``ps`` or (ramps only) ``rate_K_per_ps``, never both."""

    kind: str
    start_K: float
    end_K: float
    ps: float | None = None
    rate_K_per_ps: float | None = None

    def __post_init__(self):
        if self.kind not in KINDS:
            raise InputError(f"segment kind must be one of {KINDS}, got {self.kind!r}")
        object.__setattr__(self, "start_K", _temperature(self.start_K, "start temperature"))
        object.__setattr__(self, "end_K", _temperature(self.end_K, "end temperature"))
        if (self.ps is None) == (self.rate_K_per_ps is None):
            raise InputError(f"a {self.kind} needs exactly one of ps= and rate_K_per_ps=")
        if self.ps is not None:
            object.__setattr__(self, "ps", _positive(self.ps, "ps"))
            return
        if self.kind == "hold":
            raise InputError("a hold needs ps=")
        rate = self.rate_K_per_ps
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate):
            raise InputError(f"rate_K_per_ps must be a finite number, got {rate!r}")
        change = self.end_K - self.start_K
        if change == 0 or rate == 0 or (rate > 0) != (change > 0):
            raise InputError(f"rate_K_per_ps={rate} does not lead from {self.start_K} K to {self.end_K} K (the sign "
                             "must follow the ramp's direction)")
        object.__setattr__(self, "rate_K_per_ps", float(rate))

    @property
    def duration_ps(self) -> float:
        """The requested duration (before rounding to whole steps)."""
        if self.ps is not None:
            return self.ps
        return (self.end_K - self.start_K) / self.rate_K_per_ps

    @property
    def phase(self) -> str:
        """``heating``, ``cooling`` or ``hold``: the thermo file's phase column."""
        if self.end_K > self.start_K:
            return "heating"
        return "cooling" if self.end_K < self.start_K else "hold"

    def to_data(self) -> dict:
        """The segment as profile data (``segment_from_data`` reads it back)."""
        if self.kind == "hold":
            return {"kind": "hold", "temperature_K": self.start_K, "ps": self.ps}
        data = {"kind": "ramp", "start_K": self.start_K, "end_K": self.end_K}
        if self.ps is not None:
            data["ps"] = self.ps
        else:
            data["rate_K_per_ps"] = self.rate_K_per_ps
        return data


_SEGMENT_KEYS = {"ramp": ({"kind", "start_K", "end_K"}, {"ps", "rate_K_per_ps"}),
                 "hold": ({"kind", "temperature_K", "ps"}, set())}


def segment_from_data(data) -> Segment:
    """A segment from profile or restart data: ``{kind: ramp, start_K, end_K, ps | rate_K_per_ps}`` or
    ``{kind: hold, temperature_K, ps}``. Unknown keys are refused by name."""
    if not isinstance(data, Mapping):
        raise InputError(f"a segment must be a mapping, got {data!r}")
    kind = data.get("kind")
    if kind not in _SEGMENT_KEYS:
        raise InputError(f"segment kind must be one of {KINDS}, got {kind!r}")
    required, optional = _SEGMENT_KEYS[kind]
    missing, unknown = required - set(data), set(data) - required - optional
    if missing or unknown:
        raise InputError(f"{kind} segment: missing {sorted(missing)}, unknown {sorted(unknown)}")
    if kind == "hold":
        return Segment("hold", data["temperature_K"], data["temperature_K"], data["ps"])
    return Segment("ramp", data["start_K"], data["end_K"], data.get("ps"), data.get("rate_K_per_ps"))


@dataclass(frozen=True)
class Schedule:
    """A sequence of segments; ``+`` concatenates and refuses a temperature jump."""

    segments: tuple

    def __post_init__(self):
        segments = tuple(self.segments)
        if not segments or not all(isinstance(s, Segment) for s in segments):
            raise InputError("a schedule needs at least one segment")
        for before, after in zip(segments, segments[1:]):
            if before.end_K != after.start_K:
                raise InputError(f"temperature jump: a segment ends at {before.end_K} K and the next starts at "
                                 f"{after.start_K} K")
        object.__setattr__(self, "segments", segments)

    def __add__(self, other):
        if not isinstance(other, Schedule):
            return NotImplemented
        return Schedule(self.segments + other.segments)

    @property
    def duration_ps(self) -> float:
        """The requested duration (before rounding)."""
        return sum(s.duration_ps for s in self.segments)

    def resolve(self, timestep_fs) -> ResolvedSchedule:
        """Whole steps at ``timestep_fs``."""
        return ResolvedSchedule(self, timestep_fs)

    def to_data(self) -> list:
        return [s.to_data() for s in self.segments]

    @classmethod
    def from_data(cls, segments) -> Schedule:
        if isinstance(segments, (str, bytes, Mapping)) or not isinstance(segments, Iterable):
            raise InputError(f"segments must be a list, got {segments!r}")
        return cls(tuple(segment_from_data(s) for s in segments))


def ramp(start_K, end_K, *, ps=None, rate_K_per_ps=None) -> Schedule:
    """A linear ramp from ``start_K`` to ``end_K``, over ``ps`` or at ``rate_K_per_ps`` (signed)."""
    return Schedule((Segment("ramp", start_K, end_K, ps, rate_K_per_ps),))


def hold(temperature_K, *, ps) -> Schedule:
    """``temperature_K`` for ``ps``."""
    return Schedule((Segment("hold", temperature_K, temperature_K, ps),))


def _whole_steps(duration_ps, timestep_fs) -> int:
    """Half up (``floor(x + 0.5)``), not Python's half to even."""
    steps = math.floor(duration_ps * 1000 / timestep_fs + 0.5)
    if steps < 1:
        raise InputError(f"a segment of {duration_ps:g} ps rounds to 0 steps at {timestep_fs:g} fs")
    return steps


@dataclass(frozen=True)
class ResolvedSchedule:
    """A schedule at a timestep: steps per segment, boundaries ``(0, end_1, ..., total)``, targets."""

    schedule: Schedule
    timestep_fs: float
    segment_steps: tuple = field(init=False)
    boundaries: tuple = field(init=False, compare=False)

    def __post_init__(self):
        timestep = _positive(self.timestep_fs, "timestep_fs")
        object.__setattr__(self, "timestep_fs", timestep)
        steps = tuple(_whole_steps(s.duration_ps, timestep) for s in self.schedule.segments)
        object.__setattr__(self, "segment_steps", steps)
        boundaries = [0]
        for n in steps:
            boundaries.append(boundaries[-1] + n)
        object.__setattr__(self, "boundaries", tuple(boundaries))

    @property
    def total_steps(self) -> int:
        return self.boundaries[-1]

    @property
    def durations_ps(self) -> tuple:
        """The rounded durations."""
        return tuple(n * self.timestep_fs / 1000 for n in self.segment_steps)

    @property
    def rates_K_per_ps(self) -> tuple:
        """The rates after rounding (0 for holds)."""
        return tuple((s.end_K - s.start_K) / d for s, d in zip(self.schedule.segments, self.durations_ps))

    def _check(self, step) -> int:
        step = _count(step, "step")
        if not 0 <= step <= self.total_steps:
            raise InputError(f"step {step} is outside the schedule (0 to {self.total_steps})")
        return step

    def _segment(self, step) -> int:
        """Index of the segment whose steps (start, end] contain ``step``; step 0 is in the first."""
        return max(bisect.bisect_left(self.boundaries, step) - 1, 0)

    def target(self, step) -> float:
        """The thermostat target for step ``step`` (its end point); step 0 is the start temperature."""
        step = self._check(step)
        index = self._segment(step)
        segment = self.schedule.segments[index]
        k, n = step - self.boundaries[index], self.segment_steps[index]
        t0, t1 = segment.start_K, segment.end_K
        if t0 <= t1:
            return t0 + (t1 - t0) * k / n
        return t1 + (t0 - t1) * (n - k) / n

    def phase(self, step) -> str:
        """``heating``, ``hold`` or ``cooling``; a boundary step belongs to the segment it ends."""
        return self.schedule.segments[self._segment(self._check(step))].phase

    def next_boundary(self, step) -> int:
        """The first segment boundary after ``step``."""
        step = self._check(step)
        return next(b for b in self.boundaries if b > step) if step < self.total_steps else self.total_steps

    def targets(self, first, last) -> list:
        """The targets of steps ``first`` to ``last`` inclusive."""
        return [self.target(s) for s in range(self._check(first), self._check(last) + 1)]

    def _extreme(self, first, last, pick) -> float:
        first, last = self._check(first), self._check(last)
        if last < first:
            raise InputError(f"empty step range {first} to {last}")
        # The per-step target is monotonic within a segment, so the extremes are at the range's ends or at
        # segment boundaries inside it.
        inner = (b for b in self.boundaries if first < b < last)
        return pick(self.target(s) for s in (first, last, *inner))

    def max_target(self, first, last) -> float:
        """The highest target of steps ``first`` to ``last`` inclusive."""
        return self._extreme(first, last, max)

    def min_target(self, first, last) -> float:
        """The lowest target of steps ``first`` to ``last`` inclusive."""
        return self._extreme(first, last, min)

    def output_steps(self, interval) -> list:
        """Step 0, every ``interval`` steps and every segment boundary."""
        interval = _count(interval, "interval")
        if interval < 1:
            raise InputError(f"interval must be positive, got {interval}")
        steps = set(self.boundaries)
        steps.update(range(interval, self.total_steps + 1, interval))
        return sorted(steps)

    def record(self) -> dict:
        """For provenance and the run report: requested and rounded durations and rates, boundaries."""
        segments = []
        for segment, steps, ps, rate in zip(self.schedule.segments, self.segment_steps, self.durations_ps,
                                            self.rates_K_per_ps):
            segments.append({"kind": segment.kind, "phase": segment.phase, "start_K": segment.start_K,
                             "end_K": segment.end_K, "requested_ps": segment.ps,
                             "requested_rate_K_per_ps": segment.rate_K_per_ps, "steps": steps, "ps": ps,
                             "rate_K_per_ps": rate})
        return {"timestep_fs": self.timestep_fs, "total_steps": self.total_steps,
                "boundaries": list(self.boundaries), "target_update": "every step on ramps, end-point target",
                "rounding": "half up to whole steps", "segments": segments}


class ScheduleState:
    """The schedule position: what a restart stores. ``step`` counts the schedule's steps done (0 to
    ``total_steps``), not the simulation's step."""

    def __init__(self, schedule, timestep_fs, step=0):
        if not isinstance(schedule, Schedule):
            raise InputError(f"schedule must be a Schedule, got {type(schedule).__name__}")
        self.schedule = schedule
        self.resolved = schedule.resolve(timestep_fs)
        self.timestep_fs = self.resolved.timestep_fs
        self.step = self.resolved._check(step)

    @property
    def total_steps(self) -> int:
        return self.resolved.total_steps

    @property
    def remaining(self) -> int:
        return self.total_steps - self.step

    @property
    def finished(self) -> bool:
        return self.remaining == 0

    @property
    def target_K(self) -> float:
        """The target of the current (last completed) step."""
        return self.resolved.target(self.step)

    def steps_to_run(self, steps=None) -> int:
        """The steps a ``run(steps=...)`` takes: all that remain for ``None``. Raises before any step for a
        finished schedule or ``steps`` beyond the remainder; never truncates."""
        if self.finished:
            raise InputError("the schedule is finished and has no remaining steps", next_step="Pass a new schedule=.")
        if steps is None:
            return self.remaining
        steps = _count(steps, "steps")
        if steps < 1:
            raise InputError(f"steps must be positive, got {steps}")
        if steps > self.remaining:
            raise InputError(f"steps={steps} is beyond the schedule: {self.remaining} of its {self.total_steps} "
                             "steps remain")
        return steps

    def advance(self, steps) -> None:
        """Record ``steps`` completed steps."""
        self.step += self.steps_to_run(steps)

    def to_restart(self) -> dict:
        """JSON-safe: the segments (with their rounded steps), the timestep, the position, the target."""
        segments = [{**s.to_data(), "steps": n}
                    for s, n in zip(self.schedule.segments, self.resolved.segment_steps)]
        return {"segments": segments, "timestep_fs": self.timestep_fs, "step": self.step, "target_K": self.target_K}

    @classmethod
    def from_restart(cls, data) -> ScheduleState:
        """The inverse of ``to_restart``; refuses a record whose steps or target do not match."""
        segments = [dict(s) for s in data["segments"]]
        stored_steps = [s.pop("steps", None) for s in segments]
        state = cls(Schedule.from_data(segments), data["timestep_fs"], data["step"])
        if stored_steps != list(state.resolved.segment_steps):
            raise InputError(f"restart schedule: stored segment steps {stored_steps} differ from the resolved "
                             f"{list(state.resolved.segment_steps)}")
        if data["target_K"] != state.target_K:
            raise InputError(f"restart schedule: stored target {data['target_K']} K differs from "
                             f"{state.target_K} K at step {state.step}")
        return state

    def __repr__(self):
        return (f"ScheduleState(step={self.step}/{self.total_steps}, target_K={self.target_K:g}, "
                f"timestep_fs={self.timestep_fs:g})")


# ------------------------------------------------------------------------------------------------- profiles

QUENCH_KEYS = ("min_K", "bin_K", "per_bin", "fmax", "optimizer", "max_steps")
_PROFILE_KEYS = {"name", "segments", "sample_interval", "trajectory_interval", "relax_fmax", "quench", "ensemble",
                 "pressure_GPa"}


def _interval(value, name) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InputError(f"{name} must be a positive int, got {value!r}")
    return value


def _nonnegative(value, name) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise InputError(f"{name} must be finite and at least 0, got {value!r}")
    return float(value)


def _quench(data) -> dict:
    if not isinstance(data, Mapping) or set(data) != set(QUENCH_KEYS):
        raise InputError(f"quench needs exactly the keys {QUENCH_KEYS}, got {data!r}")
    quench = {key: _nonnegative(data[key], f"quench {key}") for key in ("min_K", "bin_K", "fmax")}
    if quench["bin_K"] <= 0 or quench["fmax"] <= 0:
        raise InputError("quench bin_K and fmax must be positive")
    quench["per_bin"] = _interval(data["per_bin"], "quench per_bin")
    quench["max_steps"] = _interval(data["max_steps"], "quench max_steps")
    if not isinstance(data["optimizer"], str) or not data["optimizer"]:
        raise InputError(f"quench optimizer must be a name, got {data['optimizer']!r}")
    quench["optimizer"] = data["optimizer"]
    return {key: quench[key] for key in QUENCH_KEYS}


@dataclass(frozen=True, eq=True)
class Profile:
    """A named schedule with its output intervals, initial relaxation and quench settings.

    ``relax_fmax`` 0 means no initial relaxation (eV/A). ``quench`` is ``None`` or a mapping with ``QUENCH_KEYS``
    (frames per ``bin_K`` bin of the target from ``min_K``, quenched to ``fmax`` with ``optimizer``, at most
    ``max_steps``). ``ensemble`` is ``"NVT"`` or ``"NPT"`` (``lm.md``'s; any case). ``pressure_GPa`` is NPT's
    constant target: ``None`` for NVT, 0 GPa by default for NPT; a pressure schedule is refused. A run file or
    ``loupmd md --profile`` runs the profile in its ensemble; ``lm.md(structure, model, **profile.md_options())``
    does the same from Python.
    """

    name: str
    schedule: Schedule
    sample_interval: int = 100
    trajectory_interval: int = 100
    relax_fmax: float = 0.0
    quench: Mapping | None = None
    ensemble: str = "NVT"
    pressure_GPa: float | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise InputError(f"a profile needs a name, got {self.name!r}")
        if not isinstance(self.schedule, Schedule):
            raise InputError(f"schedule must be a Schedule, got {type(self.schedule).__name__}")
        _interval(self.sample_interval, "sample_interval")
        _interval(self.trajectory_interval, "trajectory_interval")
        object.__setattr__(self, "relax_fmax", _nonnegative(self.relax_fmax, "relax_fmax"))
        if self.quench is not None:
            object.__setattr__(self, "quench", MappingProxyType(_quench(self.quench)))
        if not isinstance(self.ensemble, str) or self.ensemble.upper() not in ("NVT", "NPT"):
            raise InputError(f"ensemble must be 'NVT' or 'NPT', got {self.ensemble!r}")
        object.__setattr__(self, "ensemble", self.ensemble.upper())
        object.__setattr__(self, "pressure_GPa", _pressure(self.pressure_GPa, self.ensemble, self.name))

    def __hash__(self):
        return hash((self.name, self.schedule))

    def md_options(self) -> dict:
        """``lm.md``'s schedule, ensemble and pressure arguments of this profile."""
        options = {"schedule": self.schedule, "ensemble": self.ensemble}
        if self.ensemble == "NPT":
            options["pressure_GPa"] = self.pressure_GPa
        return options


def _pressure(value, ensemble, name):
    if isinstance(value, (list, tuple, Mapping)):
        raise InputError("pressure_GPa takes a constant; pressure schedules are not supported")
    if ensemble != "NPT":
        if value is not None:
            raise InputError(f"profile {name!r}: pressure_GPa={value!r} needs ensemble 'NPT', and the ensemble is "
                             f"{ensemble!r}")
        return None
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f"profile {name!r}: pressure_GPa must be a finite number of GPa, got {value!r}")
    return float(value)


def _research_profile(name, heat_ps, cool_ps, peak_K=400.0, final_K=0.0, interval=100, relax_fmax=0.0, quench=None):
    return Profile(name, ramp(0.0, peak_K, ps=heat_ps) + ramp(peak_K, final_K, ps=cool_ps),
                   sample_interval=interval, trajectory_interval=interval, relax_fmax=relax_fmax, quench=quench)


# slow, fast and ultrafast: 0 -> 400 -> 0 K with the 1:8 heating / cooling ratio. anneal: 0 -> 1000 K in 20 ps,
# then 1000 -> 250 K over 250 ps (3 K/ps), every 20th step saved, a tight initial relaxation and a quench.
PROFILES = MappingProxyType({
    "slow": _research_profile("slow", 30.0, 240.0),
    "fast": _research_profile("fast", 3.0, 24.0),
    "ultrafast": _research_profile("ultrafast", 1.0, 8.0),
    "anneal": _research_profile("anneal", 20.0, 250.0, peak_K=1000.0, final_K=250.0, interval=20, relax_fmax=0.01,
                                quench={"min_K": 500.0, "bin_K": 100.0, "per_bin": 2, "fmax": 0.01,
                                        "optimizer": "gpu-LBFGS", "max_steps": 5000}),
})


def profile_from_data(data) -> Profile:
    """A profile from a mapping: ``name``, ``segments`` (``Schedule.from_data``) and optional ``sample_interval``,
    ``trajectory_interval``, ``relax_fmax``, ``quench``, ``ensemble``, ``pressure_GPa``. Unknown keys are refused
    by name."""
    if not isinstance(data, Mapping):
        raise InputError(f"a profile must be a mapping, got {type(data).__name__}")
    unknown = set(data) - _PROFILE_KEYS
    if unknown:
        raise InputError(f"unknown profile keys {sorted(unknown)}", next_step=f"Known: {sorted(_PROFILE_KEYS)}.")
    if "name" not in data or "segments" not in data:
        raise InputError("a profile needs name and segments")
    options = {key: data[key] for key in data if key not in ("name", "segments")}
    return Profile(data["name"], Schedule.from_data(data["segments"]), **options)


def find_profile(name) -> Profile:
    """A shipped profile by its name, else the profile of a ``.toml`` file."""
    return PROFILES.get(name) or load_profile(name)


def load_profile(path) -> Profile:
    """A profile from a ``.toml`` file."""
    path = Path(path)
    if path.suffix.lower() != ".toml":
        raise InputError(f"profile files are .toml, got {path.name}")
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    with path.open("rb") as handle:
        return profile_from_data(tomllib.load(handle))
