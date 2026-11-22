"""Input sanitization, patch precomputation, matching, and postprocessing for ``surface_decompose``."""

from __future__ import annotations

import dataclasses
import logging
import pathlib
from typing import Any, Sequence

import gemmi
import numpy as np

from .common import (
    BACKBONE_ATOMS,
    C2_SYMMETRY_SWAPS,
    CANONICAL_AA3_TO_1,
    WATERS,
    coupled_kabsch_sidechain_rmsd,
    encoding_tables,
    extract_token_ca_coords,
    format_score,
    kabsch_superpose,
    normalize_blank_chain_ids,
    write_gemmi_pdb,
    write_protenix_pdb,
)

logger = logging.getLogger("surface_decompose")

SCORE_COLUMNS: tuple[str, ...] = (
    "target",
    "target_chain",
    "attempt",
    "center_residue",
    "covered_residues",
    "sequence",
    "rfd4_motif_rmsd",
    "sc_rmsd",
    "motif_rmsd",
    "mean_plddt",
    "motif_plddt",
    "mean_pae",
    "ptm",
    "failure",
)

_FAILURE_ORDER: tuple[str, ...] = (
    "f_sc_rmsd",
    "f_motif_rmsd",
    "f_plddt",
    "f_pae",
)


@dataclasses.dataclass
class SanitizedResidue:
    """Single sanitized canonical polymer residue from Stage 1."""

    res_token: str
    chain_id: str
    seqid_num: int
    icode: str
    res_name: str
    aa_idx: int
    polymer_seq_idx: int
    atom_coords: dict[str, np.ndarray]
    pos37_sc: np.ndarray
    mask37_sc: np.ndarray
    sc_atom_names: tuple[str, ...]
    has_cb: bool
    is_interface: bool = False
    is_surface: bool = False


@dataclasses.dataclass
class PatchSpec:
    """Lightweight CPU descriptor for one valid seed's surface patch."""

    seed_token: str
    member_tokens: tuple[str, ...]
    valid_seed_tokens: tuple[str, ...]
    member_residues: tuple[SanitizedResidue, ...]
    pos_raw: np.ndarray
    pos_centered: np.ndarray
    mask37: np.ndarray
    aa_idx: np.ndarray
    polymer_seq_idx: np.ndarray
    c_crd_offset: np.ndarray


@dataclasses.dataclass
class ChainContext:
    """Per-chain surface/patch precomputation state and filter counts."""

    target_name: str
    chain_id: str
    residues: list[SanitizedResidue]
    valid_seeds: list[str]
    patch_members: dict[str, tuple[SanitizedResidue, ...]] = dataclasses.field(
        default_factory=dict
    )
    patches: dict[str, PatchSpec] = dataclasses.field(default_factory=dict)
    n_polymer: int = 0
    n_non_gly_cb: int = 0
    n_interface_excluded: int = 0
    n_surface: int = 0
    n_valid_seeds: int = 0


@dataclasses.dataclass
class TargetPlan:
    """Sanitized target structure and per-chain decomposition contexts."""

    target_name: str
    pdb_path: pathlib.Path
    sanitized_structure: gemmi.Structure
    chain_residues: dict[str, list[SanitizedResidue]] = dataclasses.field(
        default_factory=dict
    )
    chains: list[ChainContext] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class RFD4AttemptPostprocessResult:
    """Result of matching, writing, and pre-fold filtering one RFD4 sample."""

    aa_pred_idx: np.ndarray
    sequence: str
    coors_ang: np.ndarray
    atom_mask: np.ndarray
    col_ind: np.ndarray | None
    rfd4_motif_rmsd: float | None
    r_rfd4: np.ndarray | None
    t_rfd4: np.ndarray | None
    failure: str | None
    score_row: list[Any] | None


@dataclasses.dataclass
class ProtenixAttemptPostprocessResult:
    """Result of scoring, filtering, and saving one Protenix prediction."""

    sc_rmsd: float
    motif_rmsd: float
    mean_plddt: float
    motif_plddt: float
    mean_pae: float
    ptm: float
    failure_str: str
    accepted: bool
    score_row: list[Any]


