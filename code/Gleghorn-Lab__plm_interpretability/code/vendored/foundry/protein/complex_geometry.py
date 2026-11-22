"""Geometry of a predicted binder-target complex, read from its PDB: the filters BindCraft and Bennett et al. apply.

The numbers a designed complex is screened on besides its confidences (ipTM, ipSAE, pAE live in `ipsae`):

- interface residues on each side (any heavy atom within `INTERFACE_CUTOFF_A` of the other chain) and the interface's
  buried solvent-accessible surface (dSASA, the SASA the two chains lose on binding, Lee-Richards with ProtOr radii);
- the binder's surface hydrophobicity (hydrophobic residues among those with relative SASA over `SURFACE_RELATIVE_SASA`,
  BindCraft's `Surface_Hydrophobicity`, filtered at 0.35), the interface's hydrophobic share and its lysine and methionine
  counts (BindCraft caps each at 3);
- hydrogen bonds across the interface (Baker-Hubbard geometry, BindCraft wants at least 3);
- the binder's secondary structure shares (P-SEA, BindCraft rejects loop over 90 percent), its radius of gyration and its
  CA RMSD to the same chain in another model, the binder folded alone (BindCraft `Binder_RMSD`, filtered at 3.5 A);
- the interface residues' mean pLDDT from the B factor column (BindCraft `i_pLDDT`) and the target chain's CA RMSD to the
  crop it was predicted from (BindCraft `Target_RMSD`: a prediction that moved the template is suspect);
- the binder's pose RMSD between two models of the complex, superposed on the target (Bennett et al. 2023 accept a design
  whose AF2 re-prediction lands within 1 A of the design model; here the disagreement between AF2 models);
- the binder's largest hydrophobic, positive and negative surface patches (the Therapeutic Antibody Profiler's patch
  metrics, Raybould et al. 2019, PNAS 116:4025: surface residues of one class whose side-chain centroids lie within
  `PATCH_NEIGHBOUR_A` form a patch, sized by its SASA) and its surface net charge; recorded, since de novo binders have
  no clinical range to be judged against yet.

Every function takes biotite atom arrays of heavy atoms; `complex_metrics` reads the files and returns one flat dictionary
whose keys the design pools use as columns. BindCraft's shape complementarity, packstat and Rosetta energies need Rosetta
and are not here. Biotite 0.41 and 1.x both serve.
"""

from __future__ import annotations

import biotite.structure as struc
import numpy as np

from pathlib import Path
from typing import Any
from biotite.structure.io.pdb import PDBFile


INTERFACE_CUTOFF_A = 4.5
SURFACE_RELATIVE_SASA = 0.25
HYDROPHOBIC = frozenset({"ALA", "VAL", "ILE", "LEU", "MET", "PHE", "TRP", "TYR"})
POSITIVE = frozenset({"ARG", "LYS"})
NEGATIVE = frozenset({"ASP", "GLU"})
PATCH_NEIGHBOUR_A = 7.5  # TAP's neighbourhood: two surface residues this close (side-chain centroids) share a patch
BACKBONE = frozenset({"N", "CA", "C", "O", "OXT"})
# Tien et al. 2013 (PLOS ONE 8:e80635), the theoretical maximum SASA of a residue in a Gly-X-Gly tripeptide, square angstrom.
MAXIMUM_SASA = {"ALA": 129.0, "ARG": 274.0, "ASN": 195.0, "ASP": 193.0, "CYS": 167.0, "GLN": 225.0, "GLU": 223.0, "GLY": 104.0,
                "HIS": 224.0, "ILE": 197.0, "LEU": 201.0, "LYS": 236.0, "MET": 224.0, "PHE": 240.0, "PRO": 159.0, "SER": 155.0,
                "THR": 172.0, "TRP": 285.0, "TYR": 263.0, "VAL": 174.0}


def read_heavy_atoms(path: str | Path) -> struc.AtomArray:
    """The first model's protein heavy atoms, with the B factor column (a predictor's pLDDT) as `b_factor`."""
    atoms = PDBFile.read(str(path)).get_structure(model=1, extra_fields=["b_factor"])
    atoms = atoms[struc.filter_amino_acids(atoms) & (atoms.element != "H")]
    if atoms.array_length() == 0:
        raise ValueError(f"{path}: no protein atoms")
    return atoms


