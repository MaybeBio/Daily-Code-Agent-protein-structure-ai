"""Surface patch decomposition and RFD4/Protenix scaffolding pipeline.

Maps solvent-exposed surface patches of one or more target PDB structures,
generates fixed-length unindexed sidechain-only motif scaffolds with RFD4,
filters candidates by symmetric Hungarian/Kabsch motif matching, and validates
folding self-consistency using single-ceiling atom-padded MSA-free Protenix.
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import pathlib
import sys
import time
from typing import Any, Sequence

import numpy as np

_REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.tooling._surface_decompose import (
    SCORE_COLUMNS,
    ChainContext,
    PatchSpec,
    ProtenixAttemptPostprocessResult,
    RFD4AttemptPostprocessResult,
    SanitizedResidue,
    TargetPlan,
    _FAILURE_ORDER,
    _describe_zero_seed_stage,
    build_patch_specs,
    compile_patch_batch,
    describe_zero_seed_stage,
    match_rfd4_patch,
    postprocess_protenix_attempt,
    postprocess_rfd4_attempt,
    precompute_chain_patches,
    prepare_target_plans,
    sanitize_target_structure,
    write_attempt_pdb,
    write_seeds_pdb,
    write_success_pdb,
    write_zero_design_seeds,
)
from scripts.tooling.common import (
    BACKBONE_ATOMS,
    C2_SYMMETRY_SWAPS,
    CANONICAL_AA3_TO_1,
    CANONICAL_NON_GLY_AAS,
    WATERS,
    PaddedProtenixRunner,
    _check_gpu_memory_policy,
    _decode_sequence,
    _encoding_tables,
    _format_score,
    _load_rfd4_sampler,
    _normalize_blank_chain_ids,
    _wrap_padded_evaluator_class,
    coupled_kabsch_sidechain_rmsd,
    discover_pdb_paths,
    kabsch_superpose,
    prepare_output_dir,
)

__all__ = [
    "BACKBONE_ATOMS",
    "WATERS",
    "CANONICAL_AA3_TO_1",
    "CANONICAL_NON_GLY_AAS",
    "C2_SYMMETRY_SWAPS",
    "SCORE_COLUMNS",
    "_FAILURE_ORDER",
    "_encoding_tables",
    "SanitizedResidue",
    "PatchSpec",
    "ChainContext",
    "TargetPlan",
    "RFD4AttemptPostprocessResult",
    "ProtenixAttemptPostprocessResult",
    "discover_pdb_paths",
    "_normalize_blank_chain_ids",
    "sanitize_target_structure",
    "precompute_chain_patches",
    "build_patch_specs",
    "compile_patch_batch",
    "kabsch_superpose",
    "coupled_kabsch_sidechain_rmsd",
    "_load_rfd4_sampler",
    "match_rfd4_patch",
    "_wrap_padded_evaluator_class",
    "PaddedProtenixRunner",
    "write_attempt_pdb",
    "write_success_pdb",
    "write_seeds_pdb",
    "_decode_sequence",
    "_format_score",
    "_describe_zero_seed_stage",
    "_check_gpu_memory_policy",
    "postprocess_rfd4_attempt",
    "postprocess_protenix_attempt",
    "prepare_target_plans",
    "parse_args",
    "main",
]

logger = logging.getLogger("surface_decompose")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate CLI flags for ``surface_decompose.py``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in_path",
        type=pathlib.Path,
        required=True,
        help="Input .pdb file or directory of .pdb files.",
    )
    parser.add_argument(
        "--out_path",
        type=pathlib.Path,
        required=True,
        help="Output root directory for attempts/, success/, seeds/, and score.csv.",
    )
    parser.add_argument(
        "--num_aa",
        type=int,
        required=True,
        help="Total length of each designed RFD4 scaffold chain (>= 1).",
    )
    parser.add_argument(
        "--num_designs",
        type=int,
        default=100,
        help="Maximum attempts per isolated protein chain (>= 0).",
    )
    parser.add_argument(
        "--max_seed_attempts",
        type=int,
        default=10,
        help="Maximum draws as center_residue before retiring an uncovered seed (>= 1).",
    )
    parser.add_argument(
        "--cutoff",
        type=float,
        default=5.0,
        help="Spherical sidechain-to-seed heavy-atom cutoff in Angstroms (> 0.0).",
    )
    parser.add_argument(
        "--min_num_patch",
        type=int,
        default=5,
        help="Minimum surface residues required in a patch for seed eligibility (>= 3).",
    )
    parser.add_argument(
        "--interface_cutoff",
        type=float,
        default=8.0,
        help="Inter-chain CB-CB cutoff in Angstroms excluding interface residues from seeds (>= 0.0).",
    )
    parser.add_argument(
        "--f_rfd4_rmsd",
        type=float,
        default=1.0,
        help="Pre-fold RFD4 motif sidechain Kabsch RMSD upper bound (<) in Angstroms (> 0.0).",
    )
    parser.add_argument(
        "--f_sc_rmsd",
        type=float,
        default=2.0,
        help="Post-fold RFD4-vs-Protenix CA Kabsch RMSD upper bound (<) in Angstroms (> 0.0).",
    )
    parser.add_argument(
        "--f_motif_rmsd",
        type=float,
        default=1.0,
        help="Post-fold Protenix motif sidechain Kabsch RMSD upper bound (<) in Angstroms (> 0.0).",
    )
    parser.add_argument(
        "--f_plddt",
        type=float,
        default=0.85,
        help="Post-fold mean normalized pLDDT ([0, 1]) lower bound (>).",
    )
    parser.add_argument(
        "--f_pae",
        type=float,
        default=3.0,
        help="Post-fold mean unnormalized PAE upper bound (<) in Angstroms (> 0.0).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Master random seed for patch sampling, RFD4, and Protenix.",
    )
    parser.add_argument(
        "--protenix_model",
        type=str,
        default="protenix_base_default_v1.0.0",
        help="Protenix checkpoint identifier passed to flexcraft.structure.protenix.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Allow writing outputs into an existing non-empty --out_path directory.",
    )

    args = parser.parse_args(argv)

    if args.num_aa < 1:
        parser.error(f"--num_aa must be >= 1, got {args.num_aa}")
    if args.num_designs < 0:
        parser.error(f"--num_designs must be >= 0, got {args.num_designs}")
    if args.max_seed_attempts < 1:
        parser.error(
            f"--max_seed_attempts must be >= 1, got {args.max_seed_attempts}"
        )
    if args.min_num_patch < 3:
        parser.error(f"--min_num_patch must be >= 3, got {args.min_num_patch}")

    for flag, val in (
        ("--cutoff", args.cutoff),
        ("--f_rfd4_rmsd", args.f_rfd4_rmsd),
        ("--f_sc_rmsd", args.f_sc_rmsd),
        ("--f_motif_rmsd", args.f_motif_rmsd),
        ("--f_pae", args.f_pae),
    ):
        if not (math.isfinite(val) and val > 0.0):
            parser.error(f"{flag} must be finite and > 0.0, got {val}")

    if not (math.isfinite(args.interface_cutoff) and args.interface_cutoff >= 0.0):
        parser.error(
            f"--interface_cutoff must be finite and >= 0.0, got {args.interface_cutoff}"
        )
    if not (math.isfinite(args.f_plddt) and 0.0 <= args.f_plddt <= 1.0):
        parser.error(
            f"--f_plddt must be finite and in [0.0, 1.0], got {args.f_plddt}"
        )
    if not args.protenix_model or not args.protenix_model.strip():
        parser.error("--protenix_model must be a non-empty string")

    return args


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint for surface patch decomposition and scaffolding."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args(argv)

    pdb_paths = discover_pdb_paths(args.in_path)
    prepare_output_dir(
        args.out_path,
        overwrite=args.overwrite,
        subdirs=("attempts", "success", "seeds"),
    )

    score_csv_path = args.out_path / "score.csv"
    plans, m_max = prepare_target_plans(
        pdb_paths,
        interface_cutoff=args.interface_cutoff,
        cutoff=args.cutoff,
        min_num_patch=args.min_num_patch,
        log=logger,
    )

    with score_csv_path.open("w", newline="") as csv_fh:
        csv_writer = csv.writer(csv_fh)
        csv_writer.writerow(SCORE_COLUMNS)
        csv_fh.flush()

        if m_max == 0 or args.num_designs == 0:
            logger.info(
                "Skipping model initialization (M_max=%d, num_designs=%d); "
                "writing seed heatmaps only.",
                m_max,
                args.num_designs,
            )
            write_zero_design_seeds(plans, args.out_path / "seeds")
            return

        import jax
        from rfd4fx.flow_matching import THINKING_HIGH
        from rfd4fx.rfd4_input import RFD4Input

        _check_gpu_memory_policy(jax, log=logger)
        n_pad = ((args.num_aa + max(m_max, 1) + 63) // 64) * 64
        base_rfd4_input = RFD4Input.from_chains(args.num_aa)
        sampler = _load_rfd4_sampler()

        with PaddedProtenixRunner(
            num_aa=args.num_aa, model_name=args.protenix_model
        ) as protenix_runner:
            logger.info(
                "Compiled tensor ceilings: n_pad=%d, n_atom_pad=%d",
                n_pad,
                protenix_runner.n_atom_pad,
            )

            for target_idx, plan in enumerate(plans):
                valid_seed_sets: dict[str, set[str]] = {}
                seed_pass_counts: dict[str, dict[str, int]] = {}

                for chain_idx, ctx in enumerate(plan.chains):
                    valid_seed_sets[ctx.chain_id] = set(ctx.valid_seeds)
                    seed_pass_counts[ctx.chain_id] = {
                        tok: 0 for tok in ctx.valid_seeds
                    }
                    if not ctx.valid_seeds:
                        continue

                    covered: set[str] = set()
                    seed_attempts: dict[str, int] = {
                        tok: 0 for tok in ctx.valid_seeds
                    }
                    active_chain_batches: dict[str, Any] = {}
                    chain_rng = np.random.Generator(
                        np.random.PCG64(
                            np.random.SeedSequence(
                                [args.seed, target_idx, chain_idx]
                            )
                        )
                    )

                    n_attempts = 0
                    n_f_match = 0
                    n_f_rfd4_rmsd = 0
                    n_accepted = 0

                    for attempt in range(args.num_designs):
                        active_seeds = [
                            tok
                            for tok in ctx.valid_seeds
                            if tok not in covered
                            and seed_attempts[tok] < args.max_seed_attempts
                        ]
                        if not active_seeds:
                            break

                        n_attempts += 1
                        center_residue = active_seeds[
                            int(chain_rng.integers(0, len(active_seeds)))
                        ]
                        seed_attempts[center_residue] += 1
                        patch = ctx.patches[center_residue]

                        if center_residue not in active_chain_batches:
                            active_chain_batches[center_residue] = (
                                compile_patch_batch(
                                    base_rfd4_input, patch, n_pad
                                )
                            )
                        batch = active_chain_batches[center_residue]

                        attempt_key = jax.random.fold_in(
                            jax.random.fold_in(
                                jax.random.fold_in(
                                    jax.random.key(args.seed), target_idx
                                ),
                                chain_idx,
                            ),
                            attempt,
                        )
                        rfd4_key = jax.random.fold_in(attempt_key, 0)
                        protenix_key = jax.random.fold_in(attempt_key, 1)

                        t0 = time.perf_counter()
                        rfd4_res = sampler.sample(
                            batch,
                            key=rfd4_key,
                            recycle_schedule=THINKING_HIGH,
                        )
                        t_rfd4_s = time.perf_counter() - t0

                        covered_str = ";".join(patch.member_tokens)
                        pdb_filename = (
                            f"{plan.target_name}_{center_residue}_{attempt}.pdb"
                        )
                        rfd4_post = postprocess_rfd4_attempt(
                            rfd4_res,
                            target_name=plan.target_name,
                            chain_id=ctx.chain_id,
                            attempt=attempt,
                            center_residue=center_residue,
                            patch=patch,
                            num_aa=args.num_aa,
                            f_rfd4_rmsd=args.f_rfd4_rmsd,
                            attempt_pdb_path=args.out_path / "attempts" / pdb_filename,
                            covered_str=covered_str,
                        )

                        if rfd4_post.failure is not None:
                            assert rfd4_post.score_row is not None
                            csv_writer.writerow(rfd4_post.score_row)
                            csv_fh.flush()
                            if rfd4_post.failure == "f_match":
                                n_f_match += 1
                                logger.info(
                                    "%s %s attempt=%d seed=%s t_rfd4_s=%.3f failure=f_match",
                                    plan.target_name,
                                    ctx.chain_id,
                                    attempt,
                                    center_residue,
                                    t_rfd4_s,
                                )
                            else:
                                n_f_rfd4_rmsd += 1
                                logger.info(
                                    "%s %s attempt=%d seed=%s t_rfd4_s=%.3f "
                                    "rfd4_motif_rmsd=%.4f failure=f_rfd4_rmsd",
                                    plan.target_name,
                                    ctx.chain_id,
                                    attempt,
                                    center_residue,
                                    t_rfd4_s,
                                    rfd4_post.rfd4_motif_rmsd,
                                )
                            continue

                        assert (
                            rfd4_post.col_ind is not None
                            and rfd4_post.rfd4_motif_rmsd is not None
                        )

                        t1 = time.perf_counter()
                        (
                            protenix_res,
                            writer,
                            sample_coords_ang,
                            res_plddt,
                            atom_to_token_idx,
                        ) = protenix_runner.fold_sequence(
                            protenix_key, rfd4_post.sequence
                        )
                        t_protenix_s = time.perf_counter() - t1

                        prot_post = postprocess_protenix_attempt(
                            protenix_res,
                            writer,
                            sample_coords_ang,
                            res_plddt,
                            atom_to_token_idx,
                            target_name=plan.target_name,
                            chain_id=ctx.chain_id,
                            attempt=attempt,
                            center_residue=center_residue,
                            patch=patch,
                            sequence=rfd4_post.sequence,
                            coors_ang=rfd4_post.coors_ang,
                            col_ind=rfd4_post.col_ind,
                            rfd4_motif_rmsd=rfd4_post.rfd4_motif_rmsd,
                            num_aa=args.num_aa,
                            f_sc_rmsd=args.f_sc_rmsd,
                            f_motif_rmsd=args.f_motif_rmsd,
                            f_plddt=args.f_plddt,
                            f_pae=args.f_pae,
                            success_pdb_path=args.out_path / "success" / pdb_filename,
                            covered_str=covered_str,
                        )

                        if prot_post.accepted:
                            n_accepted += 1
                            for tok in patch.valid_seed_tokens:
                                covered.add(tok)
                                seed_pass_counts[ctx.chain_id][tok] += 1

                        csv_writer.writerow(prot_post.score_row)
                        csv_fh.flush()
                        logger.info(
                            "%s %s attempt=%d seed=%s t_rfd4_s=%.3f "
                            "t_protenix_s=%.3f sc_rmsd=%.4f motif_rmsd=%.4f "
                            "mean_plddt=%.4f mean_pae=%.4f failure=%s",
                            plan.target_name,
                            ctx.chain_id,
                            attempt,
                            center_residue,
                            t_rfd4_s,
                            t_protenix_s,
                            prot_post.sc_rmsd,
                            prot_post.motif_rmsd,
                            prot_post.mean_plddt,
                            prot_post.mean_pae,
                            prot_post.failure_str,
                        )

                    active_chain_batches.clear()
                    logger.info(
                        "Chain summary %s %s: n_attempts=%d n_f_match=%d "
                        "n_f_rfd4_rmsd=%d n_accepted=%d covered=%d/%d",
                        plan.target_name,
                        ctx.chain_id,
                        n_attempts,
                        n_f_match,
                        n_f_rfd4_rmsd,
                        n_accepted,
                        len(covered),
                        len(ctx.valid_seeds),
                    )

                write_seeds_pdb(
                    plan.sanitized_structure,
                    args.out_path / "seeds" / f"{plan.target_name}.pdb",
                    valid_seed_sets=valid_seed_sets,
                    seed_pass_counts=seed_pass_counts,
                )


if __name__ == "__main__":
    main()