def sanitize_target_structure(
    pdb_path: pathlib.Path, interface_cutoff: float
) -> TargetPlan:
    """Sanitize model 0 of ``pdb_path`` and mark cross-chain CB interface residues."""
    st = gemmi.read_structure(str(pdb_path))
    if len(st) == 0:
        raise ValueError(f"PDB structure has no models: {pdb_path}")

    # Retain only model 0 for downstream sanitization and seeds export.
    for model_idx in range(len(st) - 1, 0, -1):
        del st[model_idx]

    st.setup_entities()
    st.assign_subchains(force=False)
    model = st[0]
    normalize_blank_chain_ids(model)

    _, token_to_idx, token_atoms, _ = encoding_tables()
    chain_residues: dict[str, list[SanitizedResidue]] = {}
    empty_chain_indices: list[int] = []

    for chain_idx, chain in enumerate(model):
        poly = chain.get_polymer()
        poly_type = poly.check_polymer_type()
        if poly_type not in (
            gemmi.PolymerType.PeptideL,
            gemmi.PolymerType.PeptideD,
        ):
            empty_chain_indices.append(chain_idx)
            continue

        # Convert polymer MSE -> MET prior to stripping HETATM records.
        for res in poly:
            if res.name.strip() == "MSE":
                res.name = "MET"
                res.het_flag = "A"
                for atom in res:
                    if atom.name.strip() == "SE":
                        atom.name = "SD"
                        atom.element = gemmi.Element("S")

        chain_id = chain.name
        retained_residues: list[SanitizedResidue] = []
        keep_res_indices: set[int] = set()
        polymer_seq_idx = 0
        saw_skipped_residue = False

        for res_idx, res in enumerate(chain):
            rname = res.name.strip()
            if (
                rname in WATERS
                or res.het_flag == "H"
                or rname not in CANONICAL_AA3_TO_1
            ):
                if retained_residues:
                    saw_skipped_residue = True
                continue

            # Strip H/D atoms and keep first altloc per atom name in file order.
            seen_atoms: set[str] = set()
            keep_atom_indices: set[int] = set()
            atom_coords: dict[str, np.ndarray] = {}
            for atom_idx, atom in enumerate(res):
                if atom.element.name in {"H", "D"}:
                    continue
                aname = atom.name.strip()
                if not aname or aname in seen_atoms:
                    continue
                coord = np.array(
                    [atom.pos.x, atom.pos.y, atom.pos.z], dtype=np.float64
                )
                if not np.isfinite(coord).all():
                    continue
                seen_atoms.add(aname)
                atom.altloc = "\x00"
                keep_atom_indices.add(atom_idx)
                atom_coords[aname] = coord

            if not keep_atom_indices:
                if retained_residues:
                    saw_skipped_residue = True
                continue

            for atom_idx in range(len(res) - 1, -1, -1):
                if atom_idx not in keep_atom_indices:
                    del res[atom_idx]

            if retained_residues:
                prev_res = retained_residues[-1]
                has_peptide_bond = (
                    not saw_skipped_residue
                    and "C" in prev_res.atom_coords
                    and "N" in atom_coords
                    and float(
                        np.linalg.norm(
                            prev_res.atom_coords["C"] - atom_coords["N"]
                        )
                    )
                    < 2.0
                )
                polymer_seq_idx += 1 if has_peptide_bond else 2
            saw_skipped_residue = False

            slots = token_atoms[rname]
            pos37_sc = np.full((37, 3), np.nan, dtype=np.float32)
            mask37_sc = np.zeros(37, dtype=bool)
            sc_names: list[str] = []
            for s, aname in enumerate(slots):
                if not aname or aname in BACKBONE_ATOMS:
                    continue
                if aname in atom_coords:
                    pos37_sc[s] = atom_coords[aname].astype(np.float32)
                    mask37_sc[s] = True
                    sc_names.append(aname)

            seqid_num = int(res.seqid.num)
            icode = res.seqid.icode.strip()
            res_token = f"{chain_id}{seqid_num}{icode}"
            retained_residues.append(
                SanitizedResidue(
                    res_token=res_token,
                    chain_id=chain_id,
                    seqid_num=seqid_num,
                    icode=icode,
                    res_name=rname,
                    aa_idx=token_to_idx[rname],
                    polymer_seq_idx=polymer_seq_idx,
                    atom_coords=atom_coords,
                    pos37_sc=pos37_sc,
                    mask37_sc=mask37_sc,
                    sc_atom_names=tuple(sc_names),
                    has_cb=("CB" in atom_coords),
                )
            )
            keep_res_indices.add(res_idx)

        if not retained_residues:
            empty_chain_indices.append(chain_idx)
            continue

        for res_idx in range(len(chain) - 1, -1, -1):
            if res_idx not in keep_res_indices:
                del chain[res_idx]

        chain_residues.setdefault(chain_id, []).extend(retained_residues)

    for chain_idx in sorted(empty_chain_indices, reverse=True):
        del model[chain_idx]

    # Mark cross-chain CB-CB interface residues (< interface_cutoff).
    chain_ids = list(chain_residues.keys())
    if len(chain_ids) > 1 and interface_cutoff > 0.0:
        cb_by_chain: dict[str, tuple[list[SanitizedResidue], np.ndarray]] = {}
        for cid in chain_ids:
            cb_res = [
                r
                for r in chain_residues[cid]
                if r.res_name != "GLY" and r.has_cb
            ]
            cb_xyz = (
                np.stack([r.atom_coords["CB"] for r in cb_res], axis=0)
                if cb_res
                else np.zeros((0, 3), dtype=np.float64)
            )
            cb_by_chain[cid] = (cb_res, cb_xyz)

        for cid in chain_ids:
            cb_res, cb_xyz = cb_by_chain[cid]
            if len(cb_res) == 0:
                continue
            other_arrays = [
                cb_by_chain[ocid][1]
                for ocid in chain_ids
                if ocid != cid and len(cb_by_chain[ocid][1]) > 0
            ]
            if not other_arrays:
                continue
            other_cb = np.concatenate(other_arrays, axis=0)
            dists = np.linalg.norm(
                cb_xyz[:, None, :] - other_cb[None, :, :], axis=-1
            )
            is_iface = (dists < interface_cutoff).any(axis=1)
            for idx, flag in enumerate(is_iface):
                if flag:
                    cb_res[idx].is_interface = True

    return TargetPlan(
        target_name=pdb_path.stem,
        pdb_path=pdb_path,
        sanitized_structure=st,
        chain_residues=chain_residues,
    )


