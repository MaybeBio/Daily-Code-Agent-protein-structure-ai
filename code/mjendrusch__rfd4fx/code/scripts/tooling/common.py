"""Shared cross-script utilities for rfd4fx CLI workflows.

Provides vocabulary and sequence decoding re-exports, PDB path and output
directory helpers, reflection-guarded Kabsch and C2-symmetric sidechain
alignment, Gemmi/Protenix PDB writers, RFD4 sampler loading, GPU memory policy
checks, and single-ceiling atom-padded MSA-free Protenix evaluation.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import os
import pathlib
import tempfile
from typing import Any, Callable, Sequence

import gemmi
import numpy as np

from rfd4fx.encoding import (
    CANONICAL_AA1_TO_3,
    CANONICAL_AA3_TO_1,
    CANONICAL_NON_GLY_AAS,
    aa_idx_from_logits,
    canonical_aa_token_indices,
    decode_sequence,
    encoding_tables,
)
from rfd4fx.pdb_io import save_gemmi_pdb

logger = logging.getLogger(__name__)

BACKBONE_ATOMS: frozenset[str] = frozenset({"N", "CA", "C", "O", "OXT"})
WATERS: frozenset[str] = frozenset({"HOH", "DOD", "WAT"})
C2_SYMMETRY_SWAPS: dict[str, tuple[tuple[str, str], ...]] = {
    "ASP": (("OD1", "OD2"),),
    "GLU": (("OE1", "OE2"),),
    "PHE": (("CD1", "CD2"), ("CE1", "CE2")),
    "TYR": (("CD1", "CD2"), ("CE1", "CE2")),
    "ARG": (("NH1", "NH2"),),
}

_encoding_tables = encoding_tables
_decode_sequence = decode_sequence


def extract_rfd4_aa_pred(
    rfd4_res: Any, num_aa: int | None = None, *, index: int = 0
) -> np.ndarray:
    """Extract 1D ``int32`` predicted token indices from an ``RFD4Result``."""
    if hasattr(rfd4_res, "aa_idx"):
        return rfd4_res.aa_idx(index=index, num_aa=num_aa)

    data = getattr(rfd4_res, "data", None)
    dec = getattr(rfd4_res, "dec", None)
    aa_src = getattr(data, "aa_pred", None) if data is not None else None
    if aa_src is None:
        s_pred = getattr(data, "s_pred", None) if data is not None else None
        if s_pred is not None and not isinstance(s_pred, dict) and dec is None:
            aa_src = aa_idx_from_logits(np.asarray(s_pred))
        elif dec is not None:
            aa_src = dec.aatype_max
        else:
            raise ValueError(
                "rfd4_res must expose data.aa_pred, sequence logits in data.s_pred, "
                "or dec.aatype_max"
            )
    aa_arr = np.asarray(aa_src, dtype=np.int32)
    if aa_arr.ndim == 2:
        aa_arr = aa_arr[index]
    elif aa_arr.ndim != 1:
        aa_arr = aa_arr.reshape(-1)
    if num_aa is not None:
        aa_arr = aa_arr[:num_aa]
    return np.asarray(aa_arr, dtype=np.int32)


def extract_rfd4_predictions(
    rfd4_res: Any, num_aa: int | None = None, *, index: int = 0
) -> tuple[np.ndarray, str, np.ndarray, np.ndarray]:
    """Return ``(aa_pred_idx, sequence, coors_ang, atom_mask)`` from ``rfd4_res``."""
    if (
        hasattr(rfd4_res, "aa_idx")
        and hasattr(rfd4_res, "sequence")
        and hasattr(rfd4_res, "to_atom37")
    ):
        aa_pred_idx = rfd4_res.aa_idx(index=index, num_aa=num_aa)
        sequence = rfd4_res.sequence(index=index, num_aa=num_aa)
        coors_ang, mask_raw = rfd4_res.to_atom37(index=index, num_aa=num_aa)
        return aa_pred_idx, sequence, coors_ang, mask_raw

    aa_pred_idx = extract_rfd4_aa_pred(rfd4_res, num_aa=num_aa, index=index)
    sequence = decode_sequence(aa_pred_idx)
    coors_raw = np.asarray(rfd4_res.dec.coors_nm, dtype=np.float64)
    mask_raw = np.asarray(rfd4_res.dec.atom_mask, dtype=bool)
    if coors_raw.ndim == 4:
        coors_raw = coors_raw[index]
    if mask_raw.ndim == 3:
        mask_raw = mask_raw[index]
    if num_aa is not None:
        coors_raw = coors_raw[:num_aa]
        mask_raw = mask_raw[:num_aa]
    coors_ang = coors_raw * 10.0
    return aa_pred_idx, sequence, coors_ang, mask_raw


def discover_pdb_paths(in_path: pathlib.Path) -> list[pathlib.Path]:
    """Resolve ``--in_path`` to a sorted list of existing ``.pdb`` file paths."""
    if not in_path.exists():
        raise ValueError(f"--in_path does not exist: {in_path}")
    if in_path.is_file():
        return [in_path]
    if in_path.is_dir():
        paths = sorted(p for p in in_path.glob("*.pdb") if p.is_file())
        if not paths:
            raise ValueError(f"No .pdb files found in directory: {in_path}")
        return paths
    raise ValueError(f"--in_path is neither a file nor a directory: {in_path}")


def prepare_output_dir(
    out_path: pathlib.Path,
    *,
    overwrite: bool = False,
    subdirs: Sequence[str] = (),
) -> pathlib.Path:
    """Validate and create ``out_path`` plus any requested subdirectories."""
    if out_path.exists():
        if not out_path.is_dir():
            raise FileExistsError(
                f"--out_path exists and is not a directory: {out_path}"
            )
        if any(out_path.iterdir()) and not overwrite:
            raise FileExistsError(
                f"--out_path is non-empty ({out_path}); pass --overwrite to allow reuse"
            )
    out_path.mkdir(parents=True, exist_ok=True)
    for sub in subdirs:
        (out_path / sub).mkdir(parents=True, exist_ok=True)
    return out_path


def normalize_blank_chain_ids(model: gemmi.Model) -> None:
    """Normalize blank chain names in-place to ``'_'``, ``'_1'``, ``'_2'``, ..."""
    existing = {c.name.strip() for c in model if c.name.strip() != ""}
    for chain in model:
        if chain.name.strip() == "":
            if "_" not in existing:
                new_name = "_"
            else:
                suffix = 1
                while f"_{suffix}" in existing:
                    suffix += 1
                new_name = f"_{suffix}"
            chain.name = new_name
            existing.add(new_name)


_normalize_blank_chain_ids = normalize_blank_chain_ids


def format_score(val: float | None, *, precision: int = 4) -> str:
    """Format an optional scalar metric for CSV logging."""
    return "none" if val is None else f"{val:.{precision}f}"


_format_score = format_score


def kabsch_superpose(
    mobile: np.ndarray, target: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray]:
    """Compute reflection-free Kabsch transform mapping ``mobile @ R + t -> target``."""
    mobile_arr = np.asarray(mobile, dtype=np.float64)
    target_arr = np.asarray(target, dtype=np.float64)
    if (
        mobile_arr.ndim != 2
        or target_arr.ndim != 2
        or mobile_arr.shape != target_arr.shape
        or mobile_arr.shape[1] != 3
        or mobile_arr.shape[0] == 0
    ):
        raise ValueError(
            f"kabsch_superpose requires matching non-empty (N, 3) arrays, "
            f"got {mobile_arr.shape} and {target_arr.shape}"
        )
    if not (np.isfinite(mobile_arr).all() and np.isfinite(target_arr).all()):
        raise ValueError(
            "kabsch_superpose requires finite coordinates; received NaN or Inf"
        )

    p_mean = mobile_arr.mean(axis=0)
    q_mean = target_arr.mean(axis=0)
    p_c = mobile_arr - p_mean
    q_c = target_arr - q_mean
    h = p_c.T @ q_c
    u, _, vt = np.linalg.svd(h)
    d = -1.0 if np.linalg.det(vt.T @ u.T) < 0.0 else 1.0
    r = u @ np.diag([1.0, 1.0, d]) @ vt
    t = q_mean - p_mean @ r
    diff = p_c @ r - q_c
    rmsd = float(np.sqrt(np.mean(np.sum(diff * diff, axis=-1))))
    return rmsd, r, t


def coupled_kabsch_sidechain_rmsd(
    pred_atom_dicts: Sequence[dict[str, np.ndarray]],
    motif_residues: Sequence[Any],
) -> tuple[float, np.ndarray, np.ndarray]:
    """Jointly optimize rigid-body Kabsch fit and C2 symmetric sidechain swaps."""
    if len(pred_atom_dicts) != len(motif_residues):
        raise ValueError(
            f"Length mismatch: {len(pred_atom_dicts)} predicted vs "
            f"{len(motif_residues)} motif residues"
        )
    if not motif_residues:
        raise ValueError("coupled_kabsch_sidechain_rmsd requires >= 1 residue")

    m_count = len(motif_residues)
    p_id_list: list[np.ndarray] = []
    p_sw_list: list[np.ndarray] = []
    q_list: list[np.ndarray] = []
    sym_indices: list[int] = []

    for m, (pred, res) in enumerate(zip(pred_atom_dicts, motif_residues)):
        for an in res.sc_atom_names:
            if an not in pred:
                label = getattr(res, "res_token", res.res_name)
                raise ValueError(
                    f"Missing sidechain atom {an!r} for {label} ({res.res_name})"
                )
        q_arr = np.stack(
            [res.atom_coords[an] for an in res.sc_atom_names], axis=0
        ).astype(np.float64)
        p_id = np.stack(
            [pred[an] for an in res.sc_atom_names], axis=0
        ).astype(np.float64)
        q_list.append(q_arr)
        p_id_list.append(p_id)

        swaps = C2_SYMMETRY_SWAPS.get(res.res_name, ())
        if swaps:
            swap_map: dict[str, str] = {}
            for a, b in swaps:
                swap_map[a] = b
                swap_map[b] = a
            if all(swap_map.get(an, an) in pred for an in res.sc_atom_names):
                sym_indices.append(m)
                p_sw = np.stack(
                    [pred[swap_map.get(an, an)] for an in res.sc_atom_names],
                    axis=0,
                ).astype(np.float64)
                p_sw_list.append(p_sw)
            else:
                p_sw_list.append(p_id)
        else:
            p_sw_list.append(p_id)

    target_all = np.concatenate(q_list, axis=0)
    m_sym = len(sym_indices)

    if m_sym <= 8:
        best_rmsd = float("inf")
        best_r = np.eye(3, dtype=np.float64)
        best_t = np.zeros(3, dtype=np.float64)
        for mask_bits in range(1 << m_sym):
            flipped = {
                sym_indices[k]
                for k in range(m_sym)
                if (mask_bits >> k) & 1
            }
            mobile_all = np.concatenate(
                [
                    p_sw_list[m] if m in flipped else p_id_list[m]
                    for m in range(m_count)
                ],
                axis=0,
            )
            rmsd, r, t = kabsch_superpose(mobile_all, target_all)
            if rmsd < best_rmsd:
                best_rmsd, best_r, best_t = rmsd, r, t
        return best_rmsd, best_r, best_t

    # M_sym > 8: initialize from swap-invariant sidechain atoms (+ CA fallback).
    inv_p: list[np.ndarray] = []
    inv_q: list[np.ndarray] = []
    for pred, res in zip(pred_atom_dicts, motif_residues):
        swapped_names = {
            an
            for pair in C2_SYMMETRY_SWAPS.get(res.res_name, ())
            for an in pair
        }
        for an in res.sc_atom_names:
            if an not in swapped_names:
                inv_p.append(np.asarray(pred[an], dtype=np.float64))
                inv_q.append(np.asarray(res.atom_coords[an], dtype=np.float64))

    need_ca_fallback = len(inv_p) < 3
    if not need_ca_fallback:
        inv_p_arr = np.stack(inv_p, axis=0)
        inv_q_arr = np.stack(inv_q, axis=0)
        s_p = np.linalg.svd(inv_p_arr - inv_p_arr.mean(axis=0), compute_uv=False)
        s_q = np.linalg.svd(inv_q_arr - inv_q_arr.mean(axis=0), compute_uv=False)
        if s_p[1] < 1e-6 or s_q[1] < 1e-6:
            need_ca_fallback = True

    if need_ca_fallback:
        for pred, res in zip(pred_atom_dicts, motif_residues):
            if "CA" in pred and "CA" in res.atom_coords:
                inv_p.append(np.asarray(pred["CA"], dtype=np.float64))
                inv_q.append(np.asarray(res.atom_coords["CA"], dtype=np.float64))

    _, r, t = kabsch_superpose(np.stack(inv_p, axis=0), np.stack(inv_q, axis=0))

    flips = [False] * m_count
    rmsd = float("inf")
    for it in range(5):
        new_flips = [False] * m_count
        for m in sym_indices:
            err_id = float(np.sum((p_id_list[m] @ r + t - q_list[m]) ** 2))
            err_sw = float(np.sum((p_sw_list[m] @ r + t - q_list[m]) ** 2))
            new_flips[m] = err_sw < err_id

        mobile_all = np.concatenate(
            [
                p_sw_list[m] if new_flips[m] else p_id_list[m]
                for m in range(m_count)
            ],
            axis=0,
        )
        rmsd, r, t = kabsch_superpose(mobile_all, target_all)
        if it > 0 and new_flips == flips:
            break
        flips = new_flips

    return rmsd, r, t


def extract_token_ca_coords(
    sample_coords_ang: np.ndarray,
    atom_names: Sequence[str],
    atom_to_token_idx: np.ndarray,
    num_aa: int,
) -> np.ndarray:
    """Extract ordered ``(num_aa, 3)`` ``CA`` coordinates from atom arrays."""
    ca_by_tok: dict[int, np.ndarray] = {}
    for ai, an in enumerate(atom_names):
        if str(an).strip() == "CA":
            tok = int(atom_to_token_idx[ai])
            if 0 <= tok < num_aa and tok not in ca_by_tok:
                ca_by_tok[tok] = sample_coords_ang[ai]
    if len(ca_by_tok) != num_aa:
        raise ValueError(
            f"Expected {num_aa} Protenix CA atoms, got {len(ca_by_tok)}"
        )
    ca_coords = np.stack([ca_by_tok[t] for t in range(num_aa)], axis=0)
    if ca_coords.shape != (num_aa, 3):
        raise ValueError(f"Unexpected Protenix CA shape: {ca_coords.shape}")
    return ca_coords


def write_rfd4_pdb(
    result: Any,
    out_file: pathlib.Path,
    *,
    R: np.ndarray | None = None,
    t: np.ndarray | None = None,
    offset: np.ndarray | None = None,
    b_factors: np.ndarray | None = None,
    highlight_res_ids: Sequence[int] | np.ndarray | None = None,
    index: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Delegate to ``RFD4Result.save_pdb`` with optional rigid transform and B-factors."""
    result.save_pdb(
        out_file,
        index=index,
        metadata=metadata,
        R=R,
        t=t,
        offset=offset,
        b_factors=b_factors,
        highlight_res_ids=highlight_res_ids,
    )


