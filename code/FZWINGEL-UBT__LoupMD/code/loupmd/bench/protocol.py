"""The benchmark protocol: how one system is timed, and the record a benchmark writes.

The standard protocol is ``tools/dev/bench_md.py``'s, so numbers stay comparable with the optimisation ledger:
Langevin at 300 K, 1 fs, skin 0.5 A, friction 0.01/fs, velocities from a Maxwell-Boltzmann draw with seed 42, 100
warm-up steps (seed 1), then the median of 6 blocks of 256 steps (seeds 2 .. 7).
"""
from __future__ import annotations

import datetime
import math
import statistics
from dataclasses import asdict, dataclass

SCHEMA = "loupmd.bench/1"


@dataclass(frozen=True)
class Protocol:
    name: str
    temperature_K: float = 300.0
    timestep_fs: float = 1.0
    friction_per_fs: float = 0.01
    skin_A: float = 0.5
    warmup_steps: int = 100
    blocks: int = 6
    block_steps: int = 256
    velocity_seed: int = 42


PROTOCOLS = {
    "standard": Protocol("standard"),
    # FastMACE's, for comparisons with its published tables.
    "fastmace": Protocol("fastmace", warmup_steps=300, blocks=4, block_steps=300),
    # One short look: under a minute on any supported GPU.
    "quick": Protocol("quick", warmup_steps=50, blocks=2, block_steps=128),
}


@dataclass(frozen=True)
class Row:
    """One system's result."""

    system: str
    atoms: int
    ms_per_step: float            # median over the blocks
    us_per_atom_step: float
    ns_per_day: float             # at the protocol's timestep
    blocks_ms: tuple              # ms per step of each block
    block_spread: float           # (max - min) / median of the blocks
    final_temperature_K: float
    dangerous_builds: int
    pipelined_steps: int
    rebuilds: int
    bundle: str                   # file name of the bundle (its key: model, elements, head, exporter)
    status: str                   # "ok", or "UNSTABLE" when the temperature is not finite


def time_system(engine, name, atoms, protocol: Protocol, bundle: str = "") -> Row:
    """Run the protocol on ``atoms`` with an engine that has the right bundle loaded."""
    import numpy as np
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    at = atoms.copy()
    MaxwellBoltzmannDistribution(at, temperature_K=protocol.temperature_K,
                                 rng=np.random.default_rng(protocol.velocity_seed))
    engine.set_system(at.get_atomic_numbers(), at.get_masses(), skin=protocol.skin_A)
    engine.set_state(at.positions, at.get_velocities(), at.cell.array)
    run = dict(dt_fs=protocol.timestep_fs, temp_k=protocol.temperature_K, friction_per_fs=protocol.friction_per_fs)
    if protocol.warmup_steps:
        engine.run_langevin(protocol.warmup_steps, seed=1, **run)
    stats = [engine.run_langevin(protocol.block_steps, seed=block + 2, **run) for block in range(protocol.blocks)]
    return row_from_blocks(name, len(at), [s.step_ms for s in stats], protocol,
                           final_temperature_K=stats[-1].final_temperature_k,
                           dangerous_builds=sum(s.dangerous_builds for s in stats),
                           pipelined_steps=sum(s.pipelined_steps for s in stats),
                           rebuilds=sum(s.rebuilds for s in stats), bundle=bundle)


def row_from_blocks(name, atoms, blocks_ms, protocol, final_temperature_K, dangerous_builds=0, pipelined_steps=0,
                    rebuilds=0, bundle="") -> Row:
    median = statistics.median(blocks_ms)
    finite = math.isfinite(final_temperature_K) and math.isfinite(median) and median > 0.0
    nan = float("nan")
    return Row(system=name, atoms=int(atoms), ms_per_step=float(median),
               us_per_atom_step=median * 1e3 / atoms if finite else nan,
               ns_per_day=86.4 * protocol.timestep_fs / median if finite else nan,
               blocks_ms=tuple(float(b) for b in blocks_ms),
               block_spread=(max(blocks_ms) - min(blocks_ms)) / median if finite else nan,
               final_temperature_K=float(final_temperature_K), dangerous_builds=int(dangerous_builds),
               pipelined_steps=int(pipelined_steps), rebuilds=int(rebuilds), bundle=str(bundle),
               status="ok" if finite else "UNSTABLE")


