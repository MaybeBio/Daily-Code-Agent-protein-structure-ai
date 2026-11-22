"""Benchmarking LoupMD on your own machine (``loupmd bench``, PLAN.md section 8)."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .. import _gpu
from ..errors import InputError, LoupError
from . import compare, protocol, reference, suites
from .protocol import PROTOCOLS, Protocol, Row, format_table, make_record, validate_record  # noqa: F401

AB_SCHEMA = "loupmd.bench-ab/1"
# Above this utilisation, with no process listed (WSL lists none), the GPU counts as in use.
BUSY_PERCENT = 20


def _nvidia_smi():
    return _gpu.nvidia_smi()


def _query(*args):
    exe = _nvidia_smi()
    if exe is None:
        return None
    try:
        done = subprocess.run([exe, *args, "--format=csv,noheader,nounits" if "utilization" in args[0] else
                               "--format=csv,noheader"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def gpu_processes(device=0):
    """Compute processes on the GPU now, as ``[{"pid": int, "name": str, "memory": str}]`` (nvidia-smi)."""
    out = []
    for line in (_query("--query-compute-apps=pid,process_name,used_memory", "-i", str(device)) or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0].isdigit():
            out.append({"pid": int(parts[0]), "name": parts[1], "memory": parts[2]})
    return out


def gpu_utilisation(device=0):
    """The GPU's utilisation in percent: the lowest of three readings 0.3 s apart, ``None`` when there is none."""
    readings = []
    for sample in range(3):
        if sample:
            time.sleep(0.3)
        text = (_query("--query-gpu=utilization.gpu", "-i", str(device)) or "").strip().split("\n")[0].strip()
        if text.isdigit():
            readings.append(int(text))
    return min(readings) if readings else None


def gpu_description(device=0):
    """``{"name", "compute_capability", "driver"}`` of the GPU (nvidia-smi), with ``None`` where unknown."""
    parts = [p.strip() for p in (_query("--query-gpu=name,compute_cap,driver_version", "-i", str(device)) or "")
             .strip().split(",")]
    if len(parts) < 3:
        return {"name": None, "compute_capability": None, "driver": None}
    return {"name": parts[0], "compute_capability": parts[1], "driver": parts[2]}


def check_gpu_is_free(force=False, device=0):
    """Refuse to time on a GPU that is in use. Returns ``(other processes, utilisation in percent)``; with
    ``force`` a busy GPU is not refused and both go into the record."""
    own = os.getpid()
    others = [p for p in gpu_processes(device) if p["pid"] != own]
    utilisation = gpu_utilisation(device)
    if not force:
        way_out = "Wait until it is idle, or pass --force to time anyway (the record then says what was there)."
        if others:
            listing = ", ".join(f"{p['name']} (pid {p['pid']}, {p['memory']})" for p in others)
            raise LoupError(f"the GPU is in use by {len(others)} other process(es): {listing}",
                            why="a timing taken beside other work on the card says nothing", next_step=way_out)
        if utilisation is not None and utilisation > BUSY_PERCENT:
            raise LoupError(f"the GPU is in use: {utilisation} % utilised before the benchmark started",
                            why="nvidia-smi lists no process for it (under WSL it never does), and a timing taken "
                                "beside other work on the card says nothing", next_step=way_out)
    return others, utilisation


def run_suite(model, suite="standard", protocol_name=None, head=None, checkpoint=None, sha256=None, trusted=False,
              download=False, systems=None, device=0, force=False, compare_with=(), engine_factory=None,
              ensure_bundle=None, environ=None):
    """Time every system of ``suite`` with ``model`` (a label, a checkpoint path or a URL) and return
    ``(record, rows)``.

    The order of the refusals: protocol, checkpoint trust, structures, busy GPU; nothing is exported or run before
    all four passed. ``engine_factory(bundle, device_id=)`` and ``ensure_bundle(path, numbers, head=, environ=)``
    replace the engine and the exporter (the tests use them).
    """
    from .. import __version__
    from .. import models as model_table

    proto_key = protocol_name or suites.DEFAULT_PROTOCOL.get(suite, "standard")
    if proto_key not in PROTOCOLS:
        raise InputError(f"unknown protocol {proto_key!r}", next_step=f"Protocols: {', '.join(PROTOCOLS)}.")
    proto = PROTOCOLS[proto_key]
    unknown = [name for name in compare_with if name not in compare.ENGINES]
    if unknown:
        raise InputError(f"unknown comparison {unknown[0]!r}", next_step=f"Comparisons: {', '.join(compare.ENGINES)}.")
    resolved, digest, _ = model_table.trusted_checkpoint(model, head, checkpoint=checkpoint, sha256=sha256,
                                                         trusted=trusted, download=download, environ=environ)
    entry = resolved.label
    use_head = head if head is not None else (entry.head if entry is not None else None)
    chosen = suites.systems_of(suite, family=entry.family if entry is not None else None, systems=systems,
                               environ=environ)
    others, utilisation = check_gpu_is_free(force, device)
    if ensure_bundle is None:
        from .. import bundles

        ensure_bundle = bundles.ensure_bundle
    if engine_factory is None:
        from .. import _core

        engine_factory, library = _core.LoupEngine, _core.library_version()
    else:
        library = "(engine replaced)"
    rows, comparisons = [], []
    for name, atoms in chosen:
        bundle = ensure_bundle(resolved.path, sorted(set(atoms.get_atomic_numbers().tolist())), head=use_head,
                               environ=environ)
        engine = engine_factory(bundle, device_id=device)
        rows.append(protocol.time_system(engine, name, atoms, proto, bundle=Path(bundle).name))
        del engine                                           # its memory is free before a comparison loads a model
        for other in compare_with:
            comparisons.append(compare.run(other, resolved.path, name, atoms, proto, head=use_head, device=device,
                                           loupmd_ms=rows[-1].ms_per_step))
    record = make_record(rows, proto, "custom" if systems else suite, gpu_description(device),
                         {"label": entry.label if entry is not None else None, "file": resolved.path.name,
                          "sha256": digest, "head": use_head},
                         library, __version__, other_gpu_processes=others, gpu_utilisation_percent=utilisation,
                         device=device)
    if comparisons:
        record["comparisons"] = comparisons
    return record, rows


