"""``loupmd bench --compare``: the same structure with another engine, on this machine.

A comparison runs fewer steps than LoupMD's protocol (the other engines are slower by one to two orders of
magnitude): 10 warm-up steps, then the median of 3 blocks of 20 steps, with the protocol's temperature, timestep and
friction. Its record says so; the ratio is theirs / LoupMD's.
"""
from __future__ import annotations

import os
import statistics
import time

from ..errors import LoupError

WARMUP_STEPS, BLOCKS, BLOCK_STEPS = 10, 3, 20


def time_mace(model_path, name, atoms, protocol, head=None, device=0):
    """``mace-torch``'s ASE calculator (float32, on the GPU) under ASE's Langevin integrator."""
    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")     # the file passed the trust rule before
    try:
        import mace
        import torch
        from mace.calculators import MACECalculator
    except ImportError as exc:
        raise LoupError("--compare mace needs mace-torch", why=str(exc),
                        next_step="Install the export extra: pip install 'loupmd[export]'.") from None
    import numpy as np
    from ase import units
    from ase.md.langevin import Langevin
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    at = atoms.copy()
    MaxwellBoltzmannDistribution(at, temperature_K=protocol.temperature_K,
                                 rng=np.random.default_rng(protocol.velocity_seed))
    at.calc = MACECalculator(model_paths=str(model_path), device=f"cuda:{device}", default_dtype="float32",
                             **({"head": head} if head else {}))
    dynamics = Langevin(at, timestep=protocol.timestep_fs * units.fs, temperature_K=protocol.temperature_K,
                        friction=protocol.friction_per_fs / units.fs, rng=np.random.default_rng(1))
    dynamics.run(WARMUP_STEPS)
    blocks_ms = []
    for _ in range(BLOCKS):
        torch.cuda.synchronize(device)
        start = time.perf_counter()
        dynamics.run(BLOCK_STEPS)
        torch.cuda.synchronize(device)
        blocks_ms.append((time.perf_counter() - start) * 1e3 / BLOCK_STEPS)
    result = {"engine": "mace-torch", "version": getattr(mace, "__version__", None), "ms_per_step":
              statistics.median(blocks_ms), "blocks_ms": blocks_ms, "final_temperature_K": float(at.get_temperature())}
    del at.calc, dynamics
    torch.cuda.empty_cache()
    return result


ENGINES = {"mace": time_mace}


def run(engine, model_path, name, atoms, protocol, head=None, device=0, loupmd_ms=None) -> dict:
    """One comparison's entry of the record. A comparison that fails (no memory, a model class the other engine
    does not read) is recorded with its error and does not stop the benchmark."""
    entry = {"engine": engine, "system": name, "atoms": len(atoms), "warmup_steps": WARMUP_STEPS, "blocks": BLOCKS,
             "block_steps": BLOCK_STEPS}
    try:
        entry.update(ENGINES[engine](model_path, name, atoms, protocol, head=head, device=device))
    except LoupError:
        raise
    except Exception as exc:  # noqa: BLE001  (the other engine's failure is a result here, not ours)
        entry.update(ms_per_step=None, error=f"{type(exc).__name__}: {exc}"[:400])
        return entry
    if loupmd_ms:
        entry["ratio_to_loupmd"] = entry["ms_per_step"] / loupmd_ms
    return entry


def format_comparisons(comparisons) -> str:
    lines = []
    for c in comparisons:
        if c.get("ms_per_step") is None:
            lines.append(f"{c['engine']}  {c['system']}: failed ({c.get('error')})")
        else:
            ratio = f", {c['ratio_to_loupmd']:.1f} x LoupMD's step time" if "ratio_to_loupmd" in c else ""
            lines.append(f"{c['engine']}  {c['system']}: {c['ms_per_step']:.2f} ms/step (median of {c['blocks']} x "
                         f"{c['block_steps']} steps{ratio})")
    return "\n".join(lines)
