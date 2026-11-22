"""Build systems for the engine.

  python -m verlet_prep water N --model tip3p --out data/systems/water.vsys
  python -m verlet_prep protein data/pdb/1L2Y.pdb --water EQUILIBRATED.pdb --out ...
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

from .forcefield import ForceField, build_system
from .pdb import Structure, read_pdb, write_pdb
from .topology import write_vsys
from .water import solvate, water_box, water_geometry


def ff_dir():
    import importlib.util

    spec = importlib.util.find_spec("openmm")
    if spec is None or spec.submodule_search_locations is None:
        sys.exit("the force-field parameter files come from the openmm package (pip install openmm)")
    return os.path.join(list(spec.submodule_search_locations)[0], "app", "data", "amber14")


def load_ff(model: str) -> ForceField:
    d = ff_dir()
    return ForceField.load(os.path.join(d, "protein.ff14SB.xml"), os.path.join(d, f"{model}.xml"))


def save(structure: Structure, ff: ForceField, out: str):
    geom = water_geometry(ff)
    s = build_system(ff, structure, structure.box, water_geometry=geom[:2])
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    write_vsys(out, s)
    residues = []
    k = 0
    for r in structure.residues:
        residues.append((r.name, r.chain, r.number, [(s.names[k + i], s.elements[k + i]) for i in range(len(r.atoms))]))
        k += len(r.atoms)
    write_pdb(os.path.splitext(out)[0] + ".pdb", residues, s.xyz, structure.box)
    q = s.charge.sum()
    print(f"{out}: {s.n} atoms, {len(s.waters)} waters, box {structure.box.round(3).tolist()} nm, net charge {q:+.3f}")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(prog="verlet_prep")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("water", help="a cubic box of N waters on a lattice")
    w.add_argument("n", type=int)
    w.add_argument("--model", default="tip3p", choices=["tip3p", "spce", "opc3"])
    w.add_argument("--density", type=float, default=0.997)
    w.add_argument("--seed", type=int, default=1)
    w.add_argument("--out", required=True)
    p = sub.add_parser("protein", help="a protein (with hydrogens) solvated in water, neutralized")
    p.add_argument("pdb")
    p.add_argument("--model", default="tip3p", choices=["tip3p", "spce", "opc3"])
    p.add_argument("--padding", type=float, default=1.0)
    p.add_argument("--water", default=None, help="an equilibrated water box (PDB) to tile")
    p.add_argument("--salt", type=float, default=0.0, help="NaCl molarity")
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ff = load_ff(a.model)
    if a.cmd == "water":
        save(water_box(ff, a.n, a.density, a.seed), ff, a.out)
    else:
        solute = read_pdb(a.pdb)
        solute.residues = [r for r in solute.residues if r.name not in ("HOH", "WAT")]
        q = build_system(ff, solute, np.array([10.0, 10.0, 10.0])).charge.sum()
        wat = read_pdb(a.water) if a.water else None
        save(solvate(solute, ff, int(round(q)), a.padding, wat, molar=a.salt), ff, a.out)


if __name__ == "__main__":
    main()
