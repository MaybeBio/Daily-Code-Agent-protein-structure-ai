"""Run files: the arguments of ``lm.md`` as a TOML file (``loupmd init`` writes one, ``loupmd run`` runs one).

The table of a run file is the ``arguments`` block of ``metadata.json``, so ``loupmd run metadata.json`` repeats a
finished run. Unknown keys are refused by name. A schedule is a list of segments (``[[schedule]]`` tables); a
profile (``profile = "fast"`` or a profile file) gives the schedule and the output cadences, and a profile at
constant pressure also ``ensemble = "NPT"`` and its pressure. ``[integrator]`` chooses an ``lm.integrators``
record by ``type`` (``Langevin``, ``CSVR``, ``NVE``, ``MTK``, ...) with its fields; ``timestep_fs`` and
``temperature_K`` may be left to the keys above it.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import integrators, protocols, quick
from .config import Output, from_mapping
from .errors import InputError

FORMAT = "loupmd.run/1"
# key -> default (None: no default, the key is left out unless given). The order is the file's.
KEYS = {
    "structure": None, "model": None, "head": None, "checkpoint": None, "sha256": None, "trusted": False,
    "download": False, "charge": None, "spin_multiplicity": None, "ensemble": "NVT", "temperature_K": None,
    "pressure_GPa": 0.0, "cell_mode": "hydrostatic",
    "profile": None, "timestep_fs": 0.5, "steps": None, "repeat": [1, 1, 1], "seed": None,
    "initial_velocities": "keep", "check": "skip", "capacity": "auto", "device": 0, "skin": "auto", "mc": None,
    "dispersion": None,
}
TABLES = ("output", "integrator", "schedule")
_COMMENTS = {
    "structure": "the structure file (anything ASE reads)",
    "model": "a label (`loupmd models`), a checkpoint path or a URL",
    "head": "the head of a multi-head model",
    "mc": "Monte Carlo moves: a list of tables with move = swap, transmute or displace and the move's fields",
    "dispersion": 'a preset ("d3bj", "d3bj-mace", ...; `loupmd dispersion list`) or a table with the fields of '
                  'lm.Dispersion',
    "checkpoint": "the file of a label, when it is not in LOUPMD_MODELS or the cache",
    "sha256": "the stated hash of a file that is not in the label table",
    "trusted": "load a file outside the label table without a hash",
    "download": "download a label's checkpoint if it is missing",
    "charge": "total charge (models with a charge embedding)",
    "spin_multiplicity": "2S + 1 (models with a spin embedding)",
    "ensemble": '"NVT", "NVE" or "NPT" (Langevin BAOAB, experimental); [integrator] chooses another integrator',
    "pressure_GPa": 'the target pressure of ensemble "NPT"',
    "cell_mode": 'ensemble "NPT": "hydrostatic" (the cell keeps its shape) or "full"',
    "temperature_K": "the thermostat's target; not with a schedule or a profile",
    "profile": 'a shipped profile ("slow", "fast", "ultrafast", "anneal") or a profile file; gives the schedule '
               'and, for a profile at constant pressure, ensemble "NPT" and its pressure',
    "timestep_fs": "the timestep",
    "steps": "the number of steps; optional with a schedule (the whole schedule)",
    "repeat": "the supercell",
    "seed": "the noise seed; left out: one is drawn and recorded",
    "initial_velocities": '"keep", "maxwell_boltzmann" or a temperature in K, for a structure at rest',
    "check": '"skip", "gate" or "allow_unavailable": the accuracy gate before the first step',
    "capacity": '"auto" (tiles when the cell does not fit the GPU whole; no barostat with a dispersion term), "whole", '
                '"tiled" or '
                '"wavefront"',
    "device": "the GPU index",
    "skin": 'the neighbour-list skin in A, or "auto": chosen from how far the atoms move per step',
}


def _value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):                   # an inline table; TOML has no null, so a None field is left out
        return "{" + ", ".join(f"{k} = {_value(v)}" for k, v in value.items() if v is not None) + "}"
    return json.dumps(str(value))                 # a TOML basic string has JSON's escapes


OFF_WITH_ZERO = ("trajectory_every", "restart_every")   # [output] keys a run file turns off with 0


def to_toml(arguments) -> str:
    """The run file of ``arguments``: every key, those at their default as a comment."""
    check(arguments)
    lines = [f"# LoupMD run file ({FORMAT}): the arguments of `loupmd md`. Run it with `loupmd run FILE`.",
             "# A line that starts with # is a key at its default.", ""]
    for key, default in KEYS.items():
        value = arguments.get(key)
        given = value is not None and value != default
        shown = value if given else default
        text = f"{key} = {_value(shown)}" if shown is not None else f"{key} ="
        lines.append(f"{'' if given else '# '}{text:<40s} # {_COMMENTS[key]}")
    if isinstance(arguments.get("schedule"), str):
        lines.append(f"{'schedule = ' + _value(arguments['schedule']):<40s} # a profile's schedule, not its cadences")
    out = arguments.get("output") or {}
    lines += ["", "[output]"]
    defaults = {"directory": None, "trajectory_every": 20, "thermo_every": 20, "restart_every": 10_000}
    for key, default in defaults.items():
        if key in out and out[key] is None:
            lines.append(f"{key} = 0{'':<{max(1, 23 - len(key))}s}# off (TOML has no none)")
        elif key in out and out[key] != default:
            lines.append(f"{key} = {_value(out[key])}")
        elif default is not None:
            lines.append(f"# {key} = {_value(default)}")
        else:
            lines.append("# directory =                  # default: <structure stem>.loupmd")
    lines += ["", "# [integrator]                           # default: Langevin for NVT, velocity Verlet for NVE",
              '# type = "CSVR"                          # "Langevin" (friction_per_fs), "CSVR" (tau_fs) or "NVE"',
              "# tau_fs = 100.0"] if not arguments.get("integrator") else ["", "[integrator]"] + [
                  f"{key} = {_value(value)}" for key, value in arguments["integrator"].items()]
    for segment in (arguments.get("schedule") if isinstance(arguments.get("schedule"), list) else []):
        lines += ["", "[[schedule]]"] + [f"{key} = {_value(value)}" for key, value in segment.items()]
    return "\n".join(lines) + "\n"


def check(arguments) -> None:
    """Refuse unknown keys by name, all at once."""
    if not isinstance(arguments, dict):
        raise InputError(f"a run file is a table of keys and values, got {type(arguments).__name__}")
    unknown = [key for key in arguments if key not in KEYS and key not in TABLES]
    if unknown:
        raise InputError(f"unknown key{'s' if len(unknown) > 1 else ''} {', '.join(repr(k) for k in unknown)} in "
                         "the run file", next_step=f"Keys: {', '.join(list(KEYS) + list(TABLES))}.")
    if arguments.get("profile") is not None and arguments.get("schedule"):
        raise InputError("profile and [[schedule]] exclude each other: a profile gives the schedule")


def load(path) -> dict:
    """The arguments of a run file (``.toml``) or of a finished run's ``metadata.json``."""
    path = Path(path)
    if not path.is_file():
        raise InputError(f"run file {path} not found")
    if path.suffix.lower() == ".json":
        metadata = json.loads(path.read_text())
        arguments = metadata.get("arguments") if isinstance(metadata, dict) else None
        if not isinstance(arguments, dict):
            raise InputError(f"{path} has no arguments block", why="it was not written by lm.md or loupmd md")
    elif path.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError:  # Python 3.10
            import tomli as tomllib
        with path.open("rb") as handle:
            try:
                arguments = tomllib.load(handle)
            except tomllib.TOMLDecodeError as error:
                raise InputError(f"{path} is not valid TOML", why=str(error)) from None
    else:
        raise InputError(f"a run file is .toml or a metadata.json, got {path.name}")
    check(arguments)
    return arguments


