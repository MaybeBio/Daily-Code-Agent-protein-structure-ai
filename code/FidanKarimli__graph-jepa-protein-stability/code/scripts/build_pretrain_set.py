"""Choose the SCOPe domains to pretrain on and remove anything resembling MegaScale.

Run from the repo root:  python scripts/build_pretrain_set.py

Writes data/processed/pretrain_ids.txt (what we pretrain on) and removed_similar.txt
(what the filter threw out, kept so the decision stays auditable). Without this filter the
model could meet a test protein during pretraining and the final scores would flatter it.

The AlphaFold corpus is filtered the same way inside scripts/download_alphafold.py.
"""
import argparse
import sys
from pathlib import Path

from pobj.data.pretrain_set import (domain_files, mmseqs_similar, read_domains,
                                    write_fasta, write_megascale_fasta)

PROCESSED = Path("data/processed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-dir", default="data/raw/scope")
    parser.add_argument("--skip-search", action="store_true",
                        help="reuse the existing hits file instead of running mmseqs")
    args = parser.parse_args()

    PROCESSED.mkdir(parents=True, exist_ok=True)

    paths = domain_files(args.scope_dir)
    if not paths:
        sys.exit(f"no .ent files under {args.scope_dir}; run scripts/download_scope.sh first")
    print(f"{len(paths):,} SCOPe domain files")

    structures, dropped = read_domains(paths)
    lengths = sorted(len(seq) for seq, _ in structures.values())
    print(f"after length and completeness filtering: {len(structures):,} domains")
    print(f"  dropped: {dropped}")
    print(f"  length: min {lengths[0]}  median {lengths[len(lengths) // 2]}  max {lengths[-1]}")

    scope_fa = PROCESSED / "scope.fasta"
    mega_fa = PROCESSED / "megascale.fasta"
    write_fasta(scope_fa, {name: seq for name, (seq, _) in structures.items()})
    n_targets = write_megascale_fasta(mega_fa)
    print(f"searching against {n_targets} MegaScale proteins")

    removed, close = mmseqs_similar(scope_fa, mega_fa,
                                    PROCESSED / "scope_vs_megascale.m8",
                                    PROCESSED / "mmseqs_tmp",
                                    rerun=not args.skip_search)
    kept = sorted(set(structures) - removed)

    print(f"\nhits: {len(removed):,} domains ({len(close):,} at 30% identity or more)")
    print(f"removed {len(removed):,}, keeping {len(kept):,} domains for pretraining")

    (PROCESSED / "pretrain_ids.txt").write_text("\n".join(kept) + "\n")
    (PROCESSED / "removed_similar.txt").write_text("\n".join(sorted(removed)) + "\n")
    print(f"wrote {PROCESSED / 'pretrain_ids.txt'} and {PROCESSED / 'removed_similar.txt'}")


if __name__ == "__main__":
    main()
