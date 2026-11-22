#!/usr/bin/env python3
"""Write one Boltz-2 input YAML per (protein variant x ligand) pair.

Layout produced under --work::

    msa/<GENE>__<VARIANT>.a3m              (from prepare_msas.py)
    jobs/<GENE>/<GENE>__<VARIANT>__<DRUG>.yaml
    manifest.tsv

Two constraints from the Boltz source drive the layout:

* ``msa:`` is resolved against the *current working directory*, not against the
  YAML's own directory, so the path written here is absolute.
* ``boltz predict <dir>`` is non-recursive and raises RuntimeError on any
  subdirectory or non-YAML file, so jobs/<GENE>/ holds YAML files and nothing else.

The job name doubles as the output directory name, so the gene, variant and drug
are encoded in the filename -- that is the only key available when collecting results.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Job, iter_gene_dirs, load_ligands, load_variants  # noqa: E402

YAML_TEMPLATE = """version: 1
sequences:
  - protein:
      id: A
      sequence: {sequence}
      msa: {msa}
  - ligand:
      id: B
      smiles: '{smiles}'
properties:
  - affinity:
      binder: B
"""


def write_yaml(job: Job, path: Path, msa_path: Path, affinity: bool) -> None:
    text = YAML_TEMPLATE.format(
        sequence=job.variant.sequence,
        msa=msa_path.resolve(),
        smiles=job.smiles,
    )
    if not affinity:
        text = text.split("properties:")[0]
    path.write_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="consolidated_projects directory")
    ap.add_argument("--work", type=Path, default=Path("boltz2_work"), help="output directory")
    ap.add_argument("--gene", action="append", dest="genes", help="restrict to these genes (repeatable)")
    ap.add_argument("--no-affinity", action="store_true", help="omit the affinity block (structure only)")
    ap.add_argument("--max-length", type=int, default=0, help="skip proteins longer than this (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true", help="report counts without writing YAMLs")
    args = ap.parse_args()

    msa_dir = args.work / "msa"
    jobs_dir = args.work / "jobs"

    rows: list[dict[str, object]] = []
    skipped_no_msa: list[str] = []
    skipped_long: list[str] = []
    written = 0

    for gene_dir in iter_gene_dirs(args.root):
        gene = gene_dir.name
        if args.genes and gene not in args.genes:
            continue
        wt, mutants = load_variants(gene_dir)
        ligands = load_ligands(gene_dir)
        if not ligands:
            continue

        gene_jobs_dir = jobs_dir / gene
        if not args.dry_run:
            gene_jobs_dir.mkdir(parents=True, exist_ok=True)

        for variant in ([wt] if wt else []) + mutants:
            if args.max_length and len(variant.sequence) > args.max_length:
                skipped_long.append(f"{variant.key} ({len(variant.sequence)} aa)")
                continue
            msa_path = msa_dir / f"{variant.key}.a3m"
            if not msa_path.exists() and not args.dry_run:
                skipped_no_msa.append(variant.key)
                continue
            for drug, smiles in ligands.items():
                job = Job(variant=variant, drug=drug, smiles=smiles)
                if not args.dry_run:
                    write_yaml(job, gene_jobs_dir / f"{job.name}.yaml", msa_path, not args.no_affinity)
                written += 1
                rows.append({
                    "job": job.name,
                    "gene": gene,
                    "variant": variant.name,
                    "is_wt": int(variant.is_wt),
                    "drug": drug,
                    "length": len(variant.sequence),
                    "pdb": str(variant.pdb),
                })

    if not args.dry_run:
        args.work.mkdir(parents=True, exist_ok=True)
        with (args.work / "manifest.tsv").open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t") if rows else None
            if writer:
                writer.writeheader()
                writer.writerows(rows)

    verb = "would write" if args.dry_run else "wrote"
    genes = {r["gene"] for r in rows}
    structures = {(r["gene"], r["variant"]) for r in rows}
    print(f"{verb} {written} YAMLs over {len(genes)} genes and {len(structures)} structures")
    if skipped_no_msa:
        print(f"\n{len(skipped_no_msa)} structure(s) skipped, no MSA yet (run prepare_msas.py):")
        for key in skipped_no_msa[:20]:
            print(f"  - {key}")
        if len(skipped_no_msa) > 20:
            print(f"  ... and {len(skipped_no_msa) - 20} more")
    if skipped_long:
        print(f"\n{len(skipped_long)} structure(s) over --max-length:")
        for key in skipped_long:
            print(f"  - {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