def md_options(arguments) -> tuple:
    """``(structure, keyword arguments)`` for ``lm.md`` from a run file's table."""
    check(arguments)
    for key in ("structure", "model"):
        if not arguments.get(key):
            raise InputError(f"the run file lacks {key}")
    options = {key: arguments[key] for key in KEYS if key not in ("structure", "profile")
               and arguments.get(key) is not None}
    if "repeat" in options:
        options["repeat"] = tuple(options["repeat"])
    out = dict(arguments.get("output") or {})
    profile = arguments.get("profile")
    table = arguments.get("integrator")
    if profile is not None:
        found = protocols.find_profile(profile)
        options["schedule"] = found.schedule
        out.setdefault("thermo_every", found.sample_interval)
        out.setdefault("trajectory_every", found.trajectory_interval)
        if found.ensemble == "NPT":
            table = _npt_profile(found, arguments, options, table)
    elif isinstance(arguments.get("schedule"), str):   # FastMACE's spelling: a profile's schedule alone
        options["schedule"] = protocols.find_profile(arguments["schedule"]).schedule
    elif arguments.get("schedule"):
        options["schedule"] = protocols.Schedule.from_data(arguments["schedule"])
    for key in OFF_WITH_ZERO:              # TOML has no null: 0 turns these files off
        if out.get(key) == 0:
            out[key] = None
    if out:
        out.setdefault("directory", Path(str(arguments["structure"])).stem + quick.OUTPUT_SUFFIX)
        options["output"] = from_mapping(Output, out, section="output")
    if table:
        timestep = arguments.get("timestep_fs", KEYS["timestep_fs"])
        start = arguments.get("temperature_K")
        if start is None and "schedule" in options and isinstance(table, dict):   # the schedule's first target
            start = protocols.ScheduleState(options["schedule"], table.get("timestep_fs", timestep)).target_K
        options["integrator"] = integrators.from_data(table, timestep_fs=timestep, temperature_K=start)
    return arguments["structure"], options


def _npt_profile(found, arguments, options, table):
    """A profile at constant pressure: ``ensemble`` and ``pressure_GPa`` for ``lm.md``. The run file's own
    ``pressure_GPa`` stands before the profile's. With an ``[integrator]`` table the table's barostat runs, at the
    profile's pressure unless the table names one; the table is returned with it."""
    import dataclasses

    asked = arguments.get("ensemble")
    if asked is not None and str(asked).upper() != "NPT":
        raise InputError(f"profile {found.name!r} runs NPT, the run file asks for ensemble={asked!r}",
                         next_step="Drop ensemble, or use a profile at constant volume.")
    options["ensemble"] = "NPT"
    if not table:
        options.setdefault("pressure_GPa", found.pressure_GPa)
        return table
    kind = table.get("type") if isinstance(table, dict) else None
    record = integrators.RECORDS.get(kind)
    if record is not None and "pressure_GPa" not in [field.name for field in dataclasses.fields(record)]:
        raise InputError(f"profile {found.name!r} runs NPT, and [integrator] of type {kind} has no barostat",
                         next_step="Use LangevinBAOAB, MTK or Berendsen with a pressure, or a profile at constant "
                                   "volume.")
    if record is not None and "pressure_GPa" not in table:
        table = dict(table, pressure_GPa=options.pop("pressure_GPa", found.pressure_GPa))
    return table


def run(arguments):
    """Run ``lm.md`` with a run file's table."""
    structure, options = md_options(arguments)
    return quick.md(structure, **options)