def chain(atoms: struc.AtomArray, chain_id: str) -> struc.AtomArray:
    """One chain's atoms; raises when the chain is absent."""
    selected = atoms[atoms.chain_id == chain_id]
    if selected.array_length() == 0:
        raise ValueError(f"chain {chain_id} is not in the structure (chains {sorted(set(atoms.chain_id))})")
    return selected


def residue_sasa(atoms: struc.AtomArray) -> tuple[np.ndarray, np.ndarray]:
    """Per-residue SASA and relative SASA (against Tien et al.'s maxima) of `atoms` as given, in residue order."""
    per_atom = np.nan_to_num(struc.sasa(atoms, vdw_radii="ProtOr"), nan=0.0)  # (n_atoms,)
    starts = struc.get_residue_starts(atoms, add_exclusive_stop=True)  # (n_residues + 1,)
    absolute = np.array([per_atom[a:b].sum() for a, b in zip(starts[:-1], starts[1:], strict=True)])  # (n_residues,)
    names = atoms.res_name[starts[:-1]]  # (n_residues,)
    relative = absolute / np.array([MAXIMUM_SASA.get(name, np.nan) for name in names])  # (n_residues,)
    return absolute, relative  # (n_residues,) each


def interface_residue_ids(atoms: struc.AtomArray, binder_id: str, target_id: str, cutoff: float = INTERFACE_CUTOFF_A) -> tuple[list[int], list[int]]:
    """Residue ids of the binder and of the target with a heavy atom within `cutoff` of the other chain."""
    binder, target = chain(atoms, binder_id), chain(atoms, target_id)
    cell = struc.CellList(target, cell_size=cutoff)
    contacts = cell.get_atoms(binder.coord, radius=cutoff)  # (n_binder_atoms, k), -1 padded
    binder_touching = (contacts >= 0).any(axis=1)  # (n_binder_atoms,)
    target_touching = np.zeros(target.array_length(), dtype=bool)  # (n_target_atoms,)
    target_touching[np.unique(contacts[contacts >= 0])] = True
    return sorted(set(binder.res_id[binder_touching].tolist())), sorted(set(target.res_id[target_touching].tolist()))


def buried_sasa(atoms: struc.AtomArray, binder_id: str, target_id: str) -> dict[str, float]:
    """The SASA lost on binding, total and the binder's share, square angstrom."""
    binder, target = chain(atoms, binder_id), chain(atoms, target_id)
    binder_alone = residue_sasa(binder)[0].sum()
    target_alone = residue_sasa(target)[0].sum()
    bound = residue_sasa(binder + target)[0]  # (n_binder_residues + n_target_residues,)
    binder_bound = bound[: struc.get_residue_count(binder)].sum()
    return {"interface_dsasa": float(binder_alone + target_alone - bound.sum()), "binder_buried_sasa": float(binder_alone - binder_bound)}


def surface_hydrophobicity(binder: struc.AtomArray, threshold: float = SURFACE_RELATIVE_SASA) -> float:
    """Share of the binder's surface residues (relative SASA over `threshold`, folded alone) that are hydrophobic."""
    _, relative = residue_sasa(binder)
    names = binder.res_name[struc.get_residue_starts(binder)]  # (n_residues,)
    surface = relative > threshold  # (n_residues,)
    if not surface.any():
        return float("nan")
    return float(np.isin(names[surface], sorted(HYDROPHOBIC)).mean())


