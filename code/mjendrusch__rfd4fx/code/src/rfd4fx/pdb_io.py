"""Structure export at the numpy/gemmi/biotite file-I/O boundary.

Mirrors the native export path, including the OP3/O3' conventions for
multi-residue nucleic-acid chains."""

from __future__ import annotations

import functools
import os
import pathlib
from typing import Any, Sequence

import numpy as np

_PROTEIN_TOKEN_TYPES = (0,)
_NA_TOKEN_TYPES = (1, 2)  # rna, dna (rfproteina TOKEN_TYPE_IDS)
_TWO_CHAR_ELEMS = frozenset(("CL", "BR", "SE", "MG", "ZN", "FE", "AS"))


@functools.lru_cache(maxsize=1)
def _atom37_vocab_tables():
    """Precompute (V+1, 37) atom-name / element lookup tables from TOKEN_ATOM_LAYOUTS."""
    from rfd4fx.encoding import TOKEN_ATOM_LAYOUTS

    v_size = len(TOKEN_ATOM_LAYOUTS)
    vocab_names = np.full(v_size + 1, "", dtype="U8")
    slot_names = np.full((v_size + 1, 37), "", dtype="U6")
    slot_elems = np.full((v_size + 1, 37), "", dtype="U4")
    tok_to_idx: dict[str, int] = {}

    for idx, (res_name, atoms) in enumerate(TOKEN_ATOM_LAYOUTS.items()):
        vocab_names[idx] = res_name
        tok_to_idx[res_name] = idx
        for s in range(37):
            an = str(atoms[s]).strip()
            if not an:
                continue
            slot_names[idx, s] = an
            letters = "".join(c for c in an if c.isalpha()).upper()
            slot_elems[idx, s] = letters[:2] if letters[:2] in _TWO_CHAR_ELEMS else letters[:1]
    return vocab_names, slot_names, slot_elems, tok_to_idx


def _chain_assignments(token_type: np.ndarray, real: np.ndarray,
                       chain_ids) -> np.ndarray:
    """Per-token chain-id strings. `chain_ids` may be None (single "A"),
    a list/str per unique token-type-respecting chain, or a (n,) array."""
    n = token_type.shape[0]
    if chain_ids is not None:
        arr = np.asarray(chain_ids)
        if arr.ndim == 2 and arr.shape[0] == 1:
            arr = arr[0]
        if arr.ndim == 0:
            return np.full(n, str(arr))
        if arr.dtype.kind in ("U", "S", "O") and arr.shape == (n,):
            return arr.astype(str)
    # derive letters from first-appearance order of real tokens (one chain
    # per maximal run is NOT assumed — callers pass explicit ids for
    # multi-unit layouts; the default assumes one polymer chain)
    return np.full(n, "A")


def _squeeze_first(value: Any, expected_ndim: int, name: str) -> np.ndarray:
    """Coerce a batched `(1, ...)` or unbatched `(...)` array to `expected_ndim`."""
    arr = np.asarray(value)
    if arr.ndim == expected_ndim + 1:
        return arr[0]
    if arr.ndim == expected_ndim:
        return arr
    raise ValueError(
        f"{name} must have {expected_ndim} or {expected_ndim + 1} dims, got {arr.shape}"
    )


