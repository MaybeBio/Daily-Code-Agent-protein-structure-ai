#!/usr/bin/env python3
"""TM-score diversity analysis for predicted structure motifs.

Implements the diversity analysis described in PGEL:
  1. Compute pairwise TM-scores between selected candidate motif regions.
  2. Hierarchically cluster candidates at one or more TM-score thresholds.
  3. Report diversity as the number of clusters.
  4. Compare each candidate's motif to a native motif. A cluster is called
     distinguishable from native at threshold tm when at least one member has
     native-motif TM-score < tm.

Requires TM-align or USalign, SciPy, NumPy, and Matplotlib.
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import squareform

TM_SCORE_RE = re.compile(r"TM-score\s*=\s*([0-9]*\.?[0-9]+)")
AA3 = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS",
    "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP",
    "TYR", "VAL",
}


def find_pdbs(input_dir: Path, pattern: str) -> list[Path]:
    paths = sorted(input_dir.glob(pattern))
    if not paths:
        raise FileNotFoundError(f"No structures matched {input_dir / pattern}")
    return paths


def parse_tm_scores(output: str) -> list[float]:
    scores = [float(x) for x in TM_SCORE_RE.findall(output)]
    if not scores:
        raise RuntimeError("Could not find TM-score in TM-align/USalign output")
    return scores


def run_tm_align(executable: str, a: Path, b: Path, timeout: int, mode: str) -> float:
    result = subprocess.run(
        [executable, str(a), str(b)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"TM-align failed for {a.name} vs {b.name}:\n{output}")
    scores = parse_tm_scores(output)
    if mode == "max":
        return max(scores)
    if mode == "mean":
        return float(np.mean(scores))
    return scores[0]


def pairwise_tm_scores(paths: list[Path], executable: str, timeout: int, mode: str) -> np.ndarray:
    n = len(paths)
    matrix = np.eye(n, dtype=float)
    total = n * (n - 1) // 2
    done = 0
    for i in range(n):
        for j in range(i + 1, n):
            score = run_tm_align(executable, paths[i], paths[j], timeout, mode)
            matrix[i, j] = matrix[j, i] = score
            done += 1
            print(f"[{done}/{total}] {paths[i].name} vs {paths[j].name}: {score:.4f}", file=sys.stderr)
    return matrix


def extract_region(
    source: Path,
    destination: Path,
    chain: str,
    ranges: list[tuple[int, int]],
    output_chain: str | None = None,
) -> None:
    """Extract protein records for selected residue ranges from one PDB chain.

    If output_chain is supplied, rewrite the extracted records to that chain
    ID. This is useful when PGEL outputs use a different chain ID from the
    native input, e.g. candidate chain A versus native chain H.
    """
    kept = []
    output_chain = output_chain or chain
    if len(output_chain) != 1:
        raise ValueError("Chain IDs must be one character")

    with source.open() as handle:
        for line in handle:
            if not (line.startswith("ATOM  ") or line.startswith("HETATM")):
                continue
            if len(line) < 26 or line[21].strip() != chain:
                continue
            if line[17:20].strip() not in AA3:
                continue
            try:
                residue_number = int(line[22:26])
            except ValueError:
                continue
            if any(start <= residue_number <= end for start, end in ranges):
                rewritten = line[:21] + output_chain + line[22:66].rstrip() + "\n"
                kept.append(rewritten)

    if not kept:
        range_text = ",".join(f"{start}-{end}" for start, end in ranges)
        raise ValueError(f"No residues found in {source}: chain {chain}, {range_text}")
    destination.write_text("".join(kept) + "END\n")


def parse_motif_ranges(value: str) -> list[tuple[int, int]]:
    """Parse comma-separated inclusive ranges, e.g. ``29-34,94-114``."""
    ranges = []
    try:
        for item in value.split(","):
            start, end = (int(part) for part in item.strip().split("-", maxsplit=1))
            if start > end:
                raise ValueError
            ranges.append((start, end))
    except ValueError as exc:
        raise ValueError("--motif-range must be START-END[,START-END...]") from exc
    if not ranges:
        raise ValueError("--motif-range must contain at least one range")
    return ranges


def extract_candidate_motifs(
    candidates: list[Path],
    destination_dir: Path,
    chain: str,
    ranges: list[tuple[int, int]],
) -> list[Path]:
    motif_paths = []
    for candidate in candidates:
        motif_path = destination_dir / candidate.name
        extract_region(candidate, motif_path, chain, ranges)
        motif_paths.append(motif_path)
    return motif_paths


def motif_tm_scores(
    candidates: list[Path],
    native_pdb: Path,
    executable: str,
    timeout: int,
    mode: str,
    native_chain: str,
    candidate_chain: str,
    ranges: list[tuple[int, int]],
) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="tm_motif_") as tmp:
        tmpdir = Path(tmp)
        native_motif = tmpdir / "native_motif.pdb"
        extract_region(native_pdb, native_motif, native_chain, ranges, output_chain="H")
        values = []
        for candidate in candidates:
            candidate_motif = tmpdir / f"{candidate.stem}_motif.pdb"
            extract_region(candidate, candidate_motif, candidate_chain, ranges, output_chain="H")
            values.append(run_tm_align(executable, candidate_motif, native_motif, timeout, mode))
            print(f"{candidate.name}: native motif TM-score={values[-1]:.4f}", file=sys.stderr)
        return np.asarray(values, dtype=float)


def cluster_at_threshold(tm_matrix: np.ndarray, tm_threshold: float, method: str) -> tuple[np.ndarray, object | None]:
    if not 0.0 < tm_threshold <= 1.0:
        raise ValueError("TM thresholds must be > 0 and <= 1")
    distance = 1.0 - tm_matrix
    n = len(tm_matrix)
    if n == 1:
        return np.ones(1, dtype=int), None
    tree = linkage(squareform(distance, checks=False), method=method)
    clusters = fcluster(tree, t=1.0 - tm_threshold, criterion="distance")
    return clusters, tree


def save_dendrogram(tree, labels: list[str], tm_threshold: float, output: Path) -> None:
    plt.figure(figsize=(max(10, 0.35 * len(labels)), 7))
    if tree is None:
        plt.text(0.5, 0.5, labels[0], ha="center", va="center", fontsize=12)
        plt.xlim(0, 1)
        plt.ylim(0, 1)
    else:
        cutoff = 1.0 - tm_threshold
        dendrogram(tree, labels=labels, color_threshold=cutoff, leaf_rotation=90, leaf_font_size=8)
        plt.axhline(cutoff, color="black", linestyle="--", linewidth=1,
                    label=f"TM-score threshold = {tm_threshold:.3f}")
        plt.legend()
    plt.ylabel("Dissimilarity (1 - TM-score)")
    plt.title("Hierarchical clustering of predicted structures")
    plt.tight_layout()
    plt.savefig(output, dpi=300)
    plt.close()


def write_matrix(path: Path, labels: list[str], matrix: np.ndarray, header: str) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([header, *labels])
        for label, row in zip(labels, matrix):
            writer.writerow([label, *[f"{x:.8f}" for x in row]])


def main() -> None:
    parser = argparse.ArgumentParser(description="Motif-only TM-score diversity and native-motif distinguishability")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="*.pdb")
    parser.add_argument("--tmalign", default="TMalign", help="TM-align or USalign executable")
    parser.add_argument("--tm-thresholds", default="0.4", help="Comma-separated thresholds, e.g. 0.5,0.6,0.7,0.8")
    parser.add_argument("--linkage", choices=["average", "complete", "single"], default="average")
    parser.add_argument("--score-mode", choices=["max", "mean", "first"], default="max")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output-prefix", type=Path, default=Path("tm_diversity"))
    parser.add_argument("--native-pdb", type=Path, help="Native/reference PDB for motif comparison")
    parser.add_argument("--motif-chain", default="H", help="Native motif chain; default: H")
    parser.add_argument(
        "--candidate-motif-chain",
        required=True,
        help="Chain containing the motif in candidate PDBs, e.g. A for standard PGEL outputs.",
    )
    parser.add_argument(
        "--motif-range",
        required=True,
        help="Inclusive motif range(s) for candidate-only pairwise scoring, e.g. 83-122 or 29-34,94-114",
    )
    args = parser.parse_args()

    thresholds = [float(x) for x in args.tm_thresholds.split(",")]
    paths = find_pdbs(args.input_dir, args.pattern)
    labels = [p.stem for p in paths]
    print(f"Found {len(paths)} structures", file=sys.stderr)

    motif_ranges = parse_motif_ranges(args.motif_range)
    candidate_chain = args.candidate_motif_chain
    with tempfile.TemporaryDirectory(prefix="tm_candidates_") as tmp:
        motif_paths = extract_candidate_motifs(
            paths, Path(tmp), candidate_chain, motif_ranges
        )
        print(
            f"Computing pairwise TM-scores on chain {candidate_chain}, "
            f"residue range(s) {args.motif_range}",
            file=sys.stderr,
        )
        tm_matrix = pairwise_tm_scores(
            motif_paths, args.tmalign, args.timeout, args.score_mode
        )
    write_matrix(Path(f"{args.output_prefix}_pairwise_tm.csv"), labels, tm_matrix, "structure")

    native_scores = None
    if args.native_pdb:
        print(
            f"Extracting native motif from chain {args.motif_chain}; "
            f"candidate motifs from chain {candidate_chain}; "
            f"rewriting both temporary motifs to chain H",
            file=sys.stderr,
        )
        native_scores = motif_tm_scores(
            paths,
            args.native_pdb,
            args.tmalign,
            args.timeout,
            args.score_mode,
            args.motif_chain,
            candidate_chain,
            motif_ranges,
        )
        with Path(f"{args.output_prefix}_native_motif_tm.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["structure", "native_motif_tm_score"])
            writer.writerows((p.name, f"{x:.8f}") for p, x in zip(paths, native_scores))

    summary_rows = []
    for threshold in thresholds:
        clusters, tree = cluster_at_threshold(tm_matrix, threshold, args.linkage)
        cluster_count = len(set(clusters))
        dendro = Path(f"{args.output_prefix}_tm{threshold:.3f}_dendrogram.png")
        save_dendrogram(tree, labels, threshold, dendro)

        assignments = Path(f"{args.output_prefix}_tm{threshold:.3f}_clusters.csv")
        with assignments.open("w", newline="") as handle:
            writer = csv.writer(handle)
            header = ["structure", "cluster"]
            if native_scores is not None:
                header += ["native_motif_tm_score", "cluster_distinguishable_from_native"]
            writer.writerow(header)
            for i, (p, cluster) in enumerate(zip(paths, clusters)):
                row = [p.name, int(cluster)]
                if native_scores is not None:
                    members = np.where(clusters == cluster)[0]
                    distinguishable = bool(np.min(native_scores[members]) < threshold)
                    row += [f"{native_scores[i]:.8f}", distinguishable]
                writer.writerow(row)

        if native_scores is None:
            distinguishable_clusters = ""
        else:
            distinguishable_clusters = sum(
                np.min(native_scores[clusters == c]) < threshold
                for c in set(clusters)
            )
        summary_rows.append([threshold, cluster_count, distinguishable_clusters])
        print(f"TM threshold {threshold:.3f}: {cluster_count} clusters", file=sys.stderr)

    with Path(f"{args.output_prefix}_summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tm_threshold", "n_clusters", "n_clusters_distinguishable_from_native"])
        writer.writerows(summary_rows)

    print(f"Wrote {args.output_prefix}_pairwise_tm.csv")
    if native_scores is not None:
        print(f"Wrote {args.output_prefix}_native_motif_tm.csv")
    print(f"Wrote {args.output_prefix}_summary.csv")


if __name__ == "__main__":
    main()
