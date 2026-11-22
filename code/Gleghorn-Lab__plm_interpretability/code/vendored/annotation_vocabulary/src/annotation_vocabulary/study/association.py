"""Full-population associations with nominal protein-based significance scores.

Dimensions: n proteins, f features in a block, t annotation terms, r residues,
k stored TopK slots. Homologous proteins are not independent observations.

Extraction arrays are read through the feature store (`open_extraction`); no `.npy` extraction
array is opened here.
"""

from __future__ import annotations

import hashlib
import json
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import scipy.sparse as sp

from pathlib import Path
from typing import Any
from scipy import stats

from ..feature_cache import POOLED_MAX, RESIDUE_TOPK, verify_recorded_store
from ..feature_views import open_extraction
from ..legacy_extraction_cache import verify_converted_manifest


def membership_matrix(token_lists: list[list[int]], n_terms: int) -> sp.csr_matrix:
    """Deduplicate tokens within each protein, retaining absent vocabulary columns."""
    indices: list[int] = []
    indptr = [0]
    for tokens in token_lists:
        unique = np.unique(np.asarray(tokens, dtype=np.int64))  # (terms_in_protein,)
        if np.any((unique < 0) | (unique >= n_terms)):
            raise ValueError("Annotation token outside the supplied vocabulary")
        indices.extend(unique.tolist())
        indptr.append(len(indices))
    return sp.csr_matrix(
        (np.ones(len(indices), dtype=np.float64), indices, indptr),
        shape=(len(token_lists), n_terms),
    )  # (n, t)


def rank_columns(scores: np.ndarray, device: str = "cpu") -> tuple[np.ndarray, np.ndarray]:
    """Return float64 midranks and exact float64 tie sums for each feature."""
    # scores: (n, f)
    if not np.isfinite(scores).all() or np.any(scores < 0):
        raise ValueError("SAE activations must be finite and nonnegative")
    if device == "cpu":
        ranks = stats.rankdata(scores, axis=0, method="average")  # (n, f)
        ties = np.empty(scores.shape[1], dtype=np.float64)  # (f,)
        for feature in range(scores.shape[1]):
            counts = np.unique(scores[:, feature], return_counts=True)[1].astype(np.float64)  # (groups,)
            ties[feature] = np.sum(counts**3 - counts)
        return ranks, ties  # (n, f), (f,)
    import torch

    tensor = torch.as_tensor(scores, device=device)  # (n, f)
    ranks = torch.empty(tensor.shape, dtype=torch.float64, device=device)  # (n, f)
    ties = torch.empty(tensor.shape[1], dtype=torch.float64, device=device)  # (f,)
    for feature in range(tensor.shape[1]):
        values, order = tensor[:, feature].sort()  # (n,), (n,)
        _, inverse, counts = torch.unique_consecutive(values, return_inverse=True, return_counts=True)
        counts = counts.to(torch.float64)  # (groups,)
        ends = counts.cumsum(0)  # (groups,)
        ranks[order, feature] = (ends - (counts - 1) / 2)[inverse]  # (n,)
        ties[feature] = (counts**3 - counts).sum()
    return ranks.cpu().numpy(), ties.cpu().numpy()  # (n, f), (f,)


def global_from_ranks(
    ranks: np.ndarray,
    ties: np.ndarray,
    active: np.ndarray,
    membership: sp.csr_matrix,
    min_support: int = 10,
    device: str = "cpu",
) -> dict[str, np.ndarray]:
    """Compute one-sided rank and exact activation-presence enrichment tests.

    Reuse ranks/ties under whole-annotation-row permutations. Positive activation
    means value > 0, not the existence of a stored TopK slot.
    """
    # ranks, active: (n, f); ties: (f,); membership: (n, t)
    n, n_features = ranks.shape
    if membership.shape[0] != n or active.shape != ranks.shape or n < 2:
        raise ValueError("Association inputs have incompatible dimensions or fewer than two proteins")
    n_positive = np.asarray(membership.sum(axis=0)).ravel()  # (t,)
    n_negative = n - n_positive  # (t,)
    valid = (n_positive >= min_support) & (n_negative >= min_support)  # (t,)
    if device == "cpu":
        rank_sum = np.asarray(membership.T @ ranks).T  # (f, t)
        cooccurrence = np.asarray(membership.T @ active.astype(np.float64)).T  # (f, t)
    else:
        import torch

        transposed = membership.T.tocsr()  # (t, n)
        matrix = torch.sparse_csr_tensor(
            transposed.indptr, transposed.indices, transposed.data,
            size=transposed.shape, dtype=torch.float64, device=device,
        )  # (t, n)
        rank_tensor = torch.as_tensor(ranks, dtype=torch.float64, device=device)  # (n, f)
        active_tensor = torch.as_tensor(active, dtype=torch.float64, device=device)  # (n, f)
        rank_sum = torch.sparse.mm(matrix, rank_tensor).T.cpu().numpy()  # (f, t)
        cooccurrence = torch.sparse.mm(matrix, active_tensor).T.cpu().numpy()  # (f, t)
    pair_count = n_positive * n_negative  # (t,)
    u_statistic = rank_sum - n_positive[None, :] * (n_positive[None, :] + 1) / 2  # (f, t)
    variance = pair_count[None, :] / 12 * ((n + 1) - ties[:, None] / (n * (n - 1)))  # (f, t)
    with np.errstate(invalid="ignore", divide="ignore"):
        auroc = u_statistic / pair_count[None, :]  # (f, t)
        z_score = (u_statistic - pair_count[None, :] / 2 - 0.5) / np.sqrt(variance)  # (f, t)
    rank_p = stats.norm.sf(z_score)  # (f, t)
    rank_p[variance <= 0] = 1  # (f, t)
    rank_p[:, ~valid] = np.nan  # (f, t)
    auroc[:, ~valid] = np.nan  # (f, t)
    n_active = active.sum(axis=0, dtype=np.int64)  # (f,)
    with np.errstate(invalid="ignore", divide="ignore"):
        annotation_prevalence_active = cooccurrence / n_active[:, None]  # (f, t)
        enrichment = annotation_prevalence_active / (n_positive[None, :] / n)  # (f, t)
    # Fisher's greater alternative equals the fixed-margin hypergeometric tail.
    presence_p = stats.hypergeom.sf(
        cooccurrence.astype(np.int64) - 1, n,
        n_positive[None, :].astype(np.int64), n_active[:, None],
    )  # (f, t)
    presence_p[:, ~valid] = np.nan  # (f, t)
    return {
        "auroc": auroc, "rank_p": rank_p, "presence_p": presence_p,
        "activation_enrichment": enrichment, "cooccurrence": cooccurrence.astype(np.int32),
        "n_positive": n_positive.astype(np.int32), "n_active": n_active,
        "annotation_prevalence_active": annotation_prevalence_active,
        "background_prevalence": n_positive / n,
    }  # dict of (f, t) and (t,) arrays