def surface_patches(binder: struc.AtomArray, threshold: float = SURFACE_RELATIVE_SASA, neighbour: float = PATCH_NEIGHBOUR_A) -> dict[str, float | int]:
    """The binder's largest hydrophobic, positive and negative surface patch (square angstrom of SASA) and its surface net charge.

    A residue is on the surface when its relative SASA exceeds `threshold`. Two surface residues of one class whose side-chain
    centroids (the CA atom when a residue has no side-chain atom) lie within `neighbour` are joined; a patch is a connected
    set and its size the sum of its residues' SASA, so a patch of small exposed residues counts less than one of large ones.
    """
    absolute, relative = residue_sasa(binder)
    starts = struc.get_residue_starts(binder, add_exclusive_stop=True)  # (n_residues + 1,)
    names = binder.res_name[starts[:-1]]  # (n_residues,)
    centroids = []
    for first, last in zip(starts[:-1], starts[1:], strict=True):
        residue = binder[first:last]
        side_chain = residue[~np.isin(residue.atom_name, sorted(BACKBONE))]
        centroids.append(side_chain.coord.mean(axis=0) if side_chain.array_length() else residue.coord[residue.atom_name == "CA"][0])
    coordinates = np.stack(centroids)  # (n_residues,3)
    surface = relative > threshold  # (n_residues,)
    patches: dict[str, float | int] = {}
    for label, members in (("hydrophobic", HYDROPHOBIC), ("positive", POSITIVE), ("negative", NEGATIVE)):
        candidates = np.flatnonzero(surface & np.isin(names, sorted(members)))  # (n_class,)
        largest = 0.0
        unseen = set(candidates.tolist())
        while unseen:
            queue = [unseen.pop()]
            component = []
            while queue:
                index = queue.pop()
                component.append(index)
                close = [other for other in unseen if np.linalg.norm(coordinates[index] - coordinates[other]) <= neighbour]
                unseen.difference_update(close)
                queue.extend(close)
            largest = max(largest, float(absolute[component].sum()))
        patches[f"largest_{label}_patch_sasa"] = largest
    patches["surface_net_charge"] = int(np.isin(names[surface], sorted(POSITIVE)).sum() - np.isin(names[surface], sorted(NEGATIVE)).sum())
    return patches


def interface_hydrogen_bonds(atoms: struc.AtomArray, binder_id: str, target_id: str) -> int:
    """Polar contacts between the chains: binder N or O atoms with a target N or O within 3.5 A, each binder atom once.

    A predicted model carries no hydrogens, so the donor-acceptor angle is unknown and this is the upper bound of the
    hydrogen bonds BindCraft counts with Rosetta.
    """
    binder, target = chain(atoms, binder_id), chain(atoms, target_id)
    binder_polar = binder[np.isin(binder.element, ["N", "O"])]
    target_polar = target[np.isin(target.element, ["N", "O"])]
    cell = struc.CellList(target_polar, cell_size=3.5)
    partners = cell.get_atoms(binder_polar.coord, radius=3.5)  # (n_binder_polar, k), -1 padded
    return int((partners >= 0).any(axis=1).sum())


def secondary_structure(binder: struc.AtomArray) -> dict[str, float]:
    """Helix, sheet and loop shares of the binder's residues (P-SEA)."""
    sse = struc.annotate_sse(binder)  # (n_residues,): "a", "b", "c" in biotite 1, `PSeaElement` integers in biotite 2
    if sse.size == 0:
        return {"helix_share": float("nan"), "sheet_share": float("nan"), "loop_share": float("nan")}
    if sse.dtype.kind == "U":
        helix, sheet, loop = "a", "b", "c"
    else:
        helix, sheet, loop = struc.PSeaElement.HELIX, struc.PSeaElement.STRAND, struc.PSeaElement.COIL
    return {"helix_share": float((sse == helix).mean()), "sheet_share": float((sse == sheet).mean()), "loop_share": float((sse == loop).mean())}


def superposition(fixed: struc.AtomArray, mobile: struc.AtomArray) -> Any:
    """The rigid transformation that puts `mobile` on `fixed`; its `apply` moves any atoms the same way.

    biotite 1 returns the fitted atoms and then the transformation, biotite 2 the transformation alone.
    """
    outcome = struc.superimpose(fixed, mobile)
    return outcome[1] if isinstance(outcome, tuple) else outcome


def ca_rmsd(reference: struc.AtomArray, mobile: struc.AtomArray) -> float:
    """CA RMSD of `mobile` on `reference` after superposition; the chains must have the same residue count."""
    fixed_ca = reference[reference.atom_name == "CA"]
    mobile_ca = mobile[mobile.atom_name == "CA"]
    if fixed_ca.array_length() != mobile_ca.array_length():
        raise ValueError(f"CA counts differ: {fixed_ca.array_length()} and {mobile_ca.array_length()}")
    return float(struc.rmsd(fixed_ca, superposition(fixed_ca, mobile_ca).apply(mobile_ca)))


