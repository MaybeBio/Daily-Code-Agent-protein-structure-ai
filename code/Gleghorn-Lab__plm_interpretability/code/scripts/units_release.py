"""Release the native-unit study's results, without its activation stores, as the paper's third archive.

    python scripts/units_release.py --source <owner>/<run dataset> --target <owner>/<archive> --work <folder> \
        --preregistration <preregistration.yaml> --card <README.md> [--apply]

The run's own dataset holds every pass's activation maxima, checkpoints and pilots, about a terabyte, beside the tables
the paper reads. This copies the tables and leaves the rest: every file of the kept folders with a kept suffix, minus
the patterns left out below. Without `--apply` it prints the plan, each kept folder with its files and size and what is
left out; with it, it downloads the kept files into `--work`, adds the preregistration and the card, and uploads them
to a private dataset, whose visibility a person changes.
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil

from collections import Counter
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download


# Tables, receipts, generated tables and figures; `.npz` and `.gz` only where a kept folder holds a small one.
KEPT_SUFFIXES = (".parquet", ".json", ".tex", ".png", ".npz", ".gz")
# The second line holds what the paper added on 2026-11-18: E15's four readings after Goodfire (communities and their
# dictionary by activation, concept groups, erasure levels, sparsity and write sums) and the exploratory exemplars of
# Fig. 5E. E16 (`e16`, `prune_*`) is not in the paper and stays in the run's dataset.
KEPT_FOLDERS = ("inputs", "passes", "missing", "concepts", "panel", "dictionary", "causal", "exemplars", "retest", "retest_esmc",
                "strength", "wiring", "coalitions", "e14", "figures", "tables", "checks", "parity", "pins", "sae_labels",
                "communities", "communities_activation", "concept_groups", "erasure_levels", "sparsify", "write_sums", "e15",
                "exemplar_concepts")
KEPT_FILES = ("decisions.json",)
# Each community graph's count of prompts that keep each unit, and its always-on units; every other `.npy` of the run is
# an activation store and is left out.
KEPT_ARRAYS = ("communities/*.npy", "communities_activation/*.npy")
# Folders left out whole: the passes' pilots, the atlas study's held-out shards (`examined`, another release's files) and
# the upload receipts and logs. Left out of the kept folders: another release's data, raw downloads and the found
# rotations' matrices.
LEFT_OUT = (
    "concepts/data/*",  # version one's concept datasets, public as GleghornLab/protein_concept_probing
    "missing/search/*",  # the homology search's FASTA files and hits
    "retest/annotations/*", "retest/uniprot_sprot*",  # InterPLM's evaluation set and the Swiss-Prot table it is built from
    "retest_esmc/*/*.npz",  # the sparsest-rotation search's matrices
    "sae_labels/*.parquet", "sae_labels/*/*",  # tables that quote another release's feature descriptions
    # Each prompt's attributed units (743 MB a dictionary), which the attribution stage rebuilds from the pinned model;
    # the tests and their tables are kept.
    "communities/attribution/*", "communities_activation/attribution/*",
)


def kept(path: str) -> bool:
    """Whether the release keeps the run's file at `path`."""
    if path in KEPT_FILES or any(fnmatch.fnmatch(path, pattern) for pattern in KEPT_ARRAYS):
        return True
    if path.split("/")[0] not in KEPT_FOLDERS or not path.endswith(KEPT_SUFFIXES):
        return False
    return not any(fnmatch.fnmatch(path, pattern) for pattern in LEFT_OUT)


def plan(api: HfApi, source: str) -> tuple[dict[str, int], dict[str, int]]:
    """The run's files the release keeps and leaves out, each with its size in bytes."""
    files = {file.rfilename: file.size or 0 for file in api.repo_info(source, repo_type="dataset", files_metadata=True).siblings}
    keep = {path: size for path, size in files.items() if kept(path)}
    return keep, {path: size for path, size in files.items() if path not in keep}


def report(keep: dict[str, int], rest: dict[str, int]) -> None:
    sizes: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for path, size in keep.items():
        sizes[path.split("/")[0]] += size
        counts[path.split("/")[0]] += 1
    for folder in sorted(sizes):
        print(f"keep {folder}: {counts[folder]} files, {sizes[folder] / 1e6:.1f} MB")
    print(f"kept {len(keep)} files, {sum(keep.values()) / 1e6:.1f} MB; left out {len(rest)} files, {sum(rest.values()) / 1e9:.1f} GB")
    largest = max(keep, key=keep.__getitem__)
    print(f"largest kept file: {largest}, {keep[largest] / 1e6:.1f} MB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--card", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    api = HfApi()
    source_revision = api.repo_info(args.source, repo_type="dataset").sha
    keep, rest = plan(api, args.source)
    report(keep, rest)
    if not args.apply:
        return
    snapshot_download(args.source, repo_type="dataset", revision=source_revision, local_dir=args.work, allow_patterns=sorted(keep), max_workers=4)
    missing = [path for path in keep if not (args.work / path).is_file()]
    assert not missing, missing[:5]
    shutil.copyfile(args.preregistration, args.work / "preregistration.yaml")
    shutil.copyfile(args.card, args.work / "README.md")
    api.create_repo(args.target, repo_type="dataset", private=True, exist_ok=True)
    commit = api.upload_folder(repo_id=args.target, repo_type="dataset", folder_path=args.work, allow_patterns=[*sorted(keep), "preregistration.yaml", "README.md"],
                               commit_message=f"The native-unit study's results, from the run's dataset at {source_revision[:8]}")
    print(f"released {len(keep)} files to {args.target} at {commit.oid[:8]}, private")


if __name__ == "__main__":
    main()
