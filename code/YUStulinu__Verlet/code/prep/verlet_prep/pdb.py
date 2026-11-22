"""Reading and writing PDB files (the subset used here: ATOM/HETATM, the
first MODEL, CRYST1)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Atom:
    name: str
    element: str
    xyz: np.ndarray  # nm


@dataclass
class Residue:
    name: str
    chain: str
    number: int
    atoms: list[Atom] = field(default_factory=list)

    def atom(self, name: str) -> Atom | None:
        for a in self.atoms:
            if a.name == name:
                return a
        return None


@dataclass
class Structure:
    residues: list[Residue]
    box: np.ndarray | None = None  # nm, orthorhombic

    def atoms(self):
        for r in self.residues:
            yield from r.atoms

    def positions(self) -> np.ndarray:
        return np.array([a.xyz for a in self.atoms()])

    def chains(self) -> list[list[Residue]]:
        out: list[list[Residue]] = []
        for r in self.residues:
            if not out or out[-1][0].chain != r.chain:
                out.append([])
            out[-1].append(r)
        return out


def _element(name: str, col: str) -> str:
    e = col.strip()
    if e:
        return e[0].upper() + e[1:].lower()
    letters = "".join(c for c in name if c.isalpha())
    return letters[:1].upper()


def read_pdb(path: str) -> Structure:
    residues: list[Residue] = []
    box = None
    with open(path) as f:
        for line in f:
            rec = line[:6]
            if rec == "ENDMDL":
                break  # first model only
            if rec == "CRYST1":
                box = np.array([float(line[6:15]), float(line[15:24]), float(line[24:33])]) / 10
            if rec not in ("ATOM  ", "HETATM"):
                continue
            name = line[12:16].strip()
            resname = line[17:20].strip()
            chain = line[21]
            number = int(line[22:26])
            icode = line[26]
            xyz = np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])]) / 10
            element = _element(name, line[76:78] if len(line) >= 78 else "")
            key = (chain, number, icode, resname)
            if not residues or (residues[-1].chain, residues[-1].number, getattr(residues[-1], "_icode", " "), residues[-1].name) != key:
                r = Residue(resname, chain, number)
                r._icode = icode  # type: ignore[attr-defined]
                residues.append(r)
            residues[-1].atoms.append(Atom(name, element, xyz))
    return Structure(residues, box)


def write_pdb(path: str, residues: list[tuple[str, str, int, list[tuple[str, str]]]], xyz: np.ndarray, box=None):
    """residues: (name, chain, number, [(atom name, element)]); xyz in nm."""
    with open(path, "w") as f:
        if box is not None:
            b = np.asarray(box) * 10
            f.write(f"CRYST1{b[0]:9.3f}{b[1]:9.3f}{b[2]:9.3f}  90.00  90.00  90.00 P 1           1\n")
        k = 0
        serial = 1
        for name, chain, number, atoms in residues:
            for an, el in atoms:
                p = xyz[k] * 10
                aname = an if len(an) == 4 or len(el) == 2 else " " + an
                f.write(f"ATOM  {serial % 100000:5d} {aname:<4s} {name:>3s} {chain}{number % 10000:4d}    "
                        f"{p[0]:8.3f}{p[1]:8.3f}{p[2]:8.3f}  1.00  0.00          {el:>2s}\n")
                k += 1
                serial += 1
        f.write("END\n")