def precompute_chain_patches(
    target_name: str,
    chain_id: str,
    residues: list[SanitizedResidue],
    *,
    cutoff: float,
    min_num_patch: int,
) -> ChainContext:
    """Run isolated-chain Shrake-Rupley surface test and precompute sidechain patches."""
    from rfd4fx.rfd4_input import is_surface

    n_polymer = len(residues)
    occluder_pts = [
        r.atom_coords[an]
        for r in residues
        for an in BACKBONE_ATOMS
        if an in r.atom_coords
    ]
    occluders = (
        np.stack(occluder_pts, axis=0).astype(np.float64)
        if occluder_pts
        else np.zeros((0, 3), dtype=np.float64)
    )

    surface_candidates = [
        r
        for r in residues
        if r.res_name != "GLY" and r.has_cb and len(r.sc_atom_names) >= 1
    ]
    n_non_gly_cb = len(surface_candidates)

    if surface_candidates:
        cb_coords = np.stack(
            [r.atom_coords["CB"] for r in surface_candidates], axis=0
        ).astype(np.float64)
        exposed = is_surface(
            cb_coords, occluders, radius=4.0, n_points=64, threshold=0.2
        )
        for k, flag in enumerate(exposed):
            surface_candidates[k].is_surface = bool(flag)

    exposed_candidates = [r for r in surface_candidates if r.is_surface]
    n_surface = len(exposed_candidates)
    n_interface_excluded = sum(1 for r in exposed_candidates if r.is_interface)

    # Precompute heavy and sidechain coordinate blocks per exposed candidate.
    heavy_blocks = [
        np.stack(list(r.atom_coords.values()), axis=0).astype(np.float64)
        for r in exposed_candidates
    ]
    sc_blocks = [
        np.stack(
            [r.atom_coords[an] for an in r.sc_atom_names], axis=0
        ).astype(np.float64)
        for r in exposed_candidates
    ]

    valid_seeds: list[str] = []
    patch_members: dict[str, tuple[SanitizedResidue, ...]] = {}
    for i, seed_res in enumerate(exposed_candidates):
        s_heavy = heavy_blocks[i]
        members: list[SanitizedResidue] = []
        for j, cand_res in enumerate(exposed_candidates):
            u_sc = sc_blocks[j]
            min_dist = float(
                np.linalg.norm(
                    s_heavy[:, None, :] - u_sc[None, :, :], axis=-1
                ).min()
            )
            if min_dist < cutoff:
                members.append(cand_res)
        if (not seed_res.is_interface) and len(members) >= min_num_patch:
            valid_seeds.append(seed_res.res_token)
            patch_members[seed_res.res_token] = tuple(members)

    return ChainContext(
        target_name=target_name,
        chain_id=chain_id,
        residues=residues,
        valid_seeds=valid_seeds,
        patch_members=patch_members,
        patches={},
        n_polymer=n_polymer,
        n_non_gly_cb=n_non_gly_cb,
        n_interface_excluded=n_interface_excluded,
        n_surface=n_surface,
        n_valid_seeds=len(valid_seeds),
    )


