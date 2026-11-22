"""LoupMD: molecular dynamics with MACE potentials on a C++/CUDA engine."""
from __future__ import annotations

from ._core import EngineInfo, LoupEngine, LoupMDStats, last_error, library_path, library_version
from .errors import (BackendError, CacheLocationError, CapacityError, CellDivergedError, CheckpointTrustError,
                     GateFailed, GateUnavailable, InputError, LoupError, ModelElementError, NonFiniteError,
                     PlanRefused, RestartMismatch, UnsupportedModel)

__version__ = "0.0.2"  # LOUP_VERSION of include/loupmd.h (tests/test_abi.py keeps the two equal)

from .runtime import GpuInfo, RuntimeInfo, runtime_info  # noqa: E402  (reads __version__ when called)

from .bundles import EXPORTER_SOURCES, _model_digest, ensure_loup_bundle, exporter_fingerprint  # noqa: E402


def load(model, head=None, **options):
    """``ff = lm.load("omat0-medium")``: a ``ForceField`` (``loupmd.forcefield.load`` has the arguments)."""
    from .forcefield import load as make

    return make(model, head, **options)


# The front end, resolved at first use so that `import loupmd` stays light: name -> (module, attribute).
_LAZY = {"ForceField": ("forcefield", "ForceField"), "Simulation": ("simulation", "Simulation"),
         "Output": ("config", "Output"), "integrators": ("integrators", None), "protocols": ("protocols", None),
         "md": ("quick", "md"), "RunResult": ("quick", "RunResult"), "optimize": ("optimize", None),
         "mc": ("mc", None), "Dispersion": ("dispersion", "Dispersion"), "dispersion": ("dispersion", None),
         "config": ("config", None)}


def __getattr__(name):
    if name in _LAZY:
        import importlib

        module_name, attribute = _LAZY[name]
        module = importlib.import_module(f"{__name__}.{module_name}")
        return module if attribute is None else getattr(module, attribute)
    raise AttributeError(f"module 'loupmd' has no attribute {name!r}")


def calc(model, **options):
    """``atoms.calc = lm.calc("omat0-medium")``: the ASE calculator (``loupmd.ase.calculator.calc`` has the
    arguments). ASE is imported here, at the first use."""
    from .ase.calculator import calc as make

    return make(model, **options)


__all__ = [
    "BackendError", "CacheLocationError", "CapacityError", "CellDivergedError", "CheckpointTrustError", "Dispersion",
    "EngineInfo",
    "ForceField", "GateFailed", "GateUnavailable", "GpuInfo", "InputError", "LoupEngine", "LoupError", "LoupMDStats",
    "ModelElementError", "NonFiniteError", "Output", "PlanRefused", "RestartMismatch", "RunResult", "RuntimeInfo",
    "Simulation", "UnsupportedModel",
    "__version__", "calc", "config", "dispersion", "ensure_loup_bundle", "exporter_fingerprint", "last_error", "library_path",
    "integrators", "library_version", "load", "mc", "md", "optimize", "protocols", "runtime_info",
]
