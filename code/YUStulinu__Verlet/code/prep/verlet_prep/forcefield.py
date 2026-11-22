"""Force-field parameters read from OpenMM's ffxml files (used here only as
parameter data: Amber ff14SB for proteins, TIP3P/SPC/E and ions for water),
and their assignment to a structure.

The assignment follows the ffxml semantics, including OpenMM's rules for
picking torsion definitions (specific over wildcard) and for ordering the
atoms of Amber improper torsions, so that the energies can be compared term
by term with OpenMM's own system.
"""

from __future__ import annotations

import itertools
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

from .pdb import Residue, Structure

MASS = {"H": 1.008, "C": 12.01, "N": 14.01, "O": 16.0, "S": 32.06}
ANY = None  # wildcard type set


@dataclass
class Template:
    name: str
    atoms: list[tuple[str, str, float]]  # name, type, charge
    bonds: list[tuple[str, str]]
    external: list[str]


@dataclass
class Torsion:
    types: list  # 4 sets of type names, or ANY
    periodicity: list[int]
    phase: list[float]
    k: list[float]
    ordering: str = "default"

    def has_wildcard(self):
        return any(t is ANY for t in self.types)


def _in(t, s):
    return s is ANY or t in s


@dataclass
class ForceField:
    types: dict[str, dict] = field(default_factory=dict)  # name -> {class, element, mass}
    templates: dict[str, Template] = field(default_factory=dict)
    bonds: list = field(default_factory=list)  # (set1, set2, r0, k)
    angles: list = field(default_factory=list)  # (set1, set2, set3, theta0, k)
    propers: list[Torsion] = field(default_factory=list)
    impropers: list[Torsion] = field(default_factory=list)
    lj: dict[str, tuple[float, float]] = field(default_factory=dict)  # type -> (sigma, epsilon)
    coulomb14: float = 1.0
    lj14: float = 1.0
    water_geometry: dict = field(default_factory=dict)

    @staticmethod
    def load(*paths: str) -> "ForceField":
        ff = ForceField()
        for p in paths:
            ff._read(p)
        return ff

    def _typeset(self, attrib, i):
        if f"type{i}" in attrib:
            t = attrib[f"type{i}"]
            return ANY if t == "" else {t}
        c = attrib.get(f"class{i}", "")
        if c == "":
            return ANY
        return {n for n, d in self.types.items() if d["class"] == c}

    def _read(self, path):
        root = ET.parse(path).getroot()
        at = root.find("AtomTypes")
        if at is not None:
            for t in at.findall("Type"):
                self.types[t.attrib["name"]] = {
                    "class": t.attrib.get("class", t.attrib["name"]),
                    "element": t.attrib.get("element", ""),
                    "mass": float(t.attrib["mass"]),
                }
        res = root.find("Residues")
        if res is not None:
            for r in res.findall("Residue"):
                atoms = [(a.attrib["name"], a.attrib["type"], float(a.attrib.get("charge", 0))) for a in r.findall("Atom")]
                bonds = []
                names = [a[0] for a in atoms]
                for b in r.findall("Bond"):
                    if "atomName1" in b.attrib:
                        bonds.append((b.attrib["atomName1"], b.attrib["atomName2"]))
                    else:
                        bonds.append((names[int(b.attrib["from"])], names[int(b.attrib["to"])]))
                ext = [e.attrib.get("atomName", names[int(e.attrib["from"])] if "from" in e.attrib else "") for e in r.findall("ExternalBond")]
                self.templates[r.attrib["name"]] = Template(r.attrib["name"], atoms, bonds, ext)
        f = root.find("HarmonicBondForce")
        if f is not None:
            for b in f.findall("Bond"):
                self.bonds.append((self._typeset(b.attrib, 1), self._typeset(b.attrib, 2), float(b.attrib["length"]), float(b.attrib["k"])))
        f = root.find("HarmonicAngleForce")
        if f is not None:
            for a in f.findall("Angle"):
                self.angles.append((self._typeset(a.attrib, 1), self._typeset(a.attrib, 2), self._typeset(a.attrib, 3), float(a.attrib["angle"]), float(a.attrib["k"])))
        f = root.find("PeriodicTorsionForce")
        if f is not None:
            ordering = f.attrib.get("ordering", "default")
            for kind, dest in (("Proper", self.propers), ("Improper", self.impropers)):
                for t in f.findall(kind):
                    per, ph, k = [], [], []
                    i = 1
                    while f"k{i}" in t.attrib:
                        per.append(int(t.attrib[f"periodicity{i}"]))
                        ph.append(float(t.attrib[f"phase{i}"]))
                        k.append(float(t.attrib[f"k{i}"]))
                        i += 1
                    dest.append(Torsion([self._typeset(t.attrib, j) for j in range(1, 5)], per, ph, k, ordering if kind == "Improper" else "default"))
        f = root.find("NonbondedForce")
        if f is not None:
            self.coulomb14 = float(f.attrib.get("coulomb14scale", 1))
            self.lj14 = float(f.attrib.get("lj14scale", 1))
            for a in f.findall("Atom"):
                for t in self._typeset({"type1": a.attrib["type"]} if "type" in a.attrib else {"class1": a.attrib["class"]}, 1) or []:
                    self.lj[t] = (float(a.attrib["sigma"]), float(a.attrib["epsilon"]))

    # ---- parameter lookup -------------------------------------------------------

    def bond_params(self, t1, t2):
        for s1, s2, r0, k in self.bonds:
            if (_in(t1, s1) and _in(t2, s2)) or (_in(t1, s2) and _in(t2, s1)):
                return r0, k
        return None

    def angle_params(self, t1, t2, t3):
        for s1, s2, s3, th, k in self.angles:
            if _in(t2, s2) and ((_in(t1, s1) and _in(t3, s3)) or (_in(t1, s3) and _in(t3, s1))):
                return th, k
        return None

    def proper_params(self, t1, t2, t3, t4):
        """The first specific definition matching either direction; else the first with wildcards."""
        match = None
        for d in self.propers:
            s1, s2, s3, s4 = d.types
            if (_in(t1, s1) and _in(t2, s2) and _in(t3, s3) and _in(t4, s4)) or (_in(t1, s4) and _in(t2, s3) and _in(t3, s2) and _in(t4, s1)):
                if not d.has_wildcard():
                    return d
                if match is None:
                    match = d
        return match