def global_statistics(
    scores: np.ndarray, membership: sp.csr_matrix, min_support: int = 10, device: str = "cpu"
) -> dict[str, np.ndarray]:
    """Rank each feature once and score all global-presence endpoints."""
    # scores: (n, f); membership: (n, t)
    ranks, ties = rank_columns(scores, device)  # (n, f), (f,)
    return global_from_ranks(ranks, ties, scores > 0, membership, min_support, device)  # dict of (f, t) and (t,) arrays


def merge_intervals(starts: list[int], ends: list[int], length: int) -> list[tuple[int, int]]:
    """Clip 1-based inclusive spans and return merged zero-based half-open spans."""
    if len(starts) != len(ends):
        raise ValueError("Local start and end arrays differ in length")
    spans: list[tuple[int, int]] = []
    for start, end in zip(starts, ends, strict=False):
        if int(start) < 1 or int(end) < int(start):
            raise ValueError("Invalid 1-based inclusive interval")
        left, right = int(start) - 1, min(int(end), length)
        if left < right:
            spans.append((left, right))
    merged: list[tuple[int, int]] = []
    for left, right in sorted(spans):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    return merged


def interval_feature_counts(positions: np.ndarray, features: np.ndarray, spans: list[tuple[int, int]], n_features: int) -> np.ndarray:
    """Count sorted active positions inside disjoint intervals without a full-track mask."""
    # positions,features: (active_residue_features,); return: (active_f,)
    boundaries = np.searchsorted(positions, np.asarray(spans, dtype=np.int64))  # (spans,2)
    windows = [features[start:end] for start, end in boundaries]  # each: (active_entries_in_span,)
    retained = windows[0] if len(windows) == 1 else np.concatenate(windows)  # (active_entries_in_union,)
    return np.bincount(retained, minlength=n_features)  # (active_f,)