def pose_rmsd(reference: struc.AtomArray, mobile: struc.AtomArray, binder_id: str = "B", target_id: str = "A") -> float:
    """CA RMSD of the binder between two models of the same complex after superposing the models on their target chains.

    The binder is not fitted on its own, so a binder that moved on the target counts in full: Bennett et al.'s
    design-to-prediction RMSD, and the agreement between two predictors or AF2 models of one design.
    """
    fixed_target = reference[(reference.chain_id == target_id) & (reference.atom_name == "CA")]
    mobile_target = mobile[(mobile.chain_id == target_id) & (mobile.atom_name == "CA")]
    if fixed_target.array_length() != mobile_target.array_length():
        raise ValueError(f"target CA counts differ: {fixed_target.array_length()} and {mobile_target.array_length()}")
    transform = superposition(fixed_target, mobile_target)
    fixed_binder = reference[(reference.chain_id == binder_id) & (reference.atom_name == "CA")]
    mobile_binder = transform.apply(mobile[(mobile.chain_id == binder_id) & (mobile.atom_name == "CA")])
    if fixed_binder.array_length() != mobile_binder.array_length():
        raise ValueError(f"binder CA counts differ: {fixed_binder.array_length()} and {mobile_binder.array_length()}")
    return float(struc.rmsd(fixed_binder, mobile_binder))


def complex_metrics(structure: str | Path, binder_id: str = "B", target_id: str = "A", alone: str | Path | None = None,
                    alone_id: str | None = None, target_reference: str | Path | None = None,
                    other_models: tuple[str | Path, ...] = ()) -> dict[str, float | int]:
    """Every geometry number of one complex, and the binder's RMSD to `alone` (the binder predicted by itself) when given.

    `alone_id` names the binder's chain in `alone`; by default its first chain (a single-chain prediction).
    `target_reference` is the target's input structure (its first chain), for the target chain's RMSD to it.
    `other_models` are other predictions of the same complex (same chains); `model_pose_rmsd` is the largest binder pose
    RMSD to any of them, the disagreement between the models.
    """
    atoms = read_heavy_atoms(structure)
    binder = chain(atoms, binder_id)
    target = chain(atoms, target_id)
    binder_interface, target_interface = interface_residue_ids(atoms, binder_id, target_id)
    interface_atoms = atoms[((atoms.chain_id == binder_id) & np.isin(atoms.res_id, binder_interface)) | ((atoms.chain_id == target_id) & np.isin(atoms.res_id, target_interface))]
    names_by_id = {int(res_id): name for res_id, name in zip(binder.res_id, binder.res_name, strict=True)}
    interface_names = [names_by_id[res_id] for res_id in binder_interface]
    metrics: dict[str, float | int] = {
        "interface_binder_residues": len(binder_interface), "interface_target_residues": len(target_interface),
        "interface_hydrophobic_share": float(np.mean([name in HYDROPHOBIC for name in interface_names])) if interface_names else float("nan"),
        "interface_lysines": sum(name == "LYS" for name in interface_names), "interface_methionines": sum(name == "MET" for name in interface_names),
        "interface_hbonds": interface_hydrogen_bonds(atoms, binder_id, target_id),
        "interface_plddt": float(interface_atoms.b_factor[interface_atoms.atom_name == "CA"].mean()) if interface_atoms.array_length() else float("nan"),
        "surface_hydrophobicity": surface_hydrophobicity(binder),
        "radius_of_gyration": float(struc.gyration_radius(binder)),
        **surface_patches(binder), **buried_sasa(atoms, binder_id, target_id), **secondary_structure(binder),
    }
    if alone is not None:
        alone_atoms = read_heavy_atoms(alone)
        alone_chain = chain(alone_atoms, alone_atoms.chain_id[0] if alone_id is None else alone_id)
        metrics["binder_alone_rmsd"] = ca_rmsd(binder, alone_chain)
        metrics["binder_alone_plddt"] = float(alone_chain.b_factor[alone_chain.atom_name == "CA"].mean())
    if target_reference is not None:
        reference = read_heavy_atoms(target_reference)
        metrics["target_rmsd"] = ca_rmsd(chain(reference, reference.chain_id[0]), target)
    if other_models:
        metrics["model_pose_rmsd"] = max(pose_rmsd(atoms, read_heavy_atoms(other), binder_id, target_id) for other in other_models)
    return metrics