@dataclass
class System:
    """Everything the engine needs (units: nm, ps, amu, kJ/mol, e)."""

    names: list[str]
    elements: list[str]
    resnames: list[str]
    resids: list[int]
    chains: list[str]
    mass: np.ndarray
    charge: np.ndarray
    sigma: np.ndarray
    epsilon: np.ndarray
    xyz: np.ndarray
    box: np.ndarray
    bonds: list = field(default_factory=list)  # (i, j, r0, k), not constrained
    angles: list = field(default_factory=list)  # (i, j, k, theta0, k)
    torsions: list = field(default_factory=list)  # (i, j, k, l, n, phase, k)
    pairs14: list = field(default_factory=list)  # (i, j, qq, sigma, epsilon) scaled
    exclusions: list = field(default_factory=list)  # (i, j): no direct nonbonded interaction
    constraints: list = field(default_factory=list)  # (i, j, d) except rigid waters
    waters: list = field(default_factory=list)  # (o, h1, h2)
    water_geometry: tuple = (0.09572, 0.15139)  # d(OH), d(HH)
    graph_bonds: list = field(default_factory=list)  # every chemical bond (i, j)
    molecules: list = field(default_factory=list)  # first atom of every molecule, then N

    @property
    def n(self):
        return len(self.names)


HIS_VARIANTS = (("HD1", "HE2", "HIP"), ("HD1", None, "HID"), (None, "HE2", "HIE"))


def _template_name(res: Residue, first: bool, last: bool) -> str:
    name = res.name
    if name == "HIS":
        names = {a.name for a in res.atoms}
        for d, e, v in HIS_VARIANTS:
            if (d is None or d in names) and (e is None or e in names) and (d is not None or "HD1" not in names) and (e is not None or "HE2" not in names):
                name = v
                break
    if name in ("WAT", "H2O", "SOL"):
        name = "HOH"
    if first and not last and name not in ("HOH",):
        return "N" + name
    if last and not first and name not in ("HOH",):
        return "C" + name
    return name


ALIASES = {"OC1": "O", "OC2": "OXT", "HN": "H", "HT1": "H1", "HT2": "H2", "HT3": "H3", "OW": "O", "HW1": "H1", "HW2": "H2"}