def local_statistics(
    proteins: pd.DataFrame,
    residue_features: np.ndarray,
    residue_values: np.ndarray,
    offsets: np.ndarray,
    lengths: np.ndarray,
    feature_indices: np.ndarray,
    term_tokens: np.ndarray,
    min_support: int = 10,
    work_dir: Path | None = None,
    circular_shifts: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Accumulate paired occupancy contrasts in one pass over protein tracks.

    Informative proteins have annotated and unannotated observed positions. All
    such proteins contribute, including zero-activity proteins with contrast zero.
    The separate active-protein count gates selection. Memmaps bound resident
    allocation; no residue-by-term matrix is constructed.
    """
    # residue_features, residue_values: (r, k); offsets,lengths,shifts: (n,); circular_shifts: (n,)
    # feature_indices: (f,); term_tokens: (t,)
    if residue_features.shape != residue_values.shape:
        raise ValueError("Sparse feature/value shapes differ")
    if len(proteins) != len(offsets) or len(proteins) != len(lengths):
        raise ValueError("Protein tracks are not aligned")
    if circular_shifts is not None and len(circular_shifts) != len(proteins):
        raise ValueError("Circular shifts are not aligned")
    n_features, n_terms = len(feature_indices), len(term_tokens)
    feature_map = np.full(int(max(feature_indices, default=-1)) + 1, -1, dtype=np.int64)  # (codebook_prefix,)
    feature_map[feature_indices] = np.arange(n_features)  # (f,)
    term_map = {int(token): position for position, token in enumerate(term_tokens)}
    accumulators: dict[str, np.ndarray] = {}
    for name in ("sum_difference", "sum_squared_difference", "sum_inside", "sum_outside", "inside_hits", "outside_hits", "n_active"):
        shape = (n_features, n_terms)
        if work_dir is None:
            accumulators[name] = np.zeros(shape, dtype=np.float64, order="F")  # (f, t)
        else:
            work_dir.mkdir(parents=True, exist_ok=True)
            accumulators[name] = np.lib.format.open_memmap(work_dir / f"{name}.npy", mode="w+", dtype=np.float64, shape=shape, fortran_order=True)  # (f, t)
    n_informative = np.zeros(n_terms, dtype=np.int64)  # (t,)
    inside_exposure = np.zeros(n_terms, dtype=np.int64)  # (t,)
    outside_exposure = np.zeros(n_terms, dtype=np.int64)  # (t,)
    for row, protein in enumerate(proteins.itertuples(index=False)):
        length, offset = int(lengths[row]), int(offsets[row])
        ids = np.asarray(residue_features[offset:offset + length])  # (l, k)
        values = np.asarray(residue_values[offset:offset + length])  # (l, k)
        if len(ids) != length or not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("Invalid sparse residue activation track")
        if circular_shifts is not None:
            ids = np.roll(ids, int(circular_shifts[row]), axis=0)  # (l, k)
            values = np.roll(values, int(circular_shifts[row]), axis=0)  # (l, k)
        selected = (values > 0) & (ids < len(feature_map))  # (l, k)
        positions, slots = np.nonzero(selected)  # (positive_slots,), (positive_slots,)
        features = feature_map[ids[positions, slots]]  # (positive_slots,)
        keep = features >= 0  # (positive_slots,)
        positions, features = positions[keep], features[keep]  # (selected_slots,), (selected_slots,)
        # Deduplicate malformed/repeated slots as occupancy is binary per residue.
        keys = np.unique(positions.astype(np.int64) * n_features + features)  # (active_residue_features,)
        positions, features = keys // n_features, keys % n_features  # (active_residue_features,), twice
        total = np.bincount(features, minlength=n_features)  # (f,)
        active_features = np.flatnonzero(total)  # (active_f,)
        compact_map = np.empty(n_features, dtype=np.int64)  # (f,), only active entries are read
        compact_map[active_features] = np.arange(len(active_features))  # (active_f,)
        compact_features = compact_map[features]  # (active_residue_features,)
        active_totals = total[active_features]  # (active_f,)
        grouped: dict[int, tuple[list[int], list[int]]] = {}
        tokens, starts, ends = protein.local_term_ids, protein.local_starts, protein.local_ends
        if len(tokens) != len(starts) or len(tokens) != len(ends):
            raise ValueError("Local annotation coordinate arrays differ in length")
        for token, start, end in zip(tokens, starts, ends, strict=False):
            if int(token) in term_map:
                left, right = grouped.setdefault(int(token), ([], []))
                left.append(int(start))
                right.append(int(end))
        for token, (starts, ends) in grouped.items():
            spans = merge_intervals(starts, ends, length)
            inside_length = sum(end - start for start, end in spans)
            outside_length = length - inside_length
            if inside_length == 0 or outside_length == 0:
                continue
            term = term_map[token]
            n_informative[term] += 1
            inside_exposure[term] += inside_length
            outside_exposure[term] += outside_length
            if len(active_features) == 0:
                continue
            # np.unique on residue*feature keys above already sorts positions,
            # including after circular shifts; no extra per-term sort is needed.
            inside = interval_feature_counts(positions, compact_features, spans, len(active_features))  # (active_f,)
            outside = active_totals - inside  # (active_f,)
            inside_fraction = inside / inside_length  # (active_f,)
            outside_fraction = outside / outside_length  # (active_f,)
            difference = inside_fraction - outside_fraction  # (active_f,)
            for name, increment in (
                ("sum_difference", difference), ("sum_squared_difference", difference**2),
                ("sum_inside", inside_fraction), ("sum_outside", outside_fraction),
                ("inside_hits", inside), ("outside_hits", outside),
                ("n_active", np.ones(len(active_features))),
            ):
                accumulators[name][active_features, term] += increment  # (active_f,)
    accumulators.update(n_informative=n_informative, inside_exposure=inside_exposure, outside_exposure=outside_exposure)
    if work_dir is not None:
        for name, values in accumulators.items():
            if isinstance(values, np.memmap):
                values.flush()
            else:
                np.save(Path(work_dir) / f"{name}.npy", values, allow_pickle=False)
    return accumulators  # dict of (f, t) and (t,) arrays


def local_metrics(accumulators: dict[str, np.ndarray], min_support: int = 10) -> dict[str, np.ndarray]:
    """Convert protein-unit sums into one-sided paired-t and effect estimates."""
    # matrix accumulators: (f,t); n_informative/exposures: (t,)
    counts = accumulators["n_informative"][None, :]  # (1, t)
    total = accumulators["sum_difference"]  # (f, t)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = total / counts  # (f, t)
        variance = np.maximum(0, (accumulators["sum_squared_difference"] - total**2 / counts) / (counts - 1))  # (f, t)
        standard_error = np.sqrt(variance / counts)  # (f, t)
        t_score = mean / standard_error  # (f, t)
        p_value = stats.t.sf(t_score, counts - 1)  # (f, t)
        enrichment = accumulators["sum_inside"] / accumulators["sum_outside"]  # (f, t)
        pooled_enrichment = (accumulators["inside_hits"] / accumulators["inside_exposure"][None, :]) / (accumulators["outside_hits"] / accumulators["outside_exposure"][None, :])  # (f, t)
    p_value[(standard_error == 0) & (mean == 0)] = 1  # (f, t)
    p_value[:, accumulators["n_informative"] < max(2, min_support)] = np.nan  # (f, t)
    return {
        "local_p": p_value, "mean_difference": mean, "standard_error": standard_error,
        "local_enrichment": enrichment, "pooled_residue_enrichment": pooled_enrichment,
        "n_informative": accumulators["n_informative"], "n_active": accumulators["n_active"],
        "inside_hits": accumulators["inside_hits"], "outside_hits": accumulators["outside_hits"],
    }  # dict of (f, t) and (t,) arrays


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Exact nominal BH, excluding structurally untestable NaN entries."""
    # p_values: (*s,) any shape; the return has the same shape
    flattened = np.asarray(p_values, dtype=np.float64).ravel()  # (pairs,)
    finite = np.flatnonzero(np.isfinite(flattened))  # (tested,)
    order = finite[np.argsort(flattened[finite], kind="stable")]  # (tested,)
    adjusted = np.full(flattened.shape, np.nan)  # (pairs,)
    if len(order):
        values = flattened[order] * len(order) / np.arange(1, len(order) + 1)  # (tested,)
        adjusted[order] = np.minimum(1, np.minimum.accumulate(values[::-1])[::-1])  # (tested,)
    return adjusted.reshape(p_values.shape)  # (*s,) same shape as p_values


class RoundedBH:
    """Bounded-memory BH on p-values rounded upward to a fixed log grid.

    Adjusted values are conservative relative to exact BH on unrounded values.
    Raw p-values are retained separately. Bin zero represents exact numerical zero.
    """

    def __init__(self, bins: int = 300_000):
        self.edges = np.concatenate(([0.0], np.logspace(-300, 0, bins + 1)))  # (bins+2,)
        self.counts = np.zeros(len(self.edges), dtype=np.int64)  # (bins+2,)
        self.adjusted: np.ndarray | None = None

    def add(self, values: np.ndarray) -> None:
        # values: (*s,) any shape
        finite = values[np.isfinite(values)]  # (tested,)
        if np.any((finite < 0) | (finite > 1)):
            raise ValueError("p-values must lie in [0, 1]")
        indices = np.searchsorted(self.edges, finite, side="left")  # (tested,)
        self.counts += np.bincount(indices, minlength=len(self.edges))  # (bins+2,)

    def finalize(self) -> None:
        cumulative = np.cumsum(self.counts)  # (bins+2,)
        values = np.full(len(self.edges), np.inf)  # (bins+2,)
        present = self.counts > 0  # (bins+2,)
        values[present] = self.edges[present] * cumulative[-1] / cumulative[present]  # (present_bins,)
        self.adjusted = np.minimum(1, np.minimum.accumulate(values[::-1])[::-1])  # (bins+2,)

    def transform(self, values: np.ndarray) -> np.ndarray:
        # values: (*s,) any shape
        if self.adjusted is None:
            raise ValueError("Finalize the correction before transforming p-values")
        result = np.full(values.shape, np.nan)  # same shape as values
        finite = np.isfinite(values)  # same shape as values
        indices = np.searchsorted(self.edges, values[finite], side="left")  # (tested,)
        result[finite] = self.adjusted[indices]  # (tested,)
        return result  # (*s,)

    def threshold(self, alpha: float) -> float | None:
        if self.adjusted is None:
            raise ValueError("Finalize the correction first")
        accepted = self.edges[self.adjusted <= alpha]  # (accepted_bins,)
        return float(accepted[-1]) if len(accepted) else None


def select_global(metrics: dict[str, np.ndarray], rank_q: np.ndarray, presence_q: np.ndarray, *, alpha: float = 0.01, auroc: float = 0.60, enrichment: float = 2.0, min_support: int = 10, min_active_proteins: int | None = None) -> np.ndarray:
    # metrics, rank_q, presence_q: (f, t)
    rank_pass = (rank_q <= alpha) & (metrics["auroc"] >= auroc)  # (f, t)
    presence_pass = (presence_q <= alpha) & (metrics["activation_enrichment"] >= enrichment)  # (f, t)
    active_support = min_support if min_active_proteins is None else min_active_proteins
    return (rank_pass | presence_pass) & (metrics["cooccurrence"] >= active_support)  # (f, t)


def select_local(metrics: dict[str, np.ndarray], local_q: np.ndarray, *, alpha: float = 0.01, enrichment: float = 2.0, min_support: int = 10, min_active_proteins: int | None = None) -> np.ndarray:
    # metrics, local_q: (f, t); n_informative: (t,)
    active_support = min_support if min_active_proteins is None else min_active_proteins
    return ((local_q <= alpha) & (metrics["local_enrichment"] >= enrichment)
            & (metrics["mean_difference"] > 0) & (metrics["n_active"] >= active_support)
            & (metrics["n_informative"][None, :] >= min_support))  # (f, t)


def resolution_coverage(coverage: pd.DataFrame, assigned: pd.DataFrame) -> dict[str, Any]:
    """Add overlapping local-resolution flags, separate from original/derived status."""
    required = {"is_local", "source_database", "is_derived"}
    groups = ("coarse_parent", "finer_local_concept")
    suffixes = ("assigned", "protein_presence_assigned", "residue_localization_assigned")
    if not required.issubset(assigned):
        for group in groups:
            for suffix in suffixes:
                coverage[f"{group}_{suffix}"] = pd.Series(pd.NA, index=coverage.index, dtype="boolean")
        return {"status": "unavailable", "missing_term_columns": sorted(required - set(assigned))}
    local = assigned["is_local"].fillna(False).astype(bool)
    coarse = local & assigned["source_database"].eq("UniProtKB-FT") & ~assigned["is_derived"].fillna(False).astype(bool)
    for group, mask in (("coarse_parent", coarse), ("finer_local_concept", local & ~coarse)):
        selected = assigned.loc[mask]
        coverage[f"{group}_assigned"] = coverage["feature_id"].isin(selected["feature_id"])
        for scope, endpoint in (("global", "protein_presence"), ("local", "residue_localization")):
            coverage[f"{group}_{endpoint}_assigned"] = coverage["feature_id"].isin(selected.loc[selected["scope"] == scope, "feature_id"])
    return {"status": "computed",
            "coarse_parent": "Local, original UniProtKB-FT term: is_local and source_database=UniProtKB-FT and not is_derived",
            "finer_local_concept": "Any other local term, including original InterPro terms and derived local concepts",
            "counting": "Any qualifying protein-presence or residue-localization assignment; endpoint-specific flags also provided; groups overlap at feature level; global vocabulary terms belong to neither local-resolution group"}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_listed_files(directory: Path, inventory: dict[str, Any], names: list[str]) -> None:
    for name in names:
        expected = inventory[name]
        path = (directory / name).resolve()
        if path.parent != directory:
            raise ValueError("Extraction manifest contains a nonlocal array path")
        if not path.is_file() or path.stat().st_size != expected["size"] or _hash_file(path) != expected["sha256"]:
            raise ValueError(f"Extraction checksum or size mismatch: {name}")


def verify_extraction(directory: str | Path, include_local: bool = True) -> dict[str, Any]:
    """Verify completed extraction bytes before computing or replaying statistics.

    An extraction written by `study.extract` records a `feature_store` block beside the checksummed
    index: the sequence sidecar and the SHA-256 of every stored file of each feature. All of it is
    re-verified here, along with the row and residue counts the index promises. An extraction
    converted from the retired `.npy` layout keeps its old manifest; `verify_converted_manifest`
    accepts each array entry when the store's conversion origin records that exact digest and size,
    so the receipt still binds the bytes the stored numbers were decoded from.
    """
    directory = Path(directory).resolve()
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("completed") is not True:
        raise ValueError("Extraction manifest does not record a completed run")
    inventory = manifest.get("files", {})
    if "protein_index.parquet" not in inventory:
        raise ValueError("Extraction manifest lacks required array checksums")
    block = manifest.get("feature_store")
    if block is None:
        _verify_listed_files(directory, inventory, ["protein_index.parquet"])
        index = pd.read_parquet(directory / "protein_index.parquet")
        verify_converted_manifest(directory, manifest, index, include_local=include_local)
        return manifest
    _verify_listed_files(directory, inventory, list(inventory))
    index = pd.read_parquet(directory / "protein_index.parquet")
    verify_recorded_store(directory, block, index, include_local=include_local)
    return manifest


def run_association(protein_path: str | Path, term_path: str | Path, extraction_dir: str | Path, output_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    """Write complete metric shards, joint nominal correction, and multi-label assignments.

    ``row_subset`` indexes the prepared protein table before filtering. ``split``
    and ``exclude_truncated`` intersect this subset. Extraction rows join by
    accession and never by assumed row order. Existing output directories must be
    empty, preventing accidental replacement of a completed experiment.
    """
    protein_path, term_path = Path(protein_path), Path(term_path)
    extraction_dir, output_dir = Path(extraction_dir), Path(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Association output is not empty: {output_dir}")
    extraction_manifest = verify_extraction(extraction_dir, bool(config.get("include_local", True)))
    output_dir.mkdir(parents=True, exist_ok=True)
    metric_dir = output_dir / "metrics"
    metric_dir.mkdir()
    columns = ["accession", "processed_length", "annotations", "original_sequence_sha256", "processed_sequence_sha256"]
    if config.get("include_local", True):
        columns.extend(("local_term_ids", "local_starts", "local_ends"))
    if config.get("split"):
        columns.append("split")
    if config.get("exclude_truncated", False):
        columns.append("truncated")
    available = set(pq.read_schema(protein_path).names)
    proteins = pd.read_parquet(protein_path, columns=[name for name in columns if name in available])
    terms = pd.read_parquet(term_path).sort_values("token").reset_index(drop=True)
    tokens = terms["token"].to_numpy(dtype=np.int64)  # (t,)
    if not np.array_equal(tokens, np.arange(len(terms))):
        raise ValueError("Vocabulary tokens must be unique and contiguous from zero")
    index = pd.read_parquet(extraction_dir / "protein_index.parquet")
    if proteins["accession"].duplicated().any() or index["accession"].duplicated().any():
        raise ValueError("Duplicate accessions prevent unique extraction alignment")
    if "row_subset" in config:
        rows = np.asarray(config["row_subset"], dtype=np.int64)  # (selected_n,)
        if len(np.unique(rows)) != len(rows) or np.any((rows < 0) | (rows >= len(proteins))):
            raise ValueError("row_subset must contain unique valid protein row indices")
        proteins = proteins.iloc[rows]
    if config.get("split"):
        proteins = proteins[proteins["split"] == config["split"]]
    if config.get("exclude_truncated", False):
        proteins = proteins[~proteins["truncated"]]
    proteins = proteins.reset_index(drop=True)
    aligned = index.set_index("accession").reindex(proteins["accession"])
    if aligned["residue_offset"].isna().any():
        raise ValueError("Selected proteins are absent from the extraction")
    if not np.array_equal(aligned["n_residues"], proteins["processed_length"]):
        raise ValueError("Prepared and extracted residue lengths disagree")
    if len(proteins) < 2:
        raise ValueError("At least two selected proteins are required")
    for name in ("original_sequence_sha256", "processed_sequence_sha256"):
        if name not in aligned or name not in proteins:
            raise ValueError(f"Missing mandatory sequence alignment field: {name}")
        if not np.array_equal(aligned[name], proteins[name]):
            raise ValueError(f"Prepared and extracted {name} values disagree")
    extraction_rows = pd.Index(index["accession"]).get_indexer(proteins["accession"])  # (n,)
    include_local = bool(config.get("include_local", True))
    local_tokens = terms.loc[terms["is_local"].astype(bool), "token"].to_numpy(dtype=np.int64)  # (local_t,)
    with open_extraction(extraction_dir, roles=(POOLED_MAX, RESIDUE_TOPK) if include_local else (POOLED_MAX,)) as arrays:
        pooled = arrays.pooled_max  # (extracted_n, c)
        if pooled.shape[0] != len(index):
            raise ValueError("Pooled matrix and extraction index differ in length")
        codebook_features = pooled.shape[1]
        feature_indices = np.asarray(config.get("feature_indices", list(range(codebook_features))), dtype=np.int64)  # (selected_f,)
        if len(np.unique(feature_indices)) != len(feature_indices) or np.any((feature_indices < 0) | (feature_indices >= codebook_features)):
            raise ValueError("feature_indices must be unique valid codebook indices")
        if len(feature_indices) == 0:
            raise ValueError("At least one feature must be selected")
        pooled.hint_columns(feature_indices)
        membership = membership_matrix(proteins["annotations"].tolist(), len(terms))  # (n, t)
        min_support = int(config.get("min_support", 10))
        feature_chunk = int(config.get("feature_chunk", 32))
        if feature_chunk < 1 or min_support < 2:
            raise ValueError("feature_chunk must be positive and min_support at least two")
        alpha = float(config.get("alpha", 0.01))
        min_auroc = float(config.get("min_auroc", 0.60))
        min_enrichment = float(config.get("min_enrichment", 2.0))
        min_active = int(config.get("min_active_proteins", min_support))
        auc_grid = sorted(set(map(float, config.get("auroc_sensitivity", [0.55, 0.60, 0.65]))) | {min_auroc})
        enrichment_grid = sorted(set(map(float, config.get("enrichment_sensitivity", [1.5, 2.0, 3.0]))) | {min_enrichment})
        if not 0 < alpha < 1 or min_active < 2 or any(not 0.5 <= value <= 1 for value in auc_grid) or any(not np.isfinite(value) or value < 1 for value in enrichment_grid):
            raise ValueError("Invalid nominal alpha, minimum active support, or positive-association effect thresholds")
        correction = RoundedBH(int(config.get("bh_bins", 300_000)))
        metric_files: list[Path] = []
        active_features: set[int] = set()
        global_evaluable: set[int] = set()
        local_evaluable: set[int] = set()
        for start in range(0, len(feature_indices), feature_chunk):
            features = feature_indices[start:start + feature_chunk]  # (f,)
            scores = np.asarray(pooled[np.ix_(extraction_rows, features)], dtype=np.float64)  # (n, f)
            metrics = global_statistics(scores, membership, min_support, str(config.get("device", "cpu")))
            active_features.update(features[metrics["n_active"] > 0].tolist())
            if np.isfinite(metrics["rank_p"]).any():
                global_evaluable.update(features[np.ptp(scores, axis=0) > 0].tolist())
            correction.add(metrics["rank_p"])
            correction.add(metrics["presence_p"])
            path = metric_dir / f"global_{start:06d}.npz"
            np.savez_compressed(path, feature_indices=features, term_tokens=tokens, **metrics)
            metric_files.append(path)
        if include_local and len(local_tokens):
            accumulators = local_statistics(
                proteins, arrays.residue_features, arrays.residue_values,
                aligned["residue_offset"].to_numpy(dtype=np.int64),
                aligned["n_residues"].to_numpy(dtype=np.int64), feature_indices, local_tokens,
                min_support, output_dir / "local_accumulators",
            )
            for start in range(0, len(feature_indices), feature_chunk):
                block = {name: value[start:start + feature_chunk] if value.ndim == 2 else value for name, value in accumulators.items()}
                metrics = local_metrics(block, min_support)
                local_evaluable.update(feature_indices[start:start + feature_chunk][np.any(np.isfinite(metrics["local_p"]) & (metrics["n_active"] >= min_support), axis=1)].tolist())
                correction.add(metrics["local_p"])
                path = metric_dir / f"local_{start:06d}.npz"
                np.savez_compressed(path, feature_indices=feature_indices[start:start + feature_chunk], term_tokens=local_tokens, **metrics)
                metric_files.append(path)
    correction.finalize()
    np.savez_compressed(output_dir / "nominal_bh.npz", edges=correction.edges, counts=correction.counts, adjusted=correction.adjusted)
    from .assignment_finalize import finalize_assignments

    finalized = finalize_assignments(
        metric_files, terms, correction, feature_indices, active_features,
        global_evaluable, local_evaluable, codebook_features, output_dir, config,
    )
    manifest = {
        "n_proteins": len(proteins), "n_terms": len(terms), "codebook_features": codebook_features,
        "evaluated_features": len(feature_indices), "active_features": len(active_features),
        "assigned_features": finalized["assigned_features"], "assignment_pairs": finalized["assignment_pairs"],
        "nominal_test_count": int(correction.counts.sum()), "alpha": alpha,
        "raw_p_rejection_threshold": correction.threshold(alpha),
        "nominal_p_cutoff": correction.threshold(alpha), "total_hypotheses": int(correction.counts.sum()),
        "correction": "BH on upward-rounded p-values; nominal protein independence; raw p-values retained",
        "global_auroc_threshold": min_auroc, "enrichment_threshold": min_enrichment, "min_support": min_support,
        "min_active_proteins": min_active,
        "local_resolution_coverage": finalized["local_resolution_coverage"],
        "representative_rule": "Within each feature and scope: smallest qualifying endpoint nominal q, descending AUROC or mean local contrast, ascending token; independent of semantic similarity",
        "config": config, "protein_table_sha256": _hash_file(protein_path),
        "term_table_sha256": _hash_file(term_path), "source_sha256": _hash_file(Path(__file__)),
        "finalization_source_sha256": _hash_file(Path(__file__).with_name("assignment_finalize.py")),
        "extraction_index_sha256": _hash_file(extraction_dir / "protein_index.parquet"),
        "selected_accessions_sha256": hashlib.sha256("\n".join(proteins["accession"]).encode("utf-8")).hexdigest(),
        "extraction_directory": str(extraction_dir.resolve()),
    }
    settings = extraction_manifest.get("settings", {})
    manifest["sae_identity"] = extraction_manifest.get("sae_identity") or {
        "base_repo": settings.get("original_base_repo", settings.get("base_repo")), "base_revision": settings.get("original_base_revision", settings.get("base_revision")),
        "sae_repo": settings.get("sae_repo"), "sae_revision": settings.get("sae_revision"),
        "sae_layer": settings.get("sae_layer"), "codebook_size": settings.get("feature_dim"),
        "k": settings.get("k"),
    }
    for name in ("extraction_manifest.json", "manifest.json"):
        if (extraction_dir / name).exists():
            manifest["extraction_manifest_sha256"] = _hash_file(extraction_dir / name)
            break
    manifest["outputs"] = {
        path.relative_to(output_dir).as_posix(): {"sha256": _hash_file(path), "size": path.stat().st_size}
        for path in sorted(output_dir.rglob("*")) if path.is_file()
    }
    (output_dir / "association_manifest.json").write_text(json.dumps(manifest, indent=2, default=lambda value: value.tolist() if isinstance(value, np.ndarray) else str(value)), encoding="utf-8")
    return manifest


def quantile_groups(values: np.ndarray, n_groups: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep tied covariate values together, allowing fewer than n_groups bins."""
    # values: (n,); groups: (n,); internal edges: (at_most_n_groups-1,)
    values = np.asarray(values, dtype=np.float64)  # (n,)
    if len(values) == 0 or not np.isfinite(values).all() or n_groups < 1:
        raise ValueError("Quantile grouping needs finite observations and a positive bin count")
    edges = np.unique(np.quantile(values, np.arange(1, n_groups) / n_groups))  # (internal_edges,)
    edges = edges[(edges > values.min()) & (edges < values.max())]  # (distinct_internal_edges,)
    return np.searchsorted(edges, values, side="right"), edges  # (n,), (internal_edges,)


def stratified_pair_statistics(scores: np.ndarray, labels: np.ndarray, strata: np.ndarray, min_support: int = 10, device: str = "cpu") -> dict[str, np.ndarray]:
    """Score one frozen annotation per feature using summed within-stratum U.

    AUROC is weighted by the number of positive-negative pairs in each stratum.
    Strata with no carriers or no noncarriers contribute no comparisons. This is
    a descriptive sensitivity of selected pairs, not a new feature assignment.
    """
    # scores, labels: (n,f); strata: (n,)
    if scores.shape != labels.shape or len(strata) != len(scores):
        raise ValueError("Scores, per-feature labels, and strata must align")
    n, n_features = scores.shape
    sums = {name: np.zeros(n_features, dtype=np.float64) for name in ("u", "variance", "pairs", "informative_proteins", "informative_positive", "informative_strata")}  # each (f,)
    n_positive = labels.sum(axis=0, dtype=np.int64)  # (f,)
    _, groups = np.unique(strata.astype(str), return_inverse=True)  # (groups,), (n,)
    order = np.argsort(groups, kind="stable")  # (n,)
    boundaries = np.r_[0, np.flatnonzero(np.diff(groups[order])) + 1, n]  # (groups+1,)
    for start, end in zip(boundaries[:-1], boundaries[1:], strict=False):
        rows = order[start:end]  # (n_s,)
        n_stratum = len(rows)
        if n_stratum < 2:
            continue
        local_labels = labels[rows]  # (n_s,f)
        positives = local_labels.sum(axis=0, dtype=np.int64)  # (f,)
        negatives = n_stratum - positives  # (f,)
        valid = (positives > 0) & (negatives > 0)  # (f,)
        if not valid.any():
            continue
        feature_rows = np.flatnonzero(valid)  # (informative_f,)
        ranks, ties = rank_columns(scores[np.ix_(rows, feature_rows)], device)  # (n_s,informative_f), (informative_f,)
        rank_sums = np.sum(ranks * local_labels[:, valid], axis=0, dtype=np.float64)  # (informative_f,)
        pair_counts = positives[valid].astype(np.float64) * negatives[valid]  # (informative_f,)
        sums["u"][valid] += rank_sums - positives[valid].astype(np.float64) * (positives[valid] + 1) / 2  # (informative_f,)
        sums["variance"][valid] += pair_counts / 12 * ((n_stratum + 1) - ties / (n_stratum * (n_stratum - 1)))  # (informative_f,)
        sums["pairs"][valid] += pair_counts  # (informative_f,)
        sums["informative_proteins"][valid] += n_stratum  # (informative_f,)
        sums["informative_positive"][valid] += positives[valid]  # (informative_f,)
        sums["informative_strata"][valid] += 1  # (informative_f,)
    with np.errstate(invalid="ignore", divide="ignore"):
        auroc = sums["u"] / sums["pairs"]  # (f,)
        z_score = (sums["u"] - sums["pairs"] / 2 - 0.5) / np.sqrt(np.maximum(0, sums["variance"]))  # (f,)
        p_value = stats.norm.sf(z_score)  # (f,)
    p_value[sums["variance"] <= 0] = 1  # (f,)
    untestable = (n_positive < min_support) | ((n - n_positive) < min_support) | (sums["pairs"] == 0)  # (f,)
    p_value[untestable] = np.nan  # (f,)
    auroc[untestable] = np.nan  # (f,)
    return {"auroc": auroc, "nominal_p": p_value, "n_positive": n_positive,
            "n_negative": n - n_positive, "comparison_pairs": sums["pairs"],
            "informative_strata": sums["informative_strata"].astype(np.int64),
            "informative_proteins": sums["informative_proteins"].astype(np.int64),
            "informative_positive": sums["informative_positive"].astype(np.int64)}  # dict of (f,) arrays


def _global_representative_assignments(path: Path, batch_size: int = 65_536) -> pd.DataFrame:
    """Read only global representatives from bounded assignment batches."""
    columns = ["scope", "representative", "feature_id", "token", "term_id"]
    parquet = pq.ParquetFile(path)
    selected: list[pd.DataFrame] = []
    for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
        frame = batch.to_pandas()
        retained = frame[(frame["scope"] == "global") & frame["representative"]]
        # Empty selections preserve nullable dtypes seen in other source rows.
        selected.append(retained.copy(deep=True))
    representatives = pd.concat(selected, ignore_index=True) if selected else parquet.schema_arrow.empty_table().select(columns).to_pandas()
    return representatives.sort_values("feature_id").reset_index(drop=True)


def run_sensitivities(protein_path: str | Path, term_path: str | Path, extraction_dir: str | Path, output_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    """Evaluate frozen global representatives under population-level adjustments."""
    from ..analysis.pipeline import resolve_domain_metadata, summarize_domain_mapping

    protein_path, term_path = Path(protein_path), Path(term_path)
    extraction_dir, output_dir = Path(extraction_dir), Path(output_dir)
    association_dir = Path(config["association_dir"])
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Sensitivity output is not empty: {output_dir}")
    verify_extraction(extraction_dir, include_local=False)
    primary = json.loads((association_dir / "association_manifest.json").read_text(encoding="utf-8"))
    if primary.get("outputs", {}).get("assignments.parquet", {}).get("sha256") != _hash_file(association_dir / "assignments.parquet"):
        raise ValueError("Primary assignment checksum differs from its frozen manifest")
    for path, key in ((protein_path, "protein_table_sha256"), (term_path, "term_table_sha256"), (extraction_dir / "protein_index.parquet", "extraction_index_sha256"), (extraction_dir / "manifest.json", "extraction_manifest_sha256")):
        if primary.get(key) != _hash_file(path):
            raise ValueError(f"Sensitivity inputs differ from the frozen association input: {key}")
    columns = ["accession", "annotations", "processed_length", "truncated", "original_sequence_sha256",
               "processed_sequence_sha256", "lineage_names", "lineage_taxon_ids", "coarse_lineage", "lineage"]
    available = set(pq.read_schema(protein_path).names)
    proteins = pd.read_parquet(protein_path, columns=[name for name in columns if name in available])
    if len(proteins) != primary["n_proteins"]:
        raise ValueError("Sensitivity source must be the full-population association")
    index = pd.read_parquet(extraction_dir / "protein_index.parquet")
    rows = pd.Index(index["accession"]).get_indexer(proteins["accession"])  # (n,)
    if np.any(rows < 0) or proteins["accession"].duplicated().any() or index["accession"].duplicated().any():
        raise ValueError("Sensitivity accessions cannot be uniquely aligned")
    for name in ("original_sequence_sha256", "processed_sequence_sha256"):
        if not np.array_equal(proteins[name], index.iloc[rows][name]):
            raise ValueError(f"Sensitivity sequence alignment mismatch: {name}")
    representatives = _global_representative_assignments(association_dir / "assignments.parquet")
    if representatives["feature_id"].duplicated().any():
        raise ValueError("Multiple primary global representatives for one feature")
    terms = pd.read_parquet(term_path)
    membership = membership_matrix(proteins["annotations"].tolist(), len(terms))  # (n,t)
    lengths = proteins["processed_length"].to_numpy(dtype=np.int64)  # (n,)
    annotation_counts = np.diff(membership.indptr)  # (n,)
    length_bin, length_edges = quantile_groups(lengths, 10)  # (n,), (length_edges,)
    density_bin, density_edges = quantile_groups(annotation_counts, 4)  # (n,), (density_edges,)
    mapping = resolve_domain_metadata(proteins)
    length_density = np.array([f"{length}:{density}" for length, density in zip(length_bin, density_bin, strict=False)])  # (n,)
    with_taxonomy = np.array([f"{group}:{domain}" for group, domain in zip(length_density, mapping.domains, strict=False)])  # (n,)
    all_rows = np.arange(len(proteins))  # (n,)
    full_sequences = np.flatnonzero(~proteins["truncated"].to_numpy(dtype=bool))  # (untruncated_n,)
    arms = {"unadjusted": (all_rows, np.zeros(len(proteins), dtype=np.int64)),
            "length_annotation_count": (all_rows, length_density),
            "length_annotation_count_domain": (all_rows, with_taxonomy),
            "exclude_truncated": (full_sequences, np.zeros(len(full_sequences), dtype=np.int64))}
    blocks: list[pd.DataFrame] = []
    feature_chunk = int(config.get("feature_chunk", 32))
    if feature_chunk < 1:
        raise ValueError("feature_chunk must be positive")
    with open_extraction(extraction_dir, roles=(POOLED_MAX,)) as arrays:
        pooled = arrays.pooled_max  # (extracted_n,c)
        pooled.hint_columns(representatives["feature_id"].to_numpy(dtype=np.int64))
        for start in range(0, len(representatives), feature_chunk):
            block = representatives.iloc[start:start + feature_chunk]
            features = block["feature_id"].to_numpy(dtype=np.int64)  # (f,)
            tokens = block["token"].to_numpy(dtype=np.int64)  # (f,)
            scores = np.asarray(pooled[np.ix_(rows, features)], dtype=np.float64)  # (n,f)
            labels = membership[:, tokens].toarray().astype(bool)  # (n,f)
            for name, (selected_rows, strata) in arms.items():
                metrics = stratified_pair_statistics(scores[selected_rows], labels[selected_rows], strata, int(config.get("min_support", 10)), str(config.get("device", "cpu")))
                result = pd.DataFrame(metrics)
                result["feature_id"], result["token"] = features, tokens
                result["term_id"] = block["term_id"].to_numpy()
                result["arm"], result["n_proteins"] = name, len(selected_rows)
                blocks.append(result)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = pd.concat(blocks, ignore_index=True) if blocks else pd.DataFrame(columns=["feature_id", "token", "term_id", "arm", "auroc", "nominal_p", "n_proteins"])
    results.to_parquet(output_dir / "representative_sensitivities.parquet", index=False)
    manifest = {"n_proteins": len(proteins), "representative_pairs": len(representatives),
                "arms": {name: len(selected) for name, (selected, _) in arms.items()},
                "length_edges": length_edges.tolist(), "annotation_count_edges": density_edges.tolist(),
                "annotation_density_definition": "Number of distinct full-protein annotation terms; tied counts stay together",
                "taxonomy": summarize_domain_mapping(mapping),
                "scope": "Frozen global protein-presence representatives; local occupancy is already paired within proteins and is not replaced by pooled prediction",
                "qualification": "Same-data descriptive sensitivities, no pair reselection; stratification can condition on true biological differences as well as confounding",
                "primary_manifest_sha256": _hash_file(association_dir / "association_manifest.json"),
                "primary_assignments_sha256": _hash_file(association_dir / "assignments.parquet"),
                "output_sha256": _hash_file(output_dir / "representative_sensitivities.parquet"),
                "source_sha256": _hash_file(Path(__file__))}
    (output_dir / "sensitivity_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
