"""LoupMD behind ASE's interfaces. ``loupmd.ase.calculator`` is the calculator (``lm.calc``); the MD classes of
``loupmd.ase.md`` and the optimisers of ``loupmd.ase.optimize`` are also here by name, so an ASE script changes
its import line only: ``from loupmd.ase import Langevin`` (as ``from fastmace.ase import Langevin``)."""

_MD = ("Langevin", "LangevinBAOAB", "VelocityVerlet", "Bussi", "NoseHooverChainNVT", "IsotropicMTKNPT", "MTKNPT",
       "NVTBerendsen", "NPTBerendsen", "Inhomogeneous_NPTBerendsen")
_OPTIMIZE = ("LBFGS", "FIRE")
__all__ = [*_MD, *_OPTIMIZE, "LoupCalculator"]


def __getattr__(name):
    import importlib

    if name in _MD:
        return getattr(importlib.import_module(".md", __name__), name)
    if name in _OPTIMIZE:
        return getattr(importlib.import_module(".optimize", __name__), name)
    if name == "LoupCalculator":
        return importlib.import_module(".calculator", __name__).LoupCalculator
    if name in ("md", "optimize", "calculator"):
        return importlib.import_module("." + name, __name__)
    raise AttributeError(f"module 'loupmd.ase' has no attribute {name!r}")
