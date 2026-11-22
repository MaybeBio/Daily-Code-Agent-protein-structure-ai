"""Water boxes, solvation and ions.

A box is filled with rigid waters on a cubic lattice at the target density,
each turned at random; the engine then relaxes it (minimization, then NPT).
A solute is solvated by tiling a water box around it and removing the waters
that overlap it; ions replace the waters farthest from the solute.
"""

from __future__ import annotations

import math

import numpy as np

from .forcefield import ForceField
from .pdb import Atom, Residue, Structure

AVOGADRO = 6.02214076e23
WATER_MASS = 18.01528  # g/mol


def water_geometry(ff: ForceField) -> tuple[float, float, float]:
    """d(O-H), d(H-H) and the H-O-H angle of the force field's water."""
    t = ff.templates["HOH"]
    to = next(a[1] for a in t.atoms if a[0] == "O")
    th = next(a[1] for a in t.atoms if a[0] == "H1")
    r0, _ = ff.bond_params(to, th)
    angle, _ = ff.angle_params(th, to, th)
    return r0, 2 * r0 * math.sin(angle / 2), angle


def _random_rotation(rng):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def _water_atoms(geom):
    doh, _, angle = geom
    h = angle / 2
    return np.array([[0, 0, 0], [doh * math.sin(h), doh * math.cos(h), 0], [-doh * math.sin(h), doh * math.cos(h), 0]])


def waters_per_nm3(density_g_cm3: float) -> float:
    return density_g_cm3 / WATER_MASS * AVOGADRO * 1e-21


def water_box(ff: ForceField, n_waters: int, density=0.997, seed=1) -> Structure:
    """n waters on a cubic lattice in a cube of the given density (g/cm^3)."""
    rng = np.random.default_rng(seed)
    L = (n_waters / waters_per_nm3(density)) ** (1 / 3)
    m = math.ceil(n_waters ** (1 / 3))
    a = L / m
    sites = [(i, j, k) for i in range(m) for j in range(m) for k in range(m)]
    rng.shuffle(sites)
    local = _water_atoms(water_geometry(ff))
    residues = []
    for w, (i, j, k) in enumerate(sorted(sites[:n_waters])):
        c = (np.array([i, j, k]) + 0.5) * a
        xyz = c + local @ _random_rotation(rng).T
        residues.append(Residue("HOH", "W", w + 1, [Atom("O", "O", xyz[0]), Atom("H1", "H", xyz[1]), Atom("H2", "H", xyz[2])]))
    return Structure(residues, np.array([L, L, L]))


def solvate(solute: Structure, ff: ForceField, charge: int, padding=1.0, water: Structure | None = None, min_dist=0.24, seed=1,
            positive_ion="NA", negative_ion="CL", neutralize=True, molar=0.0) -> Structure:
    """The solute centered in a cubic box with at least `padding` nm of water
    on every side; `water` (an equilibrated box) is tiled, or a lattice box is
    used. `charge`: the solute's net charge (from its parameters)."""
    xyz = np.array([a.xyz for a in solute.atoms()])
    size = (xyz.max(0) - xyz.min(0)).max() + 2 * padding
    box = np.array([size, size, size])
    shift = box / 2 - (xyz.max(0) + xyz.min(0)) / 2
    if water is None:
        n = int(round(waters_per_nm3(0.997) * size**3))
        water = water_box(ff, n, seed=seed)
    wb = water.box
    reps = np.ceil(box / wb).astype(int)
    cand = []
    for r in water.residues:
        o = r.atoms[0].xyz % wb
        local = np.array([a.xyz for a in r.atoms]) - r.atoms[0].xyz
        for i in range(reps[0]):
            for j in range(reps[1]):
                for k in range(reps[2]):
                    oo = o + wb * np.array([i, j, k])
                    if np.all(oo < box):
                        cand.append(oo + local)
    cand = np.array(cand)  # (n, 3, 3)
    solute_xyz = xyz + shift
    # remove waters near the solute (periodic distances) and pairs too close across the tiling seam
    keep = np.ones(len(cand), bool)
    for c in range(0, len(cand), 2000):
        blk = cand[c : c + 2000]
        d = blk[:, :, None, :] - solute_xyz[None, None, :, :]
        d -= box * np.round(d / box)
        dmin = np.sqrt((d**2).sum(-1)).min(axis=(1, 2))
        keep[c : c + 2000] = dmin > min_dist
    cand = cand[keep]
    o = cand[:, 0]
    drop = np.zeros(len(cand), bool)
    # shortcut: O(n^2) seam check, fine for a few thousand waters; use a cell list for boxes of tens of thousands
    for a in range(len(cand)):  # seam: O-O closer than 0.23 nm
        if drop[a]:
            continue
        d = o - o[a]
        d -= box * np.round(d / box)
        r = np.sqrt((d**2).sum(1))
        close = np.where((r < 0.23) & (np.arange(len(cand)) > a))[0]
        drop[close] = True
    cand = cand[~drop]
    # ions: neutralize, plus a salt concentration
    n_pos = n_neg = 0
    if neutralize:
        if charge > 0:
            n_neg += charge
        else:
            n_pos -= charge
    if molar > 0:
        pairs = int(round(molar * len(cand) / 55.5))
        n_pos += pairs
        n_neg += pairs
    rng = np.random.default_rng(seed)
    d = cand[:, 0, None, :] - solute_xyz[None, :, :]
    d -= box * np.round(d / box)
    far = np.sqrt((d**2).sum(-1)).min(1)
    candidates = np.argsort(-far)[: max(4 * (n_pos + n_neg), n_pos + n_neg)]
    chosen = rng.choice(candidates, size=n_pos + n_neg, replace=False) if n_pos + n_neg else []
    ions = [(positive_ion, cand[i, 0]) for i in chosen[:n_pos]] + [(negative_ion, cand[i, 0]) for i in chosen[n_pos:]]
    chosen_set = set(chosen)
    waters = [cand[i] for i in range(len(cand)) if i not in chosen_set]
    residues = []
    for r in solute.residues:
        residues.append(Residue(r.name, r.chain, r.number, [Atom(a.name, a.element, a.xyz + shift) for a in r.atoms]))
    for k, (name, p) in enumerate(ions):
        residues.append(Residue(name, "I", k + 1, [Atom(name, name[0] + name[1:].lower(), p)]))
    for k, w in enumerate(waters):
        residues.append(Residue("HOH", "W", k + 1, [Atom("O", "O", w[0]), Atom("H1", "H", w[1]), Atom("H2", "H", w[2])]))
    return Structure(residues, box)