def build_patch_specs(plans: list[TargetPlan]) -> int:
    """Populate CPU-only ``PatchSpec`` descriptors across all valid seeds and return ``M_max``."""
    m_max = 0
    for plan in plans:
        for ctx in plan.chains:
            valid_seed_set = set(ctx.valid_seeds)
            for seed_token in ctx.valid_seeds:
                members = ctx.patch_members[seed_token]
                member_tokens = tuple(r.res_token for r in members)
                valid_seed_tokens = tuple(
                    r.res_token for r in members if r.res_token in valid_seed_set
                )
                pos_raw = np.stack(
                    [r.pos37_sc for r in members], axis=0
                ).astype(np.float32)
                mask37 = np.stack(
                    [r.mask37_sc for r in members], axis=0
                ).astype(bool)
                aa_idx = np.array(
                    [r.aa_idx for r in members], dtype=np.int32
                )
                polymer_seq_idx = np.array(
                    [r.polymer_seq_idx for r in members], dtype=np.int32
                )
                c_crd_offset = pos_raw[mask37].mean(axis=0).astype(np.float64)
                pos_centered = np.where(
                    mask37[..., None],
                    pos_raw - c_crd_offset.astype(np.float32),
                    np.nan,
                ).astype(np.float32)
                ctx.patches[seed_token] = PatchSpec(
                    seed_token=seed_token,
                    member_tokens=member_tokens,
                    valid_seed_tokens=valid_seed_tokens,
                    member_residues=members,
                    pos_raw=pos_raw,
                    pos_centered=pos_centered,
                    mask37=mask37,
                    aa_idx=aa_idx,
                    polymer_seq_idx=polymer_seq_idx,
                    c_crd_offset=c_crd_offset,
                )
                m_max = max(m_max, len(members))
    return m_max


def describe_zero_seed_stage(ctx: ChainContext) -> str:
    """Return human-readable explanation of why ``ctx`` yielded zero seeds."""
    if ctx.n_polymer == 0:
        return "sanitization (0 retained canonical residues)"
    if ctx.n_non_gly_cb == 0:
        return "non-GLY CB filter (0 eligible residues)"
    if ctx.n_surface == 0:
        return "Shrake-Rupley surface test (0 exposed residues)"
    if ctx.n_surface - ctx.n_interface_excluded == 0:
        return "interface exclusion (all exposed residues on inter-chain interface)"
    return "min_num_patch filter (no non-interface surface patch met min_num_patch)"


_describe_zero_seed_stage = describe_zero_seed_stage