def _table(lines) -> str:
    widths = [max(len(line[i]) for line in lines) for i in range(len(lines[0]))]
    out = ["  ".join(cell.ljust(w) if i == 0 else cell.rjust(w) for i, (cell, w) in enumerate(zip(line, widths)))
           for line in lines]
    out.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(out)


def format_table(rows, references=None) -> str:
    """The result table. ``references`` maps a system to the stored ms/step of the same GPU model, model file and
    protocol; with it two more columns appear: that reference and measured / reference."""
    references = references or {}
    header = ["system", "atoms", "ms/step", "us/atom-step", "ns/day", "spread", "T / K", "dangerous", "status"]
    if references:
        header[3:3] = ["reference", "ratio"]
    lines = [tuple(header)]
    for r in rows:
        cells = [r.system, f"{r.atoms}", f"{r.ms_per_step:.3f}", f"{r.us_per_atom_step:.2f}", f"{r.ns_per_day:.1f}",
                 f"{100.0 * r.block_spread:.1f}%", f"{r.final_temperature_K:.0f}", f"{r.dangerous_builds}", r.status]
        if references:
            ref = references.get(r.system)
            cells[3:3] = [f"{ref:.3f}", f"{r.ms_per_step / ref:.3f}"] if ref else ["-", "-"]
        lines.append(tuple(cells))
    return _table(lines)


def make_record(rows, protocol, suite, gpu, model, library, package_version, other_gpu_processes=(),
                gpu_utilisation_percent=None, device=0, created=None) -> dict:
    """The JSON record of a benchmark (``loupmd.bench/1``)."""
    return {
        "schema": SCHEMA,
        "created": created or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "loupmd": package_version,
        "library": library,
        "device": int(device),
        "gpu": dict(gpu),
        "model": dict(model),
        "suite": suite,
        "protocol": asdict(protocol),
        "rows": [dict(asdict(r), blocks_ms=list(r.blocks_ms)) for r in rows],
        "other_gpu_processes": list(other_gpu_processes),
        "gpu_utilisation_percent": gpu_utilisation_percent,     # before the run; None when nvidia-smi gave none
    }


_ROW_KEYS = {"system": str, "atoms": int, "ms_per_step": float, "us_per_atom_step": float, "ns_per_day": float,
             "blocks_ms": list, "block_spread": float, "final_temperature_K": float, "dangerous_builds": int,
             "pipelined_steps": int, "rebuilds": int, "bundle": str, "status": str}
_TOP_KEYS = {"schema": str, "created": str, "loupmd": str, "library": str, "device": int, "gpu": dict, "model": dict,
             "suite": str, "protocol": dict, "rows": list, "other_gpu_processes": list}


def validate_record(record) -> list:
    """Problems of a record against ``loupmd.bench/1``; empty when it is valid."""
    problems = []
    if not isinstance(record, dict):
        return ["the record is not an object"]
    for key, kind in _TOP_KEYS.items():
        if key not in record:
            problems.append(f"missing key {key!r}")
        elif not isinstance(record[key], kind):
            problems.append(f"{key!r} is not a {kind.__name__}")
    if record.get("schema") != SCHEMA:
        problems.append(f"schema is {record.get('schema')!r}, not {SCHEMA!r}")
    gpu = record.get("gpu") if isinstance(record.get("gpu"), dict) else {}
    for key in ("name", "compute_capability", "driver"):
        if key not in gpu:
            problems.append(f"gpu lacks {key!r}")
    model = record.get("model") if isinstance(record.get("model"), dict) else {}
    for key in ("label", "file", "sha256", "head"):
        if key not in model:
            problems.append(f"model lacks {key!r}")
    for index, row in enumerate(record.get("rows") if isinstance(record.get("rows"), list) else []):
        for key, kind in _ROW_KEYS.items():
            if key not in row:
                problems.append(f"row {index} lacks {key!r}")
            elif kind is float and (isinstance(row[key], bool) or not isinstance(row[key], (int, float))):
                problems.append(f"row {index}: {key!r} is not a number")
            elif kind is not float and (not isinstance(row[key], kind) or isinstance(row[key], bool)):
                problems.append(f"row {index}: {key!r} is not a {kind.__name__}")
        if row.get("status") not in ("ok", "UNSTABLE"):
            problems.append(f"row {index}: status {row.get('status')!r}")
    return problems