def _extract_real_and_token_type(batch: Any, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Return 1D `(real, token_type)` masks of length `n` from `batch`."""
    real = (
        _squeeze_first(batch.padding_mask, 1, "batch.padding_mask").astype(bool)
        if batch is not None and getattr(batch, "padding_mask", None) is not None
        else np.ones(n, dtype=bool)
    )
    token_type = (
        _squeeze_first(batch.token_type, 1, "batch.token_type").astype(np.int32)
        if batch is not None and getattr(batch, "token_type", None) is not None
        else np.zeros(n, dtype=np.int32)
    )
    return real, token_type


def _terminal_oxygen_keep_mask(
    chain_ids: np.ndarray,
    res_ids: np.ndarray,
    atom_names: np.ndarray,
    chain_kind: dict[str, str],
) -> np.ndarray:
    """Boolean mask keeping all atoms except terminal OP3/OXT on multimers."""
    keep = np.ones(len(atom_names), dtype=bool)
    if len(atom_names) == 0:
        return keep
    for cid, kind in chain_kind.items():
        sel = chain_ids == cid
        if not sel.any() or len(np.unique(res_ids[sel])) <= 1:
            continue  # free nucleotides / single residues keep their OP3/OXT
        if kind == "na":
            keep[sel] &= atom_names[sel] != "OP3"
        elif kind == "protein":
            keep[sel] &= atom_names[sel] != "OXT"
    return keep


def drop_terminal_oxygen(arr, chain_kind: dict[str, str]):
    """Native terminal-oxygen cleanup on an assembled AtomArray.

    `chain_kind` maps chain_id -> "na" | "protein". Mirrors atomworks
    `polymer_terminal_oxygen_mask` (filters.py:555): OP3 is dropped from
    MULTI-RESIDUE nucleic-acid chains and OXT from multi-residue protein
    chains; free single-residue chains (free nucleotides / amino acids) and
    atomized tokens keep their terminal atoms. No renaming — O3' (slot 5)
    is always kept.
    """
    if len(arr) == 0:
        return arr
    keep = _terminal_oxygen_keep_mask(
        np.asarray(arr.chain_id),
        np.asarray(arr.res_id),
        np.asarray(arr.atom_name),
        chain_kind,
    )
    return arr[keep]


def _decoded_polymer_records(
    dec,
    batch=None,
    *,
    aa_pred=None,
    chain_ids=None,
    identity=None,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Decode polymer atom records `(coords_ang, chains, res_ids, res_names, atom_names, elems, tok_idx)`."""
    vocab_names, slot_names_tbl, slot_elems_tbl, tok_to_idx = _atom37_vocab_tables()
    sentinel = vocab_names.shape[0] - 1

    coors = _squeeze_first(dec.coors_nm, 3, "dec.coors_nm").astype(np.float64) * 10.0
    emit = _squeeze_first(dec.emit_mask, 1, "dec.emit_mask").astype(bool)
    atom_mask = _squeeze_first(dec.atom_mask, 2, "dec.atom_mask").astype(bool)
    gate = atom_mask & emit[:, None]
    n = coors.shape[0]
    real, token_type = _extract_real_and_token_type(batch, n)

    if identity is not None:
        res_names = np.asarray(identity).astype(str)
        v_idx = np.fromiter(
            (tok_to_idx.get(str(nm), sentinel) for nm in res_names),
            dtype=np.int32,
            count=n,
        )
    else:
        raw_aa = (
            _squeeze_first(aa_pred, 1, "aa_pred")
            if aa_pred is not None
            else _squeeze_first(dec.aatype_max, 1, "dec.aatype_max")
        ).astype(np.int32)
        v_idx = np.where((raw_aa >= 0) & (raw_aa < sentinel), raw_aa, sentinel)
        res_names = vocab_names[v_idx]
    chain_of = _chain_assignments(token_type, real, chain_ids)

    an_grid = slot_names_tbl[v_idx]
    valid_slot = (
        (real & emit)[:, None]
        & gate
        & (an_grid != "")
        & np.isfinite(coors).all(axis=-1)
        & (np.abs(coors).sum(axis=-1) > 0)
    )
    tok_idx, slot_idx = np.nonzero(valid_slot)
    if len(tok_idx):
        coords = coors[tok_idx, slot_idx]
        chains = chain_of[tok_idx]
        res_ids = (tok_idx + 1).astype(np.int64)
        res_names_out = res_names[tok_idx]
        atom_names = an_grid[tok_idx, slot_idx]
        elems = slot_elems_tbl[v_idx[tok_idx], slot_idx]
    else:
        coords = np.zeros((0, 3), dtype=np.float64)
        chains = np.zeros(0, dtype="U4")
        res_ids = np.zeros(0, dtype=np.int64)
        res_names_out = np.zeros(0, dtype="U8")
        atom_names = np.zeros(0, dtype="U6")
        elems = np.zeros(0, dtype="U4")

    # native terminal-oxygen cleanup: per chain, multi-residue only; kind
    # from the compiled token_type (na if any rna/dna token, else protein)
    chain_kind: dict[str, str] = {}
    for cid in np.unique(chain_of[real]):
        toks = np.flatnonzero(real & (chain_of == cid))
        tt = set(np.unique(token_type[toks]).tolist())
        if tt & set(_NA_TOKEN_TYPES):
            chain_kind[str(cid)] = "na"
        elif tt & set(_PROTEIN_TOKEN_TYPES):
            chain_kind[str(cid)] = "protein"
    keep = _terminal_oxygen_keep_mask(chains, res_ids, atom_names, chain_kind)
    return (
        coords[keep],
        chains[keep],
        res_ids[keep],
        res_names_out[keep],
        atom_names[keep],
        elems[keep],
        tok_idx[keep],
    )


def _apply_rigid_transform(
    coords: np.ndarray,
    *,
    R: np.ndarray | None = None,
    t: np.ndarray | None = None,
    offset: np.ndarray | None = None,
) -> np.ndarray:
    """Apply optional rigid-body transform `(R, t)` or translation `offset`."""
    if len(coords) == 0:
        return coords
    if R is not None:
        return coords @ np.asarray(R, dtype=np.float64) + np.asarray(t, dtype=np.float64)
    if offset is not None:
        return coords + np.asarray(offset, dtype=np.float64)
    return coords


def _resolve_b_factors(
    *,
    n_poly: int,
    n_lig: int,
    n_tokens: int,
    real: np.ndarray,
    poly_tok_idx: np.ndarray,
    poly_res_ids: np.ndarray,
    atom_toks: np.ndarray,
    b_factors: np.ndarray | float | None,
    highlight_res_ids: Sequence[int] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute `(poly_b, lig_b)` float64 arrays for polymer and ligand atoms."""
    if b_factors is not None and highlight_res_ids is not None:
        raise ValueError("Pass at most one of b_factors or highlight_res_ids")

    n_total = n_poly + n_lig
    n_real = int(real.sum())

    if b_factors is not None:
        bf = np.asarray(b_factors, dtype=np.float64)
        if bf.ndim == 0:
            val = float(bf)
            return np.full(n_poly, val, dtype=np.float64), np.full(
                n_lig, val, dtype=np.float64
            )
        if bf.ndim == 1 and bf.shape[0] == n_total:
            return bf[:n_poly], bf[n_poly:]
        if bf.ndim == 1 and bf.shape[0] == n_tokens:
            poly_b = bf[poly_tok_idx] if n_poly else np.zeros(0, dtype=np.float64)
            lig_b = bf[atom_toks] if n_lig else np.zeros(0, dtype=np.float64)
            return poly_b, lig_b
        if bf.ndim == 1 and bf.shape[0] == n_real:
            real_pos = np.cumsum(real) - 1
            poly_b = (
                bf[real_pos[poly_tok_idx]] if n_poly else np.zeros(0, dtype=np.float64)
            )
            lig_b = (
                bf[real_pos[atom_toks]] if n_lig else np.zeros(0, dtype=np.float64)
            )
            return poly_b, lig_b
        raise ValueError(
            f"b_factors shape {bf.shape} must be scalar, per-atom ({n_total},), "
            f"or per-token ({n_tokens},) / ({n_real},)"
        )

    if highlight_res_ids is not None:
        hi = np.asarray(highlight_res_ids, dtype=np.int64)
        poly_b = (
            np.where(np.isin(poly_res_ids, hi), 1.0, 0.0).astype(np.float64)
            if n_poly
            else np.zeros(0, dtype=np.float64)
        )
        return poly_b, np.zeros(n_lig, dtype=np.float64)

    return np.zeros(n_poly, dtype=np.float64), np.zeros(n_lig, dtype=np.float64)


def decoded_to_gemmi(
    dec,
    batch=None,
    *,
    aa_pred=None,
    chain_ids=None,
    identity=None,
    x_bb_ang: np.ndarray | None = None,
    metadata: dict | None = None,
    R: np.ndarray | None = None,
    t: np.ndarray | None = None,
    offset: np.ndarray | None = None,
    b_factors: np.ndarray | float | None = None,
    highlight_res_ids: Sequence[int] | np.ndarray | None = None,
):
    """Decode a ``DecoderOutput`` (plus optional ligand atoms) into ``gemmi.Structure``."""
    import gemmi

    if (R is None) != (t is None):
        raise ValueError("R and t must be provided together")
    if R is not None and offset is not None:
        raise ValueError("Pass either (R, t) or offset, not both")

    meta = metadata or {}
    (
        poly_coords,
        poly_chains,
        poly_res_ids,
        poly_res_names,
        poly_atom_names,
        poly_elements,
        poly_tok_idx,
    ) = _decoded_polymer_records(
        dec,
        batch,
        aa_pred=aa_pred,
        chain_ids=chain_ids,
        identity=identity,
    )

    n_tokens = int(np.asarray(dec.coors_nm).shape[-3])
    real, token_type = _extract_real_and_token_type(batch, n_tokens)

    atom_toks = np.zeros(0, dtype=np.int64)
    lig_coords = np.zeros((0, 3), dtype=np.float64)
    lig_z = np.zeros(0, dtype=np.int32)
    lig_chains = np.zeros(0, dtype="U4")
    lig_atom_names: list[str] = []
    lig_res_name = str(meta.get("residue_name", "LIG"))

    if (
        batch is not None
        and x_bb_ang is not None
        and getattr(batch, "token_type", None) is not None
        and getattr(batch, "element", None) is not None
    ):
        atom_toks = np.flatnonzero(real & (token_type == 3))
        if len(atom_toks):
            x_bb_1d = _squeeze_first(x_bb_ang, 2, "x_bb_ang").astype(np.float64)
            lig_coords = x_bb_1d[atom_toks]
            elem37 = _squeeze_first(batch.element, 2, "batch.element")
            lig_z = elem37[atom_toks, 1].astype(np.int32)
            atom_names_meta = meta.get("atom_name")
            if atom_names_meta is None:
                counts: dict[int, int] = {}
                for z in lig_z:
                    zi = int(z)
                    counts[zi] = counts.get(zi, 0) + 1
                    el_obj = gemmi.Element(zi) if zi > 0 else gemmi.Element("X")
                    sym = el_obj.name.upper() if el_obj.name != "X" else str(zi)
                    lig_atom_names.append(f"{sym}{counts[zi]}")
            else:
                lig_atom_names = [str(a) for a in atom_names_meta][: len(atom_toks)]
            if chain_ids is None:
                lig_chains = np.full(len(atom_toks), "B", dtype="U4")
            else:
                lig_chains = _chain_assignments(token_type, real, chain_ids)[atom_toks]

    poly_coords = _apply_rigid_transform(poly_coords, R=R, t=t, offset=offset)
    lig_coords = _apply_rigid_transform(lig_coords, R=R, t=t, offset=offset)

    poly_b, lig_b = _resolve_b_factors(
        n_poly=len(poly_coords),
        n_lig=len(lig_coords),
        n_tokens=n_tokens,
        real=real,
        poly_tok_idx=poly_tok_idx,
        poly_res_ids=poly_res_ids,
        atom_toks=atom_toks,
        b_factors=b_factors,
        highlight_res_ids=highlight_res_ids,
    )

    st = gemmi.Structure()
    st.name = str(meta.get("name", "rfd4"))
    model = gemmi.Model("1")
    chains_by_id: dict[str, gemmi.Chain] = {}
    label_seq_by_chain: dict[str, int] = {}
    poly_res_by_key: dict[tuple[str, int], gemmi.Residue] = {}

    for idx in range(len(poly_coords)):
        cid = str(poly_chains[idx])
        rid = int(poly_res_ids[idx])
        chain = chains_by_id.get(cid)
        if chain is None:
            chain = gemmi.Chain(cid)
            chains_by_id[cid] = chain
            label_seq_by_chain[cid] = 0
        res_key = (cid, rid)
        res = poly_res_by_key.get(res_key)
        if res is None:
            label_seq_by_chain[cid] += 1
            res = gemmi.Residue()
            res.name = str(poly_res_names[idx])
            res.seqid = gemmi.SeqId(rid, " ")
            res.het_flag = "A"
            res.entity_type = gemmi.EntityType.Polymer
            res.label_seq = label_seq_by_chain[cid]
            chain.add_residue(res)
            poly_res_by_key[res_key] = chain[-1]
            res = poly_res_by_key[res_key]
        atom = gemmi.Atom()
        atom.name = str(poly_atom_names[idx])
        el_str = str(poly_elements[idx])
        atom.element = gemmi.Element(el_str) if el_str else gemmi.Element("X")
        atom.pos = gemmi.Position(
            float(poly_coords[idx, 0]),
            float(poly_coords[idx, 1]),
            float(poly_coords[idx, 2]),
        )
        atom.occ = 1.0
        atom.b_iso = float(poly_b[idx])
        res.add_atom(atom)

    lig_res_by_chain: dict[str, gemmi.Residue] = {}
    for idx in range(len(lig_coords)):
        cid = str(lig_chains[idx])
        chain = chains_by_id.get(cid)
        if chain is None:
            chain = gemmi.Chain(cid)
            chains_by_id[cid] = chain
        res = lig_res_by_chain.get(cid)
        if res is None:
            seq_num = max((r.seqid.num for r in chain), default=0) + 1
            new_res = gemmi.Residue()
            new_res.name = lig_res_name
            new_res.seqid = gemmi.SeqId(int(seq_num), " ")
            new_res.het_flag = "H"
            new_res.entity_type = gemmi.EntityType.NonPolymer
            chain.add_residue(new_res)
            lig_res_by_chain[cid] = chain[-1]
            res = lig_res_by_chain[cid]
        atom = gemmi.Atom()
        atom.name = lig_atom_names[idx]
        zi = int(lig_z[idx])
        atom.element = gemmi.Element(zi) if zi > 0 else gemmi.Element("X")
        atom.pos = gemmi.Position(
            float(lig_coords[idx, 0]),
            float(lig_coords[idx, 1]),
            float(lig_coords[idx, 2]),
        )
        atom.occ = 1.0
        atom.b_iso = float(lig_b[idx])
        res.add_atom(atom)

    for chain in chains_by_id.values():
        model.add_chain(chain)
    st.add_model(model)
    st.setup_entities()
    return st


def save_gemmi_pdb(structure, path: str | os.PathLike) -> None:
    """Write a ``gemmi.Structure`` to a PDB file, creating parent directories."""
    import gemmi

    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    opts = gemmi.PdbWriteOptions(minimal=True)
    is_crystal = bool(structure.cell.is_crystal())
    opts.cryst1_record = is_crystal
    opts.end_record = True
    structure.write_pdb(str(out), opts)


def save_gemmi_cif(structure, path: str | os.PathLike) -> None:
    """Write a ``gemmi.Structure`` to an mmCIF file, creating parent directories."""
    import gemmi

    out = pathlib.Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    groups = gemmi.MmcifOutputGroups(True)
    groups.auth_all = True
    is_crystal = bool(structure.cell.is_crystal())
    groups.cell = is_crystal
    groups.symmetry = is_crystal
    structure.make_mmcif_document(groups).write_file(str(out))


def decoded_to_atom_array(dec, batch=None, *, aa_pred=None,
                          chain_ids=None, identity=None) -> "object":
    """Decode a DecoderOutput into a biotite AtomArray (coordinates in Å).

    Args:
      dec: decoder output with `coors_nm` (1, n, 37, 3), `aatype_max`
        (1, n), `atom_mask` (1, n, 37) and `emit_mask` (1, n).
      batch: optional FlowBatch/RFD4Input-batch carrying `padding_mask` and
        `token_type` (used for padding + the per-chain kind of the terminal-
        oxygen cleanup). May be None.
      aa_pred: optional (1, n) / (n,) trunk sequence readout used as the
        residue identity instead of the decoder's own argmax head (the
        decoder can degenerate to layout-less tokens under asymmetric
        latents; aa_pred is the token-type-restricted readout the decode
        was conditioned on).
      chain_ids: optional per-token chain ids ((n,) array of str, or a
        single str). Defaults to "A" for every token.
      identity: optional (n,) token-name array overriding both aa_pred and
        aatype_max (explicit residue identities).

    Native semantics mirrored (structure_export.py:112-138):
      - identity -> UNIFIED_ATOM37_ENCODING.token_atoms atom names;
      - a slot is written iff dec.atom_mask (residue_atom_mask & predicted
        presence) & dec.emit_mask (& padding) AND its coordinates are finite
        and non-degenerate;
      - terminal-oxygen cleanup: OP3 dropped from multi-residue nucleic-acid
        chains, OXT dropped from multi-residue protein chains (atomworks
        polymer_terminal_oxygen_mask; no renaming — O3' is slot 5 and is
        always kept).
    """
    import biotite.structure as bs

    coords, chains, res_ids, res_names, atom_names, elems, _ = (
        _decoded_polymer_records(
            dec,
            batch,
            aa_pred=aa_pred,
            chain_ids=chain_ids,
            identity=identity,
        )
    )
    arr = bs.AtomArray(len(coords))
    if len(coords):
        arr.coord[:] = coords
        arr.chain_id[:] = chains
        arr.res_id[:] = res_ids
        arr.res_name[:] = res_names
        arr.atom_name[:] = atom_names
        arr.element[:] = elems
    return arr