def prepare_target_plans(
    pdb_paths: Sequence[pathlib.Path],
    *,
    interface_cutoff: float,
    cutoff: float,
    min_num_patch: int,
    log: logging.Logger | None = None,
) -> tuple[list[TargetPlan], int]:
    """Sanitize PDBs, compute surface patches/specs, and return ``(plans, M_max)``."""
    active_log = logger if log is None else log
    plans: list[TargetPlan] = []
    for pdb_path in pdb_paths:
        plan = sanitize_target_structure(pdb_path, interface_cutoff)
        for chain_id, residues in plan.chain_residues.items():
            ctx = precompute_chain_patches(
                plan.target_name,
                chain_id,
                residues,
                cutoff=cutoff,
                min_num_patch=min_num_patch,
            )
            active_log.info(
                "Target %s chain %s: n_polymer=%d n_non_gly_cb=%d "
                "n_interface_excluded=%d n_surface=%d n_valid_seeds=%d",
                plan.target_name,
                chain_id,
                ctx.n_polymer,
                ctx.n_non_gly_cb,
                ctx.n_interface_excluded,
                ctx.n_surface,
                ctx.n_valid_seeds,
            )
            if ctx.n_valid_seeds == 0:
                active_log.warning(
                    "Target %s chain %s has 0 valid seeds (emptied at %s); skipping.",
                    plan.target_name,
                    chain_id,
                    describe_zero_seed_stage(ctx),
                )
            plan.chains.append(ctx)
        plans.append(plan)
    m_max = build_patch_specs(plans)
    return plans, m_max


def compile_patch_batch(base_rfd4_input: Any, patch: PatchSpec, n_pad: int) -> Any:
    """Compile an unindexed C_CRD motif batch padded to ``n_pad`` tokens."""
    return (
        base_rfd4_input.add_unindexed_motif(
            patch.pos_raw,
            patch.aa_idx,
            patch.mask37,
            residue_index=patch.polymer_seq_idx,
            chain_index=np.zeros(len(patch.member_residues), np.float32),
            fixed=True,
            ordered=True,
            target_chain="A",
        )
        .pad_to_nearest(n_pad)
        .to_batch()
    )


def match_rfd4_patch(
    patch: PatchSpec,
    aa_pred_idx: np.ndarray,
    coors_ang: np.ndarray,
    atom_mask: np.ndarray,
) -> tuple[np.ndarray | None, float | None, np.ndarray | None, np.ndarray | None]:
    """Assign RFD4 scaffold residues 1-to-1 to ``patch`` in C_CRD frame and fit Kabsch."""
    from scipy.optimize import linear_sum_assignment

    aa_pred = np.asarray(aa_pred_idx, dtype=np.int32).reshape(-1)
    coords = np.asarray(coors_ang, dtype=np.float64)
    mask = np.asarray(atom_mask, dtype=bool)
    num_aa = aa_pred.shape[0]
    m_count = len(patch.member_residues)

    if num_aa < m_count:
        return None, None, None, None

    # Quick AA-identity multiplicity feasibility check.
    req_vals, req_counts = np.unique(patch.aa_idx, return_counts=True)
    for aa_val, req_cnt in zip(req_vals, req_counts):
        if int((aa_pred == aa_val).sum()) < int(req_cnt):
            return None, None, None, None

    _, _, token_atoms, atom_slot_map = encoding_tables()
    cost = np.full((m_count, num_aa), np.inf, dtype=np.float64)

    for m, res in enumerate(patch.member_residues):
        slot_map = atom_slot_map[res.res_name]
        sc_names = res.sc_atom_names
        slots_id = np.array([slot_map[an] for an in sc_names], dtype=np.int32)
        q_centered = patch.pos_centered[m, slots_id].astype(np.float64)

        swaps = C2_SYMMETRY_SWAPS.get(res.res_name, ())
        if swaps:
            swap_dict: dict[str, str] = {}
            for a, b in swaps:
                swap_dict[a] = b
                swap_dict[b] = a
            slots_sw = np.array(
                [slot_map[swap_dict.get(an, an)] for an in sc_names],
                dtype=np.int32,
            )
        else:
            slots_sw = None

        cand_js = np.flatnonzero(aa_pred == res.aa_idx)
        for j_raw in cand_js:
            j = int(j_raw)
            if not bool(mask[j, slots_id].all()):
                continue
            pts_id = coords[j, slots_id]
            if not (
                np.isfinite(pts_id).all()
                and (np.abs(pts_id).sum(axis=-1) > 0.0).all()
            ):
                continue
            err = float(np.sum((pts_id - q_centered) ** 2))
            if slots_sw is not None:
                if bool(mask[j, slots_sw].all()):
                    pts_sw = coords[j, slots_sw]
                    if (
                        np.isfinite(pts_sw).all()
                        and (np.abs(pts_sw).sum(axis=-1) > 0.0).all()
                    ):
                        err_sw = float(np.sum((pts_sw - q_centered) ** 2))
                        err = min(err, err_sw)
            cost[m, j] = err

        if not np.isfinite(cost[m]).any():
            return None, None, None, None

    try:
        row_ind, col_ind = linear_sum_assignment(cost)
    except ValueError:
        return None, None, None, None

    if len(row_ind) != m_count or not np.isfinite(cost[row_ind, col_ind]).all():
        return None, None, None, None

    # Reorder col_ind to match patch.member_residues 0..M-1.
    ordered_cols = np.empty(m_count, dtype=np.int32)
    ordered_cols[row_ind] = col_ind

    pred_atom_dicts: list[dict[str, np.ndarray]] = []
    for m, res in enumerate(patch.member_residues):
        j = int(ordered_cols[m])
        slots = token_atoms[res.res_name]
        d: dict[str, np.ndarray] = {}
        for s, an in enumerate(slots):
            if not an or not bool(mask[j, s]):
                continue
            pt = coords[j, s]
            if np.isfinite(pt).all() and float(np.abs(pt).sum()) > 0.0:
                d[an] = pt
        pred_atom_dicts.append(d)

    rmsd, r, t = coupled_kabsch_sidechain_rmsd(
        pred_atom_dicts, patch.member_residues
    )
    return ordered_cols, float(rmsd), r, t