def write_protenix_pdb(
    writer: Any,
    out_file: pathlib.Path,
    *,
    coords_ang: np.ndarray,
    res_plddt: np.ndarray,
    atom_to_token_idx: np.ndarray,
    R: np.ndarray | None = None,
    t: np.ndarray | None = None,
) -> None:
    """Write Protenix coordinates + per-residue pLDDT to PDB with optional transform."""
    if R is not None and t is not None:
        aligned_coords = (
            np.asarray(coords_ang, dtype=np.float64) @ np.asarray(R, dtype=np.float64)
            + np.asarray(t, dtype=np.float64)
        )
    else:
        aligned_coords = np.asarray(coords_ang, dtype=np.float64)

    atom_plddt = np.asarray(res_plddt, dtype=np.float64)[
        np.asarray(atom_to_token_idx, dtype=np.int32)
    ]

    if hasattr(writer, "atom_array") and writer.atom_array is not None:
        writer.atom_array.coord = aligned_coords.astype(np.float32)
        writer.atom_array.set_annotation("b_factor", atom_plddt)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_str = str(out_file)

    sig = inspect.signature(writer.save_pdb)
    params = list(sig.parameters.values())
    has_var_kw = any(
        p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for p in params
    )
    if not params or (has_var_kw and len(params) <= 2):
        writer.save_pdb(out_str)
        return

    path_names = {"path", "out_path", "file_path", "filename", "pdb_path", "out_file"}
    coord_names = {
        "sample_atom_coords",
        "sample_coords",
        "positions",
        "coords",
        "coord",
        "coordinates",
        "atom_coords",
        "xyz",
        "pos",
    }
    bfac_names = {"b_factor", "b_factors", "plddt", "bfactor"}

    kwargs: dict[str, Any] = {}
    pos_args: list[Any] = []
    for p in params:
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        pname = p.name.lower()
        val: Any = inspect.Parameter.empty
        if pname in path_names:
            val = out_str
        elif pname in coord_names:
            val = aligned_coords
        elif pname in bfac_names:
            val = atom_plddt
        if val is not inspect.Parameter.empty:
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                pos_args.append(val)
            else:
                kwargs[p.name] = val

    if pos_args or kwargs:
        writer.save_pdb(*pos_args, **kwargs)
    else:
        writer.save_pdb(out_str)


