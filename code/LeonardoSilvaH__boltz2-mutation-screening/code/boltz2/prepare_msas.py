#!/usr/bin/env python3
"""Fetch one MSA per modelled structure, hitting the MSA server once per gene.

There are ~230 structures but only ~37 distinct proteins: every mutant differs
from its wild-type by a single residue. Letting ``--use_msa_server`` run per job
would mean thousands of calls to api.colabfold.com. Instead we search once per
gene on the wild-type sequence and derive each mutant's .a3m from it by patching
the query row -- same length, so every alignment column stays valid.

A variant whose sequence is not the same length as its wild-type (a truncated or
frame-shifted model) cannot share the alignment and gets its own search.

Usage::

    python boltz2/prepare_msas.py --root /path/to/consolidated_projects \
                                  --work boltz2_work [--gene KRAS ...]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Variant, iter_gene_dirs, load_variants  # noqa: E402


def split_a3m(text: str) -> tuple[list[str], str, list[str]]:
    """Split an a3m into (leading lines, query sequence, remaining lines)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(">"):
            if i + 1 >= len(lines):
                raise ValueError("a3m header has no sequence line")
            return lines[: i + 1], lines[i + 1], lines[i + 2 :]
    raise ValueError("no FASTA header found in a3m")


def retarget_a3m(wt_a3m: str, sequence: str) -> str:
    """Return *wt_a3m* with its query row replaced by *sequence*.

    Only valid when the two sequences are the same length: the query row of an
    a3m is gapless, so substituting one residue leaves every column aligned.
    """
    head, query, rest = split_a3m(wt_a3m)
    if len(query) != len(sequence):
        raise ValueError(f"length mismatch: query {len(query)} vs variant {len(sequence)}")
    return "\n".join([*head, sequence, *rest]) + "\n"


def search(sequence: str, prefix: Path, host: str) -> str:
    """Run one MMseqs2 search through Boltz's ColabFold client."""
    from boltz.data.msa.mmseqs2 import run_mmseqs2

    prefix.parent.mkdir(parents=True, exist_ok=True)
    result = run_mmseqs2([sequence], str(prefix), use_env=True, use_pairing=False, host_url=host)
    if not result:
        raise RuntimeError(f"MSA server returned nothing for {prefix.name}")
    return result[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True, help="consolidated_projects directory")
    ap.add_argument("--work", type=Path, default=Path("boltz2_work"), help="output directory")
    ap.add_argument("--gene", action="append", dest="genes", help="restrict to these genes (repeatable)")
    ap.add_argument("--host", default="https://api.colabfold.com", help="MSA server URL")
    ap.add_argument("--sleep", type=float, default=2.0, help="pause between gene searches, seconds")
    ap.add_argument("--force", action="store_true", help="re-fetch MSAs that already exist")
    args = ap.parse_args()

    msa_dir = args.work / "msa"
    msa_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = args.work / "mmseqs_tmp"

    problems: list[str] = []
    fetched = 0

    for gene_dir in iter_gene_dirs(args.root):
        gene = gene_dir.name
        if args.genes and gene not in args.genes:
            continue
        wt, mutants = load_variants(gene_dir)
        if wt is None:
            problems.append(f"{gene}: no wild-type structure, skipped entirely")
            continue

        wt_path = msa_dir / f"{wt.key}.a3m"
        if args.force or not wt_path.exists():
            print(f"[{gene}] searching wild-type ({len(wt.sequence)} aa)", flush=True)
            try:
                wt_a3m = search(wt.sequence, tmp_dir / gene / "wt", args.host)
            except Exception as exc:  # network / server errors are expected here
                problems.append(f"{gene}: wild-type search failed: {exc}")
                continue
            wt_path.write_text(wt_a3m if wt_a3m.endswith("\n") else wt_a3m + "\n")
            fetched += 1
            time.sleep(args.sleep)
        wt_a3m = wt_path.read_text()

        for variant in mutants:
            out = msa_dir / f"{variant.key}.a3m"
            if out.exists() and not args.force:
                continue
            try:
                out.write_text(retarget_a3m(wt_a3m, variant.sequence))
            except ValueError as exc:
                # Not a clean single substitution -- needs its own search.
                problems.append(f"{gene}/{variant.name}: {exc}; searched separately")
                print(f"[{gene}] {variant.name} differs in length, separate search", flush=True)
                try:
                    own = search(variant.sequence, tmp_dir / gene / variant.name, args.host)
                except Exception as err:
                    problems.append(f"{gene}/{variant.name}: search failed: {err}")
                    continue
                out.write_text(own if own.endswith("\n") else own + "\n")
                fetched += 1
                time.sleep(args.sleep)

    total = len(list(msa_dir.glob("*.a3m")))
    print(f"\n{total} MSAs in {msa_dir} ({fetched} server searches this run)")
    if problems:
        print(f"\n{len(problems)} issue(s):")
        for line in problems:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