def write_attempt_pdb(
    result: Any,
    out_file: pathlib.Path,
    *,
    col_ind: np.ndarray | None,
    R: np.ndarray | None,
    t: np.ndarray | None,
    c_crd_offset: np.ndarray,
) -> None:
    """Write target-aligned RFD4 attempt PDB with motif B-factor annotations."""
    if col_ind is None:
        result.save_pdb(
            out_file,
            offset=c_crd_offset,
            highlight_res_ids=(),
        )
    else:
        assert R is not None and t is not None
        result.save_pdb(
            out_file,
            R=R,
            t=t,
            highlight_res_ids=np.asarray(col_ind, dtype=np.int64) + 1,
        )


def write_success_pdb(
    writer: Any,
    out_file: pathlib.Path,
    *,
    coords_ang: np.ndarray,
    res_plddt: np.ndarray,
    atom_to_token_idx: np.ndarray,
    R: np.ndarray,
    t: np.ndarray,
) -> None:
    """Transform accepted Protenix coordinates onto target frame and save PDB."""
    write_protenix_pdb(
        writer,
        out_file,
        coords_ang=coords_ang,
        res_plddt=res_plddt,
        atom_to_token_idx=atom_to_token_idx,
        R=R,
        t=t,
    )


def write_seeds_pdb(
    sanitized_structure: gemmi.Structure,
    out_file: pathlib.Path,
    *,
    valid_seed_sets: dict[str, set[str]],
    seed_pass_counts: dict[str, dict[str, int]],
) -> None:
    """Write sanitized target PDB with B-factor ``-1.0`` (non-seed) or ``min(N, 999)``."""

    def _seed_b_factor(cid: str, res: gemmi.Residue) -> float:
        valid_set = valid_seed_sets.get(cid, set())
        counts = seed_pass_counts.get(cid, {})
        icode = res.seqid.icode.strip()
        res_token = f"{cid}{int(res.seqid.num)}{icode}"
        if res_token in valid_set:
            return float(min(int(counts.get(res_token, 0)), 999))
        return -1.0

    write_gemmi_pdb(
        sanitized_structure,
        out_file,
        residue_b_factor_fn=_seed_b_factor,
    )