def write_gemmi_pdb(
    structure: gemmi.Structure,
    out_file: pathlib.Path,
    *,
    residue_b_factor_fn: Callable[[str, gemmi.Residue], float] | None = None,
) -> None:
    """Write a ``gemmi.Structure`` to PDB, optionally setting per-residue B-factors."""
    if residue_b_factor_fn is not None:
        model = structure[0]
        for chain in model:
            cid = chain.name
            for res in chain:
                b_val = float(residue_b_factor_fn(cid, res))
                for atom in res:
                    atom.b_iso = b_val

    save_gemmi_pdb(structure, out_file)


def load_rfd4_sampler():
    """Lazily load pretrained RFD4 weights and construct ``RFD4Sampler``."""
    from rfd4fx.flow_matching import RFD4Sampler, THINKING_HIGH  # noqa: F401
    from rfd4fx.model import RFD4

    jax_model = RFD4.from_pretrained()
    return RFD4Sampler(jax_model.step(), jax_model)


_load_rfd4_sampler = load_rfd4_sampler


def check_gpu_memory_policy(
    jax_mod: Any, *, log: logging.Logger | None = None
) -> None:
    """Log active JAX devices and warn when XLA VRAM preallocation may OOM."""
    active_log = logger if log is None else log
    devices = jax_mod.devices()
    active_log.info("JAX devices: %s", devices)
    prealloc = os.environ.get("XLA_PYTHON_CLIENT_PREALLOCATE", "true").lower()
    mem_frac_raw = os.environ.get("XLA_PYTHON_CLIENT_MEM_FRACTION", "0.75")
    try:
        mem_frac = float(mem_frac_raw)
    except ValueError:
        mem_frac = 1.0
    if prealloc != "false" or mem_frac > 0.5:
        active_log.warning(
            "Co-resident RFD4 + Protenix GPU memory warning: "
            "XLA_PYTHON_CLIENT_PREALLOCATE=%r, XLA_PYTHON_CLIENT_MEM_FRACTION=%r. "
            "Consider setting XLA_PYTHON_CLIENT_PREALLOCATE=false or "
            "XLA_PYTHON_CLIENT_MEM_FRACTION<=0.5 to avoid GPU OOM.",
            prealloc,
            mem_frac_raw,
        )


