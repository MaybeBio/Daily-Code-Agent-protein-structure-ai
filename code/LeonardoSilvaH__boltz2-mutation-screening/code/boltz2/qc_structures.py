#!/usr/bin/env python3
"""Check every structure and ligand before committing GPU time to them.

Reports, per gene:

* missing wild-type, or variant directories with no .pdb;
* mutants whose sequence is not a clean single substitution of the wild-type
  (truncated models, frame shifts, extra changes) -- these cannot share the
  wild-type MSA and are usually a modelling mistake worth fixing first;
* unknown residues ('X') in a sequence;
* ligands RDKit cannot parse, and ligands over Boltz-2's 128-atom affinity limit;
* the largest proteins, which are the ones at risk of exhausting GPU memory.

Exits non-zero if any blocking problem is found, so it can gate a run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WT_DIRNAME, extract_sequence, iter_gene_dirs, load_variants  # noqa: E402

AFFINITY_ATOM_LIMIT = 128
AFFINITY_RECOMMENDED = 56


def describe_difference(wt: str, mut: str) -> str:
    """Summarise how a mutant sequence departs from the wild-type."""
    if len(wt) != len(mut):
        return f"length {len(mut)} vs wild-type {len(wt)}"
    diffs = [(i + 1, a, b) for i, (a, b) in enumerate(zip(wt, mut)) if a != b]
    if len(diffs) == 1:
        return ""
    if not diffs:
        return "identical to wild-type"
    shown = ", ".join(f"{a}{i}{b}" for i, a, b in diffs[:5])
    return f"{len(diffs)} substitutions ({shown}{', ...' if len(diffs) > 5 else ''})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="consolidated_projects directory")
    ap.add_argument("--gene", action="append", dest="genes", help="restrict to these genes (repeatable)")
    args = ap.parse_args()

    from rdkit import Chem, RDLogger

    RDLogger.DisableLog("rdApp.*")

    blocking: list[str] = []
    warnings: list[str] = []
    lengths: list[tuple[int, str]] = []
    n_structures = n_jobs = 0

    for gene_dir in iter_gene_dirs(args.root):
        gene = gene_dir.name
        if args.genes and gene not in args.genes:
            continue

        for sub in sorted(p for p in gene_dir.iterdir() if p.is_dir()):
            if not list(sub.glob("*.pdb")):
                blocking.append(f"{gene}/{sub.name}: no .pdb file")

        wt, mutants = load_variants(gene_dir)
        if wt is None:
            blocking.append(f"{gene}: no {WT_DIRNAME}/ structure -- mutants have nothing to compare against")

        for variant in ([wt] if wt else []) + mutants:
            n_structures += 1
            lengths.append((len(variant.sequence), variant.key))
            if "X" in variant.sequence:
                warnings.append(
                    f"{variant.key}: {variant.sequence.count('X')} unknown residue(s) in the sequence"
                )
            if wt is not None and not variant.is_wt:
                note = describe_difference(wt.sequence, variant.sequence)
                if note:
                    blocking.append(f"{gene}/{variant.name}: {note}")

        ligands = 0
        for sdf in sorted(gene_dir.glob("*.sdf")):
            mol = next(Chem.ForwardSDMolSupplier(str(sdf)), None)
            if mol is None:
                blocking.append(f"{gene}/{sdf.name}: RDKit cannot parse this SDF")
                continue
            ligands += 1
            n_atoms = Chem.AddHs(mol).GetNumAtoms()
            if n_atoms > AFFINITY_ATOM_LIMIT:
                blocking.append(f"{gene}/{sdf.stem}: {n_atoms} atoms, over the {AFFINITY_ATOM_LIMIT}-atom affinity limit")
            elif n_atoms > AFFINITY_RECOMMENDED:
                warnings.append(f"{gene}/{sdf.stem}: {n_atoms} atoms, above the {AFFINITY_RECOMMENDED}-atom training range")
        n_jobs += ligands * (len(mutants) + (1 if wt else 0))

    print(f"{n_structures} structures, {n_jobs} protein x ligand jobs\n")

    lengths.sort(reverse=True)
    print("largest proteins (GPU memory risk):")
    for length, key in lengths[:5]:
        print(f"  {length:>5} aa  {key}")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for line in warnings[:30]:
            print(f"  - {line}")
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more")

    if blocking:
        print(f"\n{len(blocking)} problem(s) to resolve before running:")
        for line in blocking:
            print(f"  - {line}")
        return 1

    print("\nNo blocking problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