def write_zero_design_seeds(
    plans: Sequence[TargetPlan], seeds_dir: pathlib.Path
) -> None:
    """Export baseline ``seeds/<target>.pdb`` files when no designs are sampled."""
    for plan in plans:
        valid_seed_sets = {
            ctx.chain_id: set(ctx.valid_seeds) for ctx in plan.chains
        }
        seed_pass_counts = {
            ctx.chain_id: {tok: 0 for tok in ctx.valid_seeds}
            for ctx in plan.chains
        }
        write_seeds_pdb(
            plan.sanitized_structure,
            seeds_dir / f"{plan.target_name}.pdb",
            valid_seed_sets=valid_seed_sets,
            seed_pass_counts=seed_pass_counts,
        )


def build_score_row(
    *,
    target_name: str,
    chain_id: str,
    attempt: int,
    center_residue: str,
    covered_str: str,
    sequence: str,
    rfd4_motif_rmsd: float | None,
    sc_rmsd: float | None = None,
    motif_rmsd: float | None = None,
    mean_plddt: float | None = None,
    motif_plddt: float | None = None,
    mean_pae: float | None = None,
    ptm: float | None = None,
    failure: str,
) -> list[Any]:
    """Format a 14-column CSV row matching ``SCORE_COLUMNS``."""
    return [
        target_name,
        chain_id,
        attempt,
        center_residue,
        covered_str,
        sequence,
        format_score(rfd4_motif_rmsd),
        format_score(sc_rmsd),
        format_score(motif_rmsd),
        format_score(mean_plddt),
        format_score(motif_plddt),
        format_score(mean_pae),
        format_score(ptm),
        failure,
    ]


def postprocess_rfd4_attempt(
    rfd4_res: Any,
    *,
    target_name: str,
    chain_id: str,
    attempt: int,
    center_residue: str,
    patch: PatchSpec,
    num_aa: int,
    f_rfd4_rmsd: float,
    attempt_pdb_path: pathlib.Path,
    covered_str: str | None = None,
) -> RFD4AttemptPostprocessResult:
    """Match RFD4 predictions to ``patch``, write attempt PDB, and apply pre-fold filter."""
    aa_pred_idx = rfd4_res.aa_idx(num_aa=num_aa)
    sequence = rfd4_res.sequence(num_aa=num_aa)
    coors_ang, atom_mask = rfd4_res.to_atom37(num_aa=num_aa)
    if covered_str is None:
        covered_str = ";".join(patch.member_tokens)

    col_ind, rfd4_motif_rmsd, r_rfd4, t_rfd4 = match_rfd4_patch(
        patch, aa_pred_idx, coors_ang, atom_mask
    )
    write_attempt_pdb(
        rfd4_res,
        attempt_pdb_path,
        col_ind=col_ind,
        R=r_rfd4,
        t=t_rfd4,
        c_crd_offset=patch.c_crd_offset,
    )

    failure: str | None = None
    score_row: list[Any] | None = None
    if col_ind is None:
        failure = "f_match"
        score_row = build_score_row(
            target_name=target_name,
            chain_id=chain_id,
            attempt=attempt,
            center_residue=center_residue,
            covered_str=covered_str,
            sequence=sequence,
            rfd4_motif_rmsd=None,
            failure=failure,
        )
    elif not (rfd4_motif_rmsd is not None and rfd4_motif_rmsd < f_rfd4_rmsd):
        failure = "f_rfd4_rmsd"
        score_row = build_score_row(
            target_name=target_name,
            chain_id=chain_id,
            attempt=attempt,
            center_residue=center_residue,
            covered_str=covered_str,
            sequence=sequence,
            rfd4_motif_rmsd=rfd4_motif_rmsd,
            failure=failure,
        )

    return RFD4AttemptPostprocessResult(
        aa_pred_idx=aa_pred_idx,
        sequence=sequence,
        coors_ang=coors_ang,
        atom_mask=atom_mask,
        col_ind=col_ind,
        rfd4_motif_rmsd=rfd4_motif_rmsd,
        r_rfd4=r_rfd4,
        t_rfd4=t_rfd4,
        failure=failure,
        score_row=score_row,
    )


