#!/usr/bin/env python3
"""CLI runner for De Novo Protein Binder Design campaigns."""

import argparse
import os
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pipeline import DeNovoBinderPipeline


def main():
    parser = argparse.ArgumentParser(
        description="Run an automated De Novo Protein Binder Design campaign targeting any PDB structure."
    )
    parser.add_argument(
        "--target",
        default="data/4ZQK.pdb",
        help="Path to target PDB structure (default: data/4ZQK.pdb - Human PD-L1).",
    )
    parser.add_argument(
        "--target-chain",
        default="A",
        help="Target chain ID (default: 'A').",
    )
    parser.add_argument(
        "--partner-chain",
        default="B",
        help="Partner chain in complex for automatic hotspot identification (default: 'B').",
    )
    parser.add_argument(
        "--hotspots",
        help="Comma-separated list of target residue numbers (e.g. '56,66,115,122,123,124').",
    )
    parser.add_argument(
        "--num-backbones",
        type=int,
        default=15,
        help="Number of diverse de novo backbones to generate (default: 15).",
    )
    parser.add_argument(
        "--seqs-per-backbone",
        type=int,
        default=2,
        help="Number of sequences to decode per backbone (default: 2).",
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Directory to save designed candidate structures and figures (default: 'results').",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42).",
    )

    args = parser.parse_args()

    hotspots = None
    if args.hotspots:
        hotspots = [int(h.strip()) for h in args.hotspots.split(",") if h.strip()]

    pipeline = DeNovoBinderPipeline(
        target_pdb=args.target,
        target_chain=args.target_chain,
        seed=args.seed,
    )

    pipeline.run_campaign(
        hotspot_res_nums=hotspots,
        partner_chain=args.partner_chain,
        num_backbones=args.num_backbones,
        seqs_per_backbone=args.seqs_per_backbone,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