_check_gpu_memory_policy = check_gpu_memory_policy


def wrap_padded_evaluator_class(
    evaluator_cls: type,
    eqx: Any,
    jax: Any,
    jnp: Any,
    atom_padding: Any,
) -> type:
    """Return a ProtenixEvaluator subclass with CPU-safe clamping and atom padding."""
    if not (
        isinstance(evaluator_cls, type)
        and issubclass(evaluator_cls, eqx.Module)
    ):
        return evaluator_cls

    class _SafePaddedProtenixEvaluator(evaluator_cls):
        """Patch Protenij CPU sqrt NaNs while retaining atom_pad_mask centering."""

        def sample_structures(
            self,
            *,
            initial_embedding: Any,
            trunk_embedding: Any,
            input_feature_dict: dict[str, Any],
            N_samples: int,
            N_steps: int,
            key: Any,
        ) -> Any:
            noise_schedule = self.model.inference_noise_scheduler(
                N_step=N_steps
            )
            atom_mask = input_feature_dict.get("atom_pad_mask")
            s_inputs = initial_embedding.s_inputs
            s_trunk = trunk_embedding.s
            z_trunk = trunk_embedding.z
            n_atom = input_feature_dict["atom_to_token_idx"].shape[-1]
            batch_shape = s_inputs.shape[:-2]

            init_noise = jax.random.normal(
                key=key, shape=(*batch_shape, N_samples, n_atom, 3)
            )
            x_l = atom_padding.mask_atom_values(
                noise_schedule[0] * init_noise, atom_mask
            )

            @jax.checkpoint
            def body_fn(carry, step_sched):
                x_cur, step_key = carry
                c_tau_last, c_tau = step_sched
                x_cur = atom_padding.center_atom_coordinates(x_cur, atom_mask)
                gamma = jax.lax.select(
                    c_tau > self.model.gamma_min,
                    jnp.asarray(self.model.gamma0, dtype=c_tau_last.dtype),
                    jnp.asarray(0.0, dtype=c_tau_last.dtype),
                )
                t_hat = c_tau_last * (
                    gamma + jnp.asarray(1.0, dtype=c_tau_last.dtype)
                )
                # Guard negative zero/FMA rounding when gamma == 0.0 on CPU.
                delta_noise_level = jnp.sqrt(
                    jnp.maximum(
                        t_hat**2 - c_tau_last**2,
                        jnp.asarray(0.0, dtype=c_tau_last.dtype),
                    )
                )
                step_key = jax.random.fold_in(step_key, 1)
                noise = jax.random.normal(key=step_key, shape=x_cur.shape)
                x_noisy = atom_padding.mask_atom_values(
                    x_cur
                    + self.model.noise_scale_lambda
                    * delta_noise_level
                    * noise,
                    atom_mask,
                )
                t_hat_batched = jnp.tile(
                    t_hat.reshape((1,) * (len(batch_shape) + 1)),
                    (*batch_shape, N_samples),
                )
                x_denoised = self.model.diffusion_module(
                    x_noisy=x_noisy,
                    t_hat_noise_level=t_hat_batched,
                    input_feature_dict=input_feature_dict,
                    s_inputs=s_inputs,
                    s_trunk=s_trunk,
                    z_trunk=z_trunk,
                )
                delta = (x_noisy - x_denoised) / t_hat_batched[
                    ..., None, None
                ]
                dt = c_tau - t_hat_batched
                x_next = atom_padding.mask_atom_values(
                    x_noisy
                    + self.model.step_scale_eta * dt[..., None, None] * delta,
                    atom_mask,
                )
                return (x_next, step_key), None

            (x_l, _), _ = jax.lax.scan(
                body_fn,
                init=(x_l, key),
                xs=(noise_schedule[:-1], noise_schedule[1:]),
            )
            return x_l

        def structure_module(
            self,
            key: Any,
            state: Any,
            features: Any,
            embedding: Any,
            num_samples: int = 1,
            sampling_steps: int = 25,
            parallel: bool = False,
        ) -> tuple[Any, Any]:
            def single_sample(carry, sample_key):
                sample = self.sample_structures(
                    initial_embedding=embedding,
                    trunk_embedding=state,
                    input_feature_dict=features,
                    N_samples=1,
                    N_steps=sampling_steps,
                    key=sample_key,
                )
                confidence = self.model.confidence_metrics(
                    initial_embedding=embedding,
                    trunk_embedding=state,
                    input_feature_dict=features,
                    coordinates=sample,
                    key=sample_key,
                )
                return carry, (sample, confidence)

            if num_samples > 1:
                sample_keys = jax.random.split(key, num_samples)
                if parallel:
                    vmap_sample = jax.vmap(
                        single_sample,
                        in_axes=(None, 0),
                        out_axes=(None, (0, 0)),
                    )
                    _, (samples, confidence) = vmap_sample(None, sample_keys)
                else:
                    _, (samples, confidence) = jax.lax.scan(
                        single_sample, None, sample_keys
                    )
            else:
                _, (samples, confidence) = single_sample(None, key)
            return samples, confidence

    return _SafePaddedProtenixEvaluator