def postprocess_protenix_attempt(
    protenix_res: Any,
    writer: Any,
    sample_coords_ang: np.ndarray,
    res_plddt: np.ndarray,
    atom_to_token_idx: np.ndarray,
    *,
    target_name: str,
    chain_id: str,
    attempt: int,
    center_residue: str,
    patch: PatchSpec,
    sequence: str,
    coors_ang: np.ndarray,
    col_ind: np.ndarray,
    rfd4_motif_rmsd: float,
    num_aa: int,
    f_sc_rmsd: float,
    f_motif_rmsd: float,
    f_plddt: float,
    f_pae: float,
    success_pdb_path: pathlib.Path,
    covered_str: str | None = None,
) -> ProtenixAttemptPostprocessResult:
    """Compute Protenix metrics, apply acceptance filters, and export accepted PDBs."""
    if covered_str is None:
        covered_str = ";".join(patch.member_tokens)

    atom_names = [str(an).strip() for an in writer.atom_array.atom_name]
    ca_coords = extract_token_ca_coords(
        sample_coords_ang, atom_names, atom_to_token_idx, num_aa
    )
    rfd4_ca = coors_ang[:, 1, :]
    sc_rmsd, _, _ = kabsch_superpose(ca_coords, rfd4_ca)

    prot_atom_dicts: list[dict[str, np.ndarray]] = []
    missing_prot_sc = False
    for m_idx, motif_res in enumerate(patch.member_residues):
        tok = int(col_ind[m_idx])
        atom_indices = np.flatnonzero(atom_to_token_idx == tok)
        atom_dict = {
            atom_names[int(ai)]: sample_coords_ang[int(ai)]
            for ai in atom_indices
        }
        if any(an not in atom_dict for an in motif_res.sc_atom_names):
            missing_prot_sc = True
        prot_atom_dicts.append(atom_dict)

    if missing_prot_sc:
        motif_rmsd = float("inf")
        r_prot = np.eye(3, dtype=np.float64)
        t_prot = np.zeros(3, dtype=np.float64)
    else:
        motif_rmsd, r_prot, t_prot = coupled_kabsch_sidechain_rmsd(
            prot_atom_dicts, patch.member_residues
        )

    mean_plddt = float(np.mean(res_plddt))
    motif_plddt = float(np.mean(res_plddt[col_ind]))
    pae_arr = np.asarray(protenix_res.pae, dtype=np.float64)
    if pae_arr.ndim == 3 and pae_arr.shape[0] == 1:
        pae_arr = pae_arr[0]
    mean_pae = float(np.mean(pae_arr * 32.0))
    ptm = float(np.asarray(protenix_res.ptm, dtype=np.float64).reshape(-1)[0])

    failures: list[str] = []
    if not (sc_rmsd < f_sc_rmsd):
        failures.append("f_sc_rmsd")
    if not (motif_rmsd < f_motif_rmsd):
        failures.append("f_motif_rmsd")
    if not (mean_plddt > f_plddt):
        failures.append("f_plddt")
    if not (mean_pae < f_pae):
        failures.append("f_pae")
    failure_str = ";".join(failures) if failures else "none"
    accepted = not failures

    if accepted:
        write_success_pdb(
            writer,
            success_pdb_path,
            coords_ang=sample_coords_ang,
            res_plddt=res_plddt,
            atom_to_token_idx=atom_to_token_idx,
            R=r_prot,
            t=t_prot,
        )

    score_row = build_score_row(
        target_name=target_name,
        chain_id=chain_id,
        attempt=attempt,
        center_residue=center_residue,
        covered_str=covered_str,
        sequence=sequence,
        rfd4_motif_rmsd=rfd4_motif_rmsd,
        sc_rmsd=sc_rmsd,
        motif_rmsd=motif_rmsd,
        mean_plddt=mean_plddt,
        motif_plddt=motif_plddt,
        mean_pae=mean_pae,
        ptm=ptm,
        failure=failure_str,
    )

    return ProtenixAttemptPostprocessResult(
        sc_rmsd=sc_rmsd,
        motif_rmsd=motif_rmsd,
        mean_plddt=mean_plddt,
        motif_plddt=motif_plddt,
        mean_pae=mean_pae,
        ptm=ptm,
        failure_str=failure_str,
        accepted=accepted,
        score_row=score_row,
    )