def build_system(ff: ForceField, structure: Structure, box, water_geometry=(0.09572, 0.15139), constrain_h=True, ion_templates=None) -> System:
    """Parameters for every atom and every bonded term; the structure must have all hydrogens."""
    atoms = []  # (residue index, name, element, template, type, charge, xyz)
    residues = structure.residues
    res_atoms: list[dict[str, int]] = []
    res_tmpl: list[Template] = []
    chains = structure.chains()
    first_of_chain = {id(c[0]) for c in chains if c[0].name not in ("HOH", "WAT", "NA", "CL", "Na+", "Cl-")}
    last_of_chain = {id(c[-1]) for c in chains if c[-1].name not in ("HOH", "WAT", "NA", "CL", "Na+", "Cl-")}
    for ri, r in enumerate(residues):
        tname = _template_name(r, id(r) in first_of_chain, id(r) in last_of_chain)
        if ion_templates and tname in ion_templates:
            tname = ion_templates[tname]
        if tname not in ff.templates:
            raise KeyError(f"no template {tname} for residue {r.name} {r.number}")
        t = ff.templates[tname]
        tnames = [a[0] for a in t.atoms]
        have = {ALIASES.get(a.name, a.name): a for a in r.atoms}
        missing = set(tnames) - set(have)
        extra = set(have) - set(tnames)
        if missing or extra:
            raise ValueError(f"residue {r.name} {r.number} ({tname}): missing {sorted(missing)}, unknown {sorted(extra)}")
        idx = {}
        for a in r.atoms:  # file order for the atom indices
            name = ALIASES.get(a.name, a.name)
            at, q = next((x[1], x[2]) for x in t.atoms if x[0] == name)
            idx[name] = len(atoms)
            atoms.append((ri, name, ff.types[at]["element"] or a.element, tname, at, q, a.xyz))
        res_atoms.append(idx)
        res_tmpl.append(t)
    n = len(atoms)
    types = [a[4] for a in atoms]
    elements = [a[2] for a in atoms]
    tmpl_index = [ [x[0] for x in res_tmpl[a[0]].atoms].index(a[1]) for a in atoms]
    # bonds: template bonds, then peptide bonds between consecutive residues of a chain
    bonds = []
    for ri, t in enumerate(res_tmpl):
        for a, b in t.bonds:
            bonds.append((res_atoms[ri][a], res_atoms[ri][b]))
    for c in chains:
        for r1, r2 in zip(c, c[1:]):
            i1, i2 = residues.index(r1), residues.index(r2)
            if "C" in res_tmpl[i1].external and "N" in res_tmpl[i2].external:
                bonds.append((res_atoms[i1]["C"], res_atoms[i2]["N"]))
    nbr = [[] for _ in range(n)]
    for a, b in bonds:
        nbr[a].append(b)
        nbr[b].append(a)
    sysm = System(
        names=[a[1] for a in atoms], elements=elements, resnames=[residues[a[0]].name for a in atoms],
        resids=[residues[a[0]].number for a in atoms], chains=[residues[a[0]].chain for a in atoms],
        mass=np.array([ff.types[t]["mass"] for t in types]), charge=np.array([a[5] for a in atoms]),
        sigma=np.array([ff.lj[t][0] for t in types]), epsilon=np.array([ff.lj[t][1] for t in types]),
        xyz=np.array([a[6] for a in atoms]), box=np.asarray(box, float), water_geometry=water_geometry,
    )
    sysm.graph_bonds = bonds
    is_water = [residues[a[0]].name in ("HOH", "WAT") or a[3] == "HOH" for a in atoms]
    # rigid waters (SETTLE): no bonded terms
    for ri, t in enumerate(res_tmpl):
        if t.name == "HOH":
            sysm.waters.append((res_atoms[ri]["O"], res_atoms[ri]["H1"], res_atoms[ri]["H2"]))
    # bonds: constraints for X-H (like OpenMM's HBonds), harmonic terms otherwise
    for a, b in bonds:
        if is_water[a]:
            continue
        p = ff.bond_params(types[a], types[b])
        if p is None:
            raise KeyError(f"no bond parameters for {types[a]}-{types[b]}")
        if constrain_h and (elements[a] == "H" or elements[b] == "H"):
            sysm.constraints.append((a, b, p[0]))
        else:
            sysm.bonds.append((a, b, p[0], p[1]))
    # angles
    for j in range(n):
        if is_water[j]:
            continue
        for i, k in itertools.combinations(nbr[j], 2):
            p = ff.angle_params(types[i], types[j], types[k])
            if p is None:
                raise KeyError(f"no angle parameters for {types[i]}-{types[j]}-{types[k]}")
            sysm.angles.append((i, j, k, p[0], p[1]))
    # proper torsions, every path i-j-k-l over the bond j-k
    for j, k in bonds:
        for i in nbr[j]:
            if i == k:
                continue
            for l in nbr[k]:
                if l in (j, i):
                    continue
                d = ff.proper_params(types[i], types[j], types[k], types[l])
                if d is None:
                    continue
                for per, ph, kk in zip(d.periodicity, d.phase, d.k):
                    if kk != 0:
                        sysm.torsions.append((i, j, k, l, per, ph, kk))
    # improper torsions: every atom with three or more neighbors
    for c in range(n):
        if len(nbr[c]) < 3:
            continue
        for trio in itertools.combinations(nbr[c], 3):
            m = _match_improper(ff, c, trio, types, elements, [atoms[x][0] for x in range(n)], tmpl_index)
            if m is None:
                continue
            a1, a2, a3, a4, d = m
            for per, ph, kk in zip(d.periodicity, d.phase, d.k):
                if kk != 0:
                    sysm.torsions.append((a1, a2, a3, a4, per, ph, kk))
    # exclusions and 1-4 pairs from the bond graph
    excl = set()
    pairs14 = set()
    for i in range(n):
        one = set(nbr[i])
        two = {b for a in one for b in nbr[a]} - {i}
        three = {c for b in two for c in nbr[b]} - {i}
        for j in one | two:
            if j > i:
                excl.add((i, j))
        for j in three - one - two:
            if j > i:
                pairs14.add((i, j))
    for i, j in sorted(pairs14):
        excl.add((i, j))
        q = sysm.charge[i] * sysm.charge[j] * ff.coulomb14
        s = 0.5 * (sysm.sigma[i] + sysm.sigma[j])
        e = math.sqrt(sysm.epsilon[i] * sysm.epsilon[j]) * ff.lj14
        sysm.pairs14.append((i, j, q, s, e))
    sysm.exclusions = sorted(excl)
    # molecules: connected components of the bond graph (for the barostat)
    seen = [-1] * n
    starts = []
    for i in range(n):
        if seen[i] >= 0:
            continue
        stack = [i]
        seen[i] = i
        comp = []
        while stack:
            a = stack.pop()
            comp.append(a)
            for b in nbr[a]:
                if seen[b] < 0:
                    seen[b] = i
                    stack.append(b)
        if sorted(comp) != list(range(min(comp), max(comp) + 1)):
            raise ValueError("molecules must be contiguous in the atom order")
        starts.append(min(comp))
    sysm.molecules = sorted(starts) + [n]
    return sysm


