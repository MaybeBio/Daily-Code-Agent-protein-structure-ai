"""The structures the gate runs on: the sets of ``tools/dev/test_gate.py`` and rattled copies of a user's structure.

The sets are built exactly as ``test_gate.py`` builds them (same strains, rattles and seed), so both find the same
cached references. Files are found as the benchmark's are (``loupmd.bench.suites.find_file``).
"""
from __future__ import annotations

from pathlib import Path

from ..bench import suites
from ..errors import InputError

SEED = 20261112
SET_NAMES = ("oxide", "organic", "crystals")


def _configs(bases, schedule, seed=SEED):
    import numpy as np

    rng = np.random.default_rng(seed)
    configs = []
    for name, base in bases:
        for k, (strain, rattle) in enumerate(schedule):
            at = base.copy()
            deformation = np.eye(3) + strain * np.array([[1.0, 0.1, -0.05], [0.1, 0.8, 0.07], [-0.05, 0.07, 1.2]])
            at.set_cell(at.cell.array @ deformation.T, scale_atoms=True)
            at.positions += rng.normal(0.0, rattle, size=at.positions.shape)
            configs.append((f"{name}_c{k}", at))
    return configs


def _read(name, environ):
    from ase.io import read

    return read(suites.find_file(name, environ))


def _oxide(environ):
    """NaCl 2x2x2 (64 atoms), SrTiO3 3x3x3 (135) and NbCl5 2x2x2 (576, above the 512-atom kernel switch)."""
    from ase.build import bulk

    nbcl5 = _read("NbCl5_R2SCAN.cif", environ).repeat((2, 2, 2))       # looked for first: nothing is built without it
    bases = [("NaCl_2x2x2", bulk("NaCl", "rocksalt", a=5.64, cubic=True).repeat((2, 2, 2))),
             ("SrTiO3_3x3x3", suites.srtio3(3)), ("NbCl5_2x2x2", nbcl5)]
    return _configs(bases, [(0.02, 0.05), (-0.015, 0.08)])


def _organic(environ):
    """MACE-OFF's set: urea, naphthalene, paracetamol and the 648-atom water box."""
    bases = [("urea_3x3x3", _read("urea_cod1008787.cif", environ).repeat((3, 3, 3))),
             ("naphthalene_2x2x2", _read("naphthalene_cod2311090.cif", environ).repeat((2, 2, 2))),
             ("paracetamol_2x2x2", _read("paracetamol_cod2104364.cif", environ).repeat((2, 2, 2))),
             ("water_216", _read("water_216.extxyz", environ))]
    return _configs(bases, [(0.01, 0.02), (-0.008, 0.04)])


def _crystals(environ):
    """FastMACE's MH-1 / POLAR set: the R2SCAN cells of NaCl, NaNbO3 and NbCl5, repeated to at least 13 A."""
    import numpy as np

    def repeated(at, length=13.0):
        return at.repeat([max(1, int(np.ceil(length / h))) for h in at.cell.cellpar()[:3]])

    bases = [(name, repeated(_read(f"{name}.cif", environ))) for name in ("NaCl", "NaNbO3", "NbCl5")]
    return _configs(bases, [(0.02, 0.05), (-0.015, 0.08)])


_BUILDERS = {"oxide": _oxide, "organic": _organic, "crystals": _crystals}


def configs(set_name, environ=None):
    """``[(name, atoms)]`` of a set."""
    if set_name not in _BUILDERS:
        raise InputError(f"unknown set {set_name!r}", next_step=f"Sets: {', '.join(SET_NAMES)}; or pass your own "
                                                                "structure.")
    return _BUILDERS[set_name](environ)


def user_configs(structures, gate_config, seed=SEED):
    """Rattled copies of the user's structures (files or ``Atoms``): ``gate_config.copies`` of each, displaced by a
    normal distribution of width ``gate_config.rattle_A``. Names are ``<file stem>_r<k>``."""
    import numpy as np
    from ase.io import read

    rng = np.random.default_rng(seed)
    out = []
    for index, structure in enumerate(structures):
        if isinstance(structure, (str, Path)):
            path = Path(structure)
            if not path.is_file():
                raise InputError(f"structure file {path} not found")
            name, atoms = path.stem, read(path)
        else:
            name, atoms = f"structure{index}", structure
        if not all(atoms.pbc):
            raise InputError(f"{name} has pbc={tuple(bool(p) for p in atoms.pbc)}; the gate needs a cell periodic "
                             "in all three directions",
                             next_step="Put a molecule or slab in a box with vacuum and set pbc=True.")
        for k in range(gate_config.copies):
            at = atoms.copy()
            at.positions += rng.normal(0.0, gate_config.rattle_A, size=at.positions.shape)
            out.append((f"{name}_r{k}", at))
    return out
