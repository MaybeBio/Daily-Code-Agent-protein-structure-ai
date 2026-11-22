"""The gate's references: MACE in float64 and float32 on the same structures, cached.

They do not depend on LoupMD, so they are computed once per model, head, structures, reference device and
mace / torch version and kept under ``<cache root>/gate_refs`` (``LOUP_GATE_CACHE`` overrides the folder). The key
recipe is ``tools/dev/test_gate.py``'s, so both read each other's files. Needs the export extra (torch, mace-torch).
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import platform
from pathlib import Path

from .. import cache
from ..errors import GateUnavailable

CACHE_FORMAT = "gate-refs-1"
FD_STRESS_H = 1e-5
_find_spec = importlib.util.find_spec


def require():
    """Raise ``GateUnavailable`` unless torch and mace-torch can be imported."""
    missing = [dist for module, dist in (("torch", "torch"), ("mace", "mace-torch")) if _find_spec(module) is None]
    if missing:
        raise GateUnavailable(f"the gate needs {' and '.join(missing)}, which {'is' if len(missing) == 1 else 'are'} "
                              "not installed",
                              why="its references are MACE's own float64 and float32 results on the same structures")


def versions():
    import mace
    import torch

    return getattr(mace, "__version__", "?"), torch.__version__


def resolve_device(reference_device):
    """``auto`` is the GPU when torch sees one, else the CPU."""
    if reference_device != "auto":
        return reference_device
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def device_tag(device):
    """The reference device as it affects rounding: for CUDA the GPU model, compute capability and CUDA version (a
    reference computed on another GPU is not reused), for the CPU the machine type."""
    import torch

    if device.startswith("cuda") and torch.cuda.is_available():
        index = torch.device(device).index or 0
        capability = torch.cuda.get_device_capability(index)
        return f"cuda:{torch.cuda.get_device_name(index)}:sm{capability[0]}{capability[1]}:cuda{torch.version.cuda}"
    return f"{device}:{platform.machine()}"


def default_head(model_path):
    """For a multi-head file given without a head: the exporter's default head, named for MACE's calculator."""
    import torch

    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    heads = list(getattr(torch.load(model_path, map_location="cpu", weights_only=False), "heads", None) or [])
    if len(heads) > 1:
        return next((h for h in ("omat_pbe", "default", "Default") if h in heads), heads[-1])
    return None


def cache_path(model_file, digest, head, set_name, device_tag, versions, configs, charge_spin=(None, None),
               environ=None) -> Path:
    import numpy as np

    environ = os.environ if environ is None else environ
    h = hashlib.sha256()
    for part in (CACHE_FORMAT, digest, str(head), set_name, device_tag, versions[0], versions[1], repr(FD_STRESS_H)):
        h.update(part.encode() + b"\0")
    if charge_spin is not None and tuple(charge_spin) != (None, None):
        h.update(f"charge={charge_spin[0]}|spin={charge_spin[1]}".encode() + b"\0")
    for name, at in configs:
        h.update(name.encode() + b"\0")
        h.update(np.ascontiguousarray(at.get_atomic_numbers(), dtype=np.int64).tobytes())
        h.update(np.ascontiguousarray(at.positions, dtype=np.float64).tobytes())
        h.update(np.ascontiguousarray(at.cell.array, dtype=np.float64).tobytes())
        h.update(np.asarray(at.pbc, dtype=np.int8).tobytes())
    override = environ.get("LOUP_GATE_CACHE")
    root = Path(os.path.expanduser(override)) if override else cache.cache_dir("gate_refs", create=False,
                                                                               environ=environ)
    return root / f"{Path(model_file).stem}_{set_name}_{h.hexdigest()[:20]}.npz"


def load(path, n):
    """The cached references ``(ref64, ref32, stress_ref)``, or ``None`` if absent or unreadable."""
    import numpy as np

    path = Path(path)
    if not path.exists():
        return None
    try:
        with np.load(path) as z:
            def ref(prefix, i):
                return float(z[f"{prefix}e"][i]), np.array(z[f"{prefix}f{i}"]), np.array(z[f"{prefix}s"][i])

            return ([ref("r64", i) for i in range(n)], [ref("r32", i) for i in range(n)],
                    [np.array(z["sref"][i]) for i in range(n)])
    except Exception:  # noqa: BLE001  (any unreadable entry means: recompute)
        return None


def save(path, ref64, ref32, stress_ref):
    import numpy as np

    path = Path(path)
    arrays = {"sref": np.stack(stress_ref)}
    for prefix, refs in (("r64", ref64), ("r32", ref32)):
        arrays[f"{prefix}e"] = np.array([e for e, _, _ in refs])
        arrays[f"{prefix}s"] = np.stack([s for _, _, s in refs])
        for i, (_, forces, _) in enumerate(refs):
            arrays[f"{prefix}f{i}"] = forces
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.stem + f".tmp{os.getpid()}.npz")
    np.savez(part, **arrays)
    os.replace(part, path)


def _evaluate(model_path, dtype, configs, head, device, charge, spin):
    import numpy as np
    from mace.calculators import MACECalculator

    calc = MACECalculator(model_paths=str(model_path), device=device, default_dtype=dtype,
                          **({"head": head} if head else {}))
    out = []
    for _, at in configs:
        a = at.copy()
        if charge is not None:
            a.info["charge"] = int(charge)
        if spin is not None:
            a.info["spin"] = int(spin)
        a.calc = calc
        out.append((float(a.get_potential_energy()), np.asarray(a.get_forces(), dtype=np.float64),
                    np.asarray(a.get_stress(voigt=False), dtype=np.float64)))
    return out


def _fd_stress(model_path, configs, device, h=FD_STRESS_H):
    """Stress as the float64 MACE energy's central difference under symmetric strain. For PolarMACE this is the
    reference whatever mace-torch is installed: up to 0.3.16 its autograd stress leaves out the k-space terms' cell
    dependence (about 0.02 GPa on a water box with POLAR-1-S); 0.3.17 has it."""
    import numpy as np
    from mace.calculators import MACECalculator

    calc = MACECalculator(model_paths=str(model_path), device=device, default_dtype="float64")
    out = []
    for _, at in configs:
        def energy(eps, at=at):
            a = at.copy()
            deformation = np.eye(3) + eps
            a.set_cell(at.cell.array @ deformation, scale_atoms=False)
            a.positions = at.positions @ deformation
            a.calc = calc
            return a.get_potential_energy()

        volume, stress = at.get_volume(), np.zeros((3, 3))
        for i in range(3):
            for j in range(i, 3):
                eps = np.zeros((3, 3))
                eps[i, j] = eps[j, i] = h
                stress[i, j] = stress[j, i] = (energy(eps) - energy(-eps)) / (2 * h) / volume / (1 if i == j else 2)
        out.append(stress)
    return out


def compute(model_path, configs, head, device, charge, spin):
    """``(ref64, ref32, stress_ref)``: MACE float64 and float32 ``(energy, forces, stress)`` per configuration and
    the stress each is gated against (MACE float64 autograd; for PolarMACE the finite-difference stress)."""
    import torch

    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    ref64 = _evaluate(model_path, "float64", configs, head, device, charge, spin)
    ref32 = _evaluate(model_path, "float32", configs, head, device, charge, spin)
    stress_ref = [s for _, _, s in ref64]
    if type(torch.load(model_path, map_location="cpu", weights_only=False)).__name__ == "PolarMACE":
        stress_ref = _fd_stress(model_path, configs, device)
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return ref64, ref32, stress_ref