def _match_improper(ff, center, trio, types, elements, resindex, tmpl_index):
    """OpenMM's improper matching: the last specific definition wins, else the
    first one with wildcards; atoms ordered by the Amber rules."""
    t1 = types[center]
    match = None
    for d in ff.impropers:
        wild = d.has_wildcard()
        if match is not None and wild:
            continue
        s1, s2, s3, s4 = d.types
        if not _in(t1, s1):
            continue
        for perm in itertools.permutations(trio):
            p2, p3, p4 = perm
            if not (_in(types[p2], s2) and _in(types[p3], s3) and _in(types[p4], s4)):
                continue
            a2, a3, a4 = p2, p3, p4
            key = lambda a: (resindex[a], tmpl_index[a])  # noqa: E731
            if d.ordering == "amber":
                if not wild:
                    if types[p2] == types[p4] and key(a2) > key(a4):
                        a2, a4 = a4, a2
                    if types[p3] == types[p4] and key(a3) > key(a4):
                        a3, a4 = a4, a3
                    if types[p2] == types[p3] and key(a2) > key(a3):
                        a2, a3 = a3, a2
                else:
                    if elements[a2] == elements[a4] and key(a2) > key(a4):
                        a2, a4 = a4, a2
                    if elements[a3] == elements[a4] and key(a3) > key(a4):
                        a3, a4 = a4, a3
                    if key(a2) > key(a3):
                        a2, a3 = a3, a2
                match = (a2, a3, center, a4, d)
            else:
                match = (center, p2, p3, p4, d)
            break
    return match
