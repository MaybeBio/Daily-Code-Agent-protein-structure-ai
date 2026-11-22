"""Quench of a finished run: pick trajectory frames per target-temperature bin and relax each to its minimum.

Ported from FastMACE (``fastmace/protocols/quench.py``): the same selection (the thermostat's target temperature;
each ramp separately; evenly spaced within each bin; plus the final frame), the same settings (``min_K``,
``bin_K``, ``per_bin``, ``fmax``, ``optimizer``, ``max_steps``) and the same files in ``<run>/quench/``:
``settings.json`` (written first; an interrupted quench continues only with the same settings), ``captured.traj``
(the picked MD frames), ``quenched.traj`` (their minima), ``quench.csv`` (one row per frame, written after every
frame) and ``quench.json`` (settings and summary, written last: a quench with it is complete).

Each frame is relaxed at fixed cell with ``lm.optimize`` (LBFGS on the GPU where the engine offers it, FIRE on the host).
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import time
from pathlib import Path

from . import optimize, provenance
from . import output as _output
from .errors import InputError
from .protocols import QUENCH_KEYS, Schedule

QUENCH_DIRECTORY = "quench"
CAPTURED, QUENCHED, ROWS, SUMMARY, SETTINGS = "captured.traj", "quenched.traj", "quench.csv", "quench.json", \
    "settings.json"
ROW_FIELDS = ("phase", "bin", "frame", "step", "time_ps", "target_K", "md_temperature_K", "md_potential_eV_atom",
              "singlepoint_eV_atom", "quenched_eV_atom", "converged", "optimizer_steps", "seconds", "fmax_eV_A",
              "volume_A3_atom")
SELECTION = "thermostat target temperature; each ramp separately; evenly spaced within each bin; plus the final frame"
DEFAULTS = {"min_K": 500.0, "bin_K": 100.0, "per_bin": 2, "fmax": 0.01, "optimizer": "gpu-LBFGS", "max_steps": 5000}
# FastMACE's optimiser names: here every LBFGS name runs lm.optimize.LBFGS (on the GPU where the engine offers it).
OPTIMIZERS = {"gpu-LBFGS": optimize.LBFGS, "ase-LBFGS": optimize.LBFGS, "LBFGS": optimize.LBFGS,
              "gpu-FIRE": optimize.FIRE, "FIRE": optimize.FIRE}


def select_frames(frames, min_K, bin_K, per_bin, peak_K) -> list:
    """Pick ``per_bin`` frames per ``bin_K`` target-temperature bin from ``min_K`` up, on each ramp.

    ``frames``: dicts with ``step``, ``target_K`` and ``phase`` (``heating`` / ``cooling``), in step order. Within
    a bin the picks sit at the fractions (j + 1/2) / per_bin of the bin's step range (nearest saved frame).
    Returns the chosen frame dicts with a ``bin`` label, in step order.
    """
    chosen = {}
    bins = max(1, math.ceil((peak_K - min_K) / bin_K - 1e-9))
    for phase in ("heating", "cooling"):
        for k in range(bins):
            low, high = min_K + k * bin_K, min(min_K + (k + 1) * bin_K, peak_K)
            members = [f for f in frames if f["phase"] == phase and low - 1e-9 <= f["target_K"]
                       and (f["target_K"] < high - 1e-9 or (k == bins - 1 and f["target_K"] <= high + 1e-9))]
            if not members:
                continue
            first, last = members[0]["step"], members[-1]["step"]
            for j in range(per_bin):
                goal = first + (j + 0.5) / per_bin * (last - first)
                free = [f for f in members if f["step"] not in chosen]
                if not free:
                    break
                pick = min(free, key=lambda f: abs(f["step"] - goal))
                chosen[pick["step"]] = dict(pick, bin=f"{low:g}-{high:g} K")
    return [chosen[s] for s in sorted(chosen)]


def frame_table(resolved, frame_every) -> list:
    """The frames a run along ``resolved`` wrote: step 0, every ``frame_every`` steps and every segment end."""
    return [{"index": index, "step": step, "phase": resolved.phase(step), "target_K": resolved.target(step)}
            for index, step in enumerate(resolved.output_steps(frame_every))]


def picks(resolved, frame_every, settings) -> list:
    """The frames a quench relaxes: ``select_frames``, then the final frame (always)."""
    frames = frame_table(resolved, frame_every)
    peak = resolved.max_target(0, resolved.total_steps)
    chosen = select_frames(frames, settings["min_K"], settings["bin_K"], settings["per_bin"], peak)
    return chosen + [dict(frames[-1], phase="final", bin="final")]


def check_settings(settings) -> dict:
    if not isinstance(settings, dict) or set(settings) != set(QUENCH_KEYS):
        raise InputError(f"quench settings need exactly the keys {QUENCH_KEYS}, got {sorted(settings)}")
    if settings["optimizer"] not in OPTIMIZERS:
        raise InputError(f"quench optimizer {settings['optimizer']!r} is not in this version",
                         next_step=f"Optimisers: {', '.join(OPTIMIZERS)}.")
    for key in ("min_K", "bin_K", "fmax"):
        value = settings[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise InputError(f"quench {key} must be finite and at least 0, got {value!r}")
    if settings["bin_K"] <= 0 or settings["fmax"] <= 0:
        raise InputError("quench bin_K and fmax must be positive")
    for key in ("per_bin", "max_steps"):
        if isinstance(settings[key], bool) or not isinstance(settings[key], int) or settings[key] < 1:
            raise InputError(f"quench {key} must be a positive int, got {settings[key]!r}")
    return dict(settings)


def _read_rows(path) -> list:
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ROW_FIELDS:
            if key in ("phase", "bin"):
                continue
            row[key] = (row[key] == "True") if key == "converged" else (
                int(row[key]) if key in ("frame", "step", "optimizer_steps") else float(row[key]))
    return rows


def _write_rows(path, rows):
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows, phase):
    values = [r["quenched_eV_atom"] for r in rows if r["phase"] == phase]
    if not values:
        return None
    return {"frames": len(values), "min_eV_atom": min(values), "max_eV_atom": max(values),
            "mean_eV_atom": statistics.fmean(values)}


def quench_run(directory, force_field, settings=None, *, name=QUENCH_DIRECTORY, log=print) -> dict:
    """Quench the picked frames of the finished run in ``directory`` and return the summary.

    The run must have been made by ``lm.md`` / ``loupmd md`` with a schedule and a trajectory, and be complete
    (``metadata.json`` holds the schedule). ``settings``: the six quench keys (default: the run's profile's, else
    FastMACE's defaults). A complete quench is returned as it is; an interrupted one continues after its last row.
    """
    from ase.io.trajectory import Trajectory

    directory = Path(directory)
    record = directory / provenance.METADATA_NAME
    if not record.is_file():
        raise InputError(f"{directory} has no {provenance.METADATA_NAME}: not a finished run of lm.md")
    metadata = json.loads(record.read_text())
    arguments = metadata.get("arguments") or {}
    schedule_data = arguments.get("schedule")
    frame_every = (metadata.get("output") or {}).get("trajectory_every")
    if not schedule_data or not frame_every:
        raise InputError(f"the run in {directory} has no temperature schedule or no trajectory, so there are no "
                         "frames to pick by target temperature",
                         next_step="Quench a run made with a schedule or a profile (for example --profile anneal).")
    timestep = metadata["integrator"]["timestep_fs"]
    resolved = Schedule.from_data(schedule_data).resolve(timestep)
    if metadata["step"] != resolved.total_steps:
        raise InputError(f"the run in {directory} is at step {metadata['step']} of its schedule's "
                         f"{resolved.total_steps}", next_step="Finish it first: loupmd run --resume DIR.")
    settings = check_settings(dict(DEFAULTS) if settings is None else dict(settings))
    out = directory / name
    if (out / SUMMARY).is_file():
        return json.loads((out / SUMMARY).read_text())
    out.mkdir(exist_ok=True)
    chosen = picks(resolved, frame_every, settings)
    frames = _output.read_frames(directory)
    expected = len(resolved.output_steps(frame_every))
    if len(frames) != expected:
        raise InputError(f"{directory} holds {len(frames)} trajectory frames, and its schedule with a frame every "
                         f"{frame_every} steps gives {expected}")
    header, thermo_rows = _output.read_thermo(directory)
    thermo = {int(row[0]): dict(zip(header, row)) for row in thermo_rows}
    stored = out / SETTINGS
    if stored.is_file() and json.loads(stored.read_text()) != settings:
        raise InputError(f"{out} holds an unfinished quench with other settings",
                         next_step="Continue it with its own settings, or give this quench another --name.")
    stored.write_text(json.dumps(settings, indent=2) + "\n")
    rows = _read_rows(out / ROWS) if (out / ROWS).is_file() else []
    if len(rows) > len(chosen) or any(row["frame"] != pick["index"] for row, pick in zip(rows, chosen)):
        raise InputError(f"{out / ROWS} does not belong to this run's picks")
    for trajectory in (CAPTURED, QUENCHED):                  # keep exactly the frames the rows stand for
        path = out / trajectory
        if path.is_file():
            with Trajectory(str(path)) as handle:
                kept = [handle[i] for i in range(min(len(handle), len(rows)))]
            with Trajectory(str(path), "w") as handle:
                for frame in kept:
                    handle.write(frame)
    if rows:
        log(f"quench: continuing after {len(rows)} of {len(chosen)} frames")
    optimizer = OPTIMIZERS[settings["optimizer"]]()
    started = time.perf_counter()
    for number, pick in enumerate(chosen[len(rows):], len(rows) + 1):
        atoms = frames[pick["index"]].copy()
        md_energy = frames[pick["index"]].get_potential_energy() / len(atoms)
        atoms.calc = None
        began = time.perf_counter()
        result = optimize.relax(force_field, atoms, optimizer, fmax=settings["fmax"], steps=settings["max_steps"],
                                dispersion=arguments.get("dispersion"))      # the run's D3 term, as FastMACE
        seconds = time.perf_counter() - began
        for trajectory, frame in ((CAPTURED, atoms), (QUENCHED, result.atoms)):
            path = out / trajectory
            with Trajectory(str(path), "a" if path.is_file() else "w") as handle:
                handle.write(frame)
        sample = thermo.get(pick["step"])
        rows.append({"phase": pick["phase"], "bin": pick["bin"], "frame": pick["index"], "step": pick["step"],
                     "time_ps": pick["step"] * timestep / 1000, "target_K": pick["target_K"],
                     "md_temperature_K": float(sample["temperature_K"]) if sample else math.nan,
                     "md_potential_eV_atom": float(sample["potential_eV_atom"]) if sample else md_energy,
                     "singlepoint_eV_atom": md_energy, "quenched_eV_atom": result.energy / len(atoms),
                     "converged": result.converged, "optimizer_steps": result.steps, "seconds": seconds,
                     "fmax_eV_A": result.max_force, "volume_A3_atom": atoms.get_volume() / len(atoms)})
        _write_rows(out / ROWS, rows)
        log(f"quench {number}/{len(chosen)}: {pick['phase']} {pick['target_K']:.0f} K -> "
            f"{rows[-1]['quenched_eV_atom']:.6f} eV/atom in {result.steps} steps ({seconds:.1f} s)"
            f"{'' if result.converged else ' NOT CONVERGED'}")
    summary = {"settings": {**settings, "fixed_cell": True, "cell": "frame", "selection": SELECTION},
               "frames": len(rows), "frame_every": int(frame_every), "trajectory_frames": len(frames),
               "quench_wall_s": time.perf_counter() - started, "quench_seconds_sum": sum(r["seconds"] for r in rows),
               "not_converged": sum(not r["converged"] for r in rows),
               "heating": _summary(rows, "heating"), "cooling": _summary(rows, "cooling"),
               "final_quenched_eV_atom": rows[-1]["quenched_eV_atom"]}
    (out / SUMMARY).write_text(json.dumps(summary, indent=2) + "\n")
    return summary
