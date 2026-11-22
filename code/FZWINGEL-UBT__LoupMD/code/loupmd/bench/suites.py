"""The benchmark systems and suites.

``SrTiO3`` and ``NaCl`` are generated. ``NbCl5`` and the water box are files: they are looked for in
``loupmd/bench/structures/`` and then in ``$LOUPMD_BENCH_STRUCTURES``. The water box and the organic crystals of
the gate ship with the package; ``NbCl5`` does not yet (``structures/SOURCES.md`` says why).
"""
from __future__ import annotations

import os
from pathlib import Path

from ..errors import InputError, LoupError

STRUCTURES_VARIABLE = "LOUPMD_BENCH_STRUCTURES"
_SHIPPED = Path(__file__).resolve().parent / "structures"
FILES = {"nbcl5": "NbCl5_R2SCAN.cif", "water": "water_216.extxyz"}


def find_file(name, environ=None) -> Path:
    """A structure file by name: shipped with the package, or in one of the folders of ``$LOUPMD_BENCH_STRUCTURES``
    (several are separated like ``PATH``)."""
    environ = os.environ if environ is None else environ
    places = [_SHIPPED]
    places += [Path(os.path.expanduser(p)) for p in (environ.get(STRUCTURES_VARIABLE) or "").split(os.pathsep) if p]
    for place in places:
        if (place / name).is_file():
            return place / name
    raise InputError(f"the structure {name} was not found",
                     why="it is not shipped with this build of LoupMD",
                     next_step=f"Set {STRUCTURES_VARIABLE} to the folder that holds {name} (several folders are "
                               "separated like PATH), or run a suite that needs no file (--suite quick).")


def structure_file(key, environ=None) -> Path:
    return find_file(FILES[key], environ)


def srtio3(rep: int):
    from ase import Atoms

    a = 3.905
    return Atoms(symbols=["Sr", "Ti", "O", "O", "O"],
                 scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
                 cell=[a, a, a], pbc=True).repeat((rep, rep, rep))


def _nacl(environ=None):
    from ase.build import bulk

    return bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((3, 3, 3))


def _nbcl5(environ=None):
    from ase.io import read

    return read(structure_file("nbcl5", environ)).repeat((3, 3, 3))


def _water(rep):
    def build(environ=None):
        from ase.io import read

        return read(structure_file("water", environ)).repeat((rep, rep, rep))
    return build


# name -> builder(environ) of the system
SYSTEMS = {
    "NbCl5 3x3x3": _nbcl5,                                     # 1,944 atoms (file)
    "SrTiO3 10x10x10": lambda environ=None: srtio3(10),        # 5,000 atoms
    "SrTiO3 6x6x6": lambda environ=None: srtio3(6),            # 1,080 atoms
    "NaCl 3x3x3": _nacl,                                       # 216 atoms, rocksalt a = 5.64 A
    "water 216": _water(1),                                    # 648 atoms (file)
    "water 216 2x2x2": _water(2),                              # 5,184 atoms (file)
}
SUITES = {
    "standard": ("NbCl5 3x3x3", "SrTiO3 10x10x10"),   # the two systems of the optimisation ledger
    "quick": ("SrTiO3 6x6x6",),                       # no file needed
}
# The ``families`` suite: one system per model family (the label table's ``family``).
FAMILY_SYSTEM = {"residual": "SrTiO3 10x10x10", "density": "SrTiO3 10x10x10", "mh1": "SrTiO3 10x10x10",
                 "polar": "NaCl 3x3x3", "off": "water 216", "omol": "water 216"}
SUITE_NAMES = ("standard", "quick", "families", "capacity")
DEFAULT_PROTOCOL = {"standard": "standard", "quick": "quick", "families": "standard"}


def systems_of(suite, family=None, systems=None, environ=None):
    """``[(name, atoms)]`` of a suite, or of ``systems`` when given; a missing structure file is reported here,
    before anything is exported or run."""
    if systems:
        unknown = [s for s in systems if s not in SYSTEMS]
        if unknown:
            raise InputError(f"unknown system {unknown[0]!r}", next_step=f"Systems: {', '.join(SYSTEMS)}.")
        names = tuple(systems)
    elif suite == "capacity":
        raise LoupError("the capacity suite is not in this version",
                        why="it times the tiled call, which this version does not have yet (PLAN.md Stage 5)",
                        next_step="Run --suite standard, quick or families.")
    elif suite == "families":
        if family not in FAMILY_SYSTEM:
            raise InputError("the families suite needs a model of the label table, whose family chooses the system",
                             why=f"this model's family is {family!r}",
                             next_step=f"Name the system instead: --system NAME ({', '.join(SYSTEMS)}).")
        names = (FAMILY_SYSTEM[family],)
    elif suite in SUITES:
        names = SUITES[suite]
    else:
        raise InputError(f"unknown suite {suite!r}", next_step=f"Suites: {', '.join(SUITE_NAMES)}.")
    return [(name, SYSTEMS[name](environ)) for name in names]
