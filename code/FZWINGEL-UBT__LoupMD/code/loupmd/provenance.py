"""``metadata.json``: what a run was, enough to repeat it (schema ``loupmd.metadata/1``).

Code version and git commit, library build, model file with its SHA-256, label and licence, the bundle, the
structure, integrator, schedule, output and seed, the plan (execution mode, kernels, memory), the gate's record,
software versions, the GPU with compute capability and driver, counters and timing, and the arguments of ``lm.md``
when the run came from it (``loupmd run metadata.json`` repeats the run from those).
"""
from __future__ import annotations

import dataclasses
import datetime
import json
import platform
import subprocess
from pathlib import Path

from . import output as _output

SCHEMA = "loupmd.metadata/1"
METADATA_NAME = "metadata.json"
PRECISION = "float32 model evaluation with float64 accumulation of energy, forces and virial; float64 integration"


def git_commit():
    """The commit of a source checkout, or ``None`` for an installed package."""
    root = Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        return None
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def _versions():
    import ase
    import numpy

    return {"python": platform.python_version(), "numpy": numpy.__version__, "ase": ase.__version__,
            "platform": platform.platform()}


def _gpu(device):
    from . import _gpu as probe

    try:
        name, driver, capability = probe.query_gpus()[device]
    except (OSError, ValueError, IndexError):
        return None
    return {"index": device, "name": name, "compute_capability": f"{capability // 10}.{capability % 10}",
            "driver": driver}


def _plan(sim):
    """The execution plan as far as the engine tells it: whole-system execution, the kernel path, the memory."""
    plan = {"execution": "whole", "precision": PRECISION, "kernels": None, "kernel_signature": None,
            "interaction_layers": None, "r_max_A": sim.force_field.r_max_A, "memory": None, "library": None}
    engine = sim._engine
    if engine is None:
        return plan
    execution = getattr(sim, "execution", None) or {}
    if execution.get("mode") in ("tiled", "wavefront"):   # tiles of at most `receivers` atoms (PLAN.md S5-T12)
        requested = getattr(getattr(sim, "capacity", None), "mode", "auto")
        plan.update(execution="tiled", receivers=int(getattr(engine, "receivers", 0) or execution["receivers"]),
                    tiles=int(getattr(engine, "tiles", 0)) or None, integrator_on=getattr(engine, "integrator_on", "host"),
                    wavefront=bool(getattr(engine, "wavefront", False)),
                    requested=requested, tiled_because="asked" if requested in ("tiled", "wavefront") else "memory")
    found = execution.get("plan")
    if found is not None and found.whole_bytes > 0:      # 0: the bundle cannot tile, nothing was measured
        plan["memory"] = {"whole_bytes": int(found.whole_bytes), "free_bytes": int(found.free_bytes),
                          "tiled_global_bytes": int(found.tiled_global_bytes),
                          "tile_workspace_bytes": int(found.tile_workspace_bytes),
                          "host_bytes": int(getattr(found, "host_bytes", 0) or 0),
                          "host_lists": bool(getattr(found, "host_lists", False)),
                          "host_state": bool(getattr(found, "host_state", False))}
    try:
        from . import _core

        inner = getattr(engine, "_eng", engine)               # a TiledEngine's LoupEngine
        plan["library"] = _core.library_version() if isinstance(inner, _core.LoupEngine) else None
    except Exception:  # noqa: BLE001  (a replaced engine has no library)
        pass
    if hasattr(engine, "info"):
        info = engine.info()
        plan.update(kernels="specialised" if info.specialised else "generic",
                    kernel_signature=getattr(info, "kernel_signature", None),
                    interaction_layers=getattr(info, "n_layers", None), r_max_A=getattr(info, "r_max", plan["r_max_A"]))
    if plan["memory"] is None and hasattr(engine, "plan_memory"):
        memory = engine.plan_memory(len(sim._atoms))
        plan["memory"] = {"whole_bytes": int(memory.whole_bytes), "free_bytes": int(memory.free_bytes)}
    return plan


def _dispersion_entry(sim):
    from .simulation import _dispersion_entry as entry

    return entry(sim)