_wrap_padded_evaluator_class = wrap_padded_evaluator_class


class PaddedProtenixRunner:
    """Single-ceiling atom-padded MSA-free Protenix evaluator context manager."""

    def __init__(self, *, num_aa: int, model_name: str) -> None:
        self.num_aa = int(num_aa)
        self.model_name = str(model_name)
        self.n_atom_pad = ((14 * self.num_aa + 1 + 127) // 128) * 128
        self._tmp_ctx: tempfile.TemporaryDirectory[str] | None = None
        self.msa_tmp: pathlib.Path | None = None
        self._jit_predict = None
        self._make_dummy_msa = None
        self._ProtenixSpec = None
        self._ProtenixResult = None
        self._pad_atom_features = None

    def __enter__(self) -> "PaddedProtenixRunner":
        import equinox as eqx
        import jax
        import jax.numpy as jnp
        import protenix.atom_padding as atom_padding
        from flexcraft.structure.protenix._data import (
            ProtenixSpec,
            _make_dummy_msa,
        )
        from flexcraft.structure.protenix._model import (
            Protenix,
            ProtenixEvaluator,
        )
        from flexcraft.structure.protenix._result import ProtenixResult

        self._tmp_ctx = tempfile.TemporaryDirectory(prefix="protenix_msa_")
        self.msa_tmp = pathlib.Path(self._tmp_ctx.name)
        protenix = Protenix(self.model_name)
        evaluator_cls = wrap_padded_evaluator_class(
            ProtenixEvaluator, eqx, jax, jnp, atom_padding
        )
        evaluator = evaluator_cls(
            model=protenix.model, num_recycle=4, sampling_steps=25
        )
        self._jit_predict = eqx.filter_jit(evaluator._predict)
        self._make_dummy_msa = _make_dummy_msa
        self._ProtenixSpec = ProtenixSpec
        self._ProtenixResult = ProtenixResult
        self._pad_atom_features = atom_padding.pad_atom_features
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tmp_ctx is not None:
            self._tmp_ctx.cleanup()
            self._tmp_ctx = None
            self.msa_tmp = None

    def fold_sequence(
        self, key: Any, sequence: str
    ) -> tuple[Any, Any, np.ndarray, np.ndarray, np.ndarray]:
        """Fold ``sequence`` with single-ceiling atom padding and unpad outputs."""
        import jax

        if self.msa_tmp is None or self._jit_predict is None:
            raise RuntimeError(
                "PaddedProtenixRunner must be used inside a 'with' context"
            )

        self._make_dummy_msa(sequence, self.msa_tmp)
        unpadded_input, writer = self._ProtenixSpec(
            {
                "kind": "protein",
                "sequence": sequence,
                "use_msa": False,
                "msa_dir": self.msa_tmp,
            }
        ).to_input()
        n_atom = int(writer.atom_array.array_length())
        if n_atom > self.n_atom_pad:
            raise ValueError(
                f"Sequence heavy-atom count {n_atom} exceeds n_atom_pad={self.n_atom_pad}"
            )

        flat_arrays: dict[str, Any] = {}
        nested_dicts: dict[str, Any] = {}
        for k, v in unpadded_input.features.items():
            if isinstance(v, (np.ndarray, jax.Array)):
                flat_arrays[k] = v
            elif isinstance(v, dict):
                nested_dicts[k] = {
                    k2: v2
                    for k2, v2 in v.items()
                    if isinstance(v2, (np.ndarray, jax.Array))
                }

        padded_flat = self._pad_atom_features(
            flat_arrays,
            atom_count=self.n_atom_pad,
            extra_atom_axes={"distogram_rep_atom_mask": (0,)},
        )
        padded_features = {**nested_dicts, **padded_flat}
        raw = self._jit_predict(key, padded_features, num_samples=1)

        samples = raw.data["samples"][:, :n_atom, :]
        sliced_conf = dataclasses.replace(
            raw.data["confidence"],
            plddt_logits=raw.data["confidence"].plddt_logits[:, :n_atom, :],
        )
        protenix_res = self._ProtenixResult(
            {
                **raw.data,
                "features": unpadded_input.features,
                "samples": samples,
                "confidence": sliced_conf,
            }
        )
        atom_to_token_idx = np.asarray(
            unpadded_input.features["atom_to_token_idx"], dtype=np.int32
        )
        sample_coords_ang = np.asarray(samples[0], dtype=np.float64)

        plddt_arr = np.asarray(protenix_res.plddt, dtype=np.float64)
        if plddt_arr.ndim == 2 and plddt_arr.shape[0] == 1:
            plddt_arr = plddt_arr[0]
        if plddt_arr.shape == (self.num_aa,):
            res_plddt = plddt_arr
        elif plddt_arr.shape == (n_atom,):
            res_plddt = np.zeros(self.num_aa, dtype=np.float64)
            for tok in range(self.num_aa):
                sel = atom_to_token_idx == tok
                res_plddt[tok] = float(plddt_arr[sel].mean()) if sel.any() else 0.0
        else:
            res_plddt = plddt_arr.reshape(self.num_aa)

        return (
            protenix_res,
            writer,
            sample_coords_ang,
            res_plddt,
            atom_to_token_idx,
        )