# ------------------------------------------------------------------------------------------------------ A/B

def _side_environment(side, environ):
    env = dict(environ)
    if side != "-":
        for pair in side.split(","):
            key, sep, value = pair.partition("=")
            if not sep or not key:
                raise InputError(f"--ab side {side!r} is not ENV=VAL[,ENV=VAL...] (or - for no change)")
            env[key] = value
    return env


def run_ab(sides, argv, environ=None):
    """``--ab``: the same benchmark once per side in a fresh process each, in the order a b b a, so drift and the
    build order are both covered (as ``bench_md.py``). A side is ``ENV=VAL[,ENV=VAL...]``, or ``-`` for the
    environment as it is. Returns the ``loupmd.bench-ab/1`` record: every run's record, the mean ms/step per side
    and system, and each mean's ratio to the first side's."""
    environ = dict(os.environ if environ is None else environ)
    package_parent = str(Path(__file__).resolve().parents[2])
    environ["PYTHONPATH"] = os.pathsep.join(p for p in (package_parent, environ.get("PYTHONPATH")) if p)
    environments = {side: _side_environment(side, environ) for side in sides}      # every side is checked first
    order = list(sides) + list(reversed(sides))
    runs = []
    with tempfile.TemporaryDirectory(prefix="loupmd-bench-") as scratch:
        for index, side in enumerate(order):
            target = os.path.join(scratch, f"run{index}.json")
            done = subprocess.run([sys.executable, "-m", "loupmd", "bench", *argv, "--json", target],
                                  env=environments[side], capture_output=True, text=True)
            if done.returncode != 0:
                raise LoupError(f"the benchmark of side {side!r} failed",
                                why=(done.stderr or done.stdout or "").strip()[-800:] or
                                f"it ended with status {done.returncode}")
            with open(target) as handle:
                runs.append({"side": side, "record": json.load(handle)})
    mean = {}
    for side in sides:
        per_system = {}
        for run in runs:
            if run["side"] == side:
                for row in run["record"]["rows"]:
                    per_system.setdefault(row["system"], []).append(row["ms_per_step"])
        mean[side] = {system: statistics.mean(values) for system, values in per_system.items()}
    first = mean[sides[0]]
    ratio = {side: {system: value / first[system] for system, value in mean[side].items() if first.get(system)}
             for side in sides}
    return {"schema": AB_SCHEMA, "order": order, "runs": runs, "mean_ms": mean, "ratio": ratio}


def format_ab(result) -> str:
    width = max([len(side) for side in result["order"]] + [4])
    lines = []
    for run in result["runs"]:
        cells = "  ".join(f"{row['system']} {row['ms_per_step']:.3f} ms" for row in run["record"]["rows"])
        lines.append(f"{run['side']:{width}s}  {cells}")
    for side, per_system in result["mean_ms"].items():
        cells = "  ".join(f"{system} {ms:.3f} ({result['ratio'][side].get(system, float('nan')):.4f})"
                          for system, ms in per_system.items())
        lines.append(f"MEAN {side:{width}s}  {cells}")
    return "\n".join(lines)


def write_record(record, target):
    """Write a record to a file, or to stdout for ``-``."""
    text = json.dumps(record, indent=2)
    if str(target) == "-":
        print(text)
    else:
        Path(target).write_text(text + "\n")