def collect(sim, *, source=None, repeat=None, arguments=None, warnings=()) -> dict:
    """The metadata of ``sim`` as it stands now."""
    from collections import Counter

    from . import __version__

    ff, atoms, totals = sim.force_field, sim._atoms, sim.totals
    steps = totals["steps"]
    timestep = sim.config.timestep_fs
    wall_ms = totals["wall_s"] * 1e3 / steps if steps else None
    schedule = sim._schedule
    return {
        "schema": SCHEMA,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "status": sim.status,
        "loupmd": {"version": __version__, "git_commit": git_commit()},
        "software": _versions(),
        "gpu": _gpu(ff.device),
        "model": {"label": ff.label, "file": ff.path.name, "path": str(ff.path), "sha256": ff.sha256,
                  "head": ff.head, "licence": ff.licence, "functional": ff.functional, "charge": ff.charge,
                  "spin_multiplicity": ff.spin_multiplicity},
        "bundle": Path(sim._bundle).name if getattr(sim, "_bundle", None) else None,
        "structure": {"source": source, "repeat": list(repeat) if repeat else None, "atoms": len(atoms),
                      "elements": dict(sorted(Counter(atoms.get_chemical_symbols()).items())),
                      "fixed_atoms": int(sim._fixed.sum()) if sim._fixed is not None else 0,
                      "cell": [[float(x) for x in row] for row in atoms.cell.array],
                      "pbc": [bool(p) for p in atoms.pbc]},
        "integrator": dataclasses.asdict(sim.config),
        "schedule": schedule.resolved.record() if schedule is not None else None,
        "output": dataclasses.asdict(sim.output) if sim.output is not None else None,
        "seed": sim.seed, "skin_A": sim.skin, "skin": dict(sim.skin_record),
        "plan": _plan(sim),
        "dispersion": _dispersion_entry(sim),
        "gate": sim.gate,
        "step": sim.step,
        "counters": {key: totals[key] for key in ("steps", "rebuilds", "pipelined_steps", "dangerous_builds")},
        "mc": ({"moves": getattr(sim, "mc_moves", None),
                "counters": {k: c.as_dict() for k, c in sim.mc_counters.items()}}
               if getattr(sim, "mc_counters", None) else None),
        "timing": {"setup_s": sim.setup_s, "wall_s": totals["wall_s"], "ms_per_step": wall_ms,
                   "engine_ms_per_step": totals["engine_ms"] / steps if steps else None,
                   "ns_per_day": 86.4 * timestep / wall_ms if wall_ms else None,
                   "atom_steps_per_s": len(atoms) * 1e3 / wall_ms if wall_ms else None},
        "arguments": arguments,
        "warnings": list(warnings),
    }


def write(metadata, directory) -> Path:
    """Write ``metadata.json`` into ``directory`` atomically."""
    text = json.dumps(metadata, indent=2) + "\n"
    return _output.write_atomically(Path(directory) / METADATA_NAME, lambda handle: handle.write(text.encode("utf-8")))


_REQUIRED = {"schema": str, "created": str, "status": str, "loupmd": dict, "software": dict, "model": dict,
             "structure": dict, "integrator": dict, "seed": int, "plan": dict, "gate": dict, "step": int,
             "counters": dict, "timing": dict, "warnings": list}


def validate(metadata) -> list:
    """Problems of a record against ``loupmd.metadata/1``; empty when it is valid."""
    if not isinstance(metadata, dict):
        return ["the record is not an object"]
    problems = [f"missing key {key!r}" if key not in metadata else f"{key!r} is not a {kind.__name__}"
                for key, kind in _REQUIRED.items() if key not in metadata or not isinstance(metadata[key], kind)]
    if metadata.get("schema") != SCHEMA:
        problems.append(f"schema is {metadata.get('schema')!r}, not {SCHEMA!r}")
    for section, keys in (("model", ("label", "file", "sha256", "head", "licence")),
                          ("structure", ("atoms", "elements", "cell", "pbc")),
                          ("plan", ("execution", "precision", "kernels", "memory")),
                          ("timing", ("setup_s", "wall_s", "ms_per_step", "ns_per_day", "atom_steps_per_s")),
                          ("counters", ("steps", "rebuilds", "pipelined_steps", "dangerous_builds")),
                          ("loupmd", ("version", "git_commit")), ("gate", ("status",))):
        for key in keys:
            if key not in (metadata.get(section) if isinstance(metadata.get(section), dict) else {}):
                problems.append(f"{section} lacks {key!r}")
    return problems
