"""Rank-based association between SAE features and annotation vocabulary terms.

The question for a global term is "does feature `f` separate the proteins that carry term `j`
from the proteins that do not". That is exactly the Mann-Whitney U statistic, whose normalized
form is the AUROC. Ranking each feature column once and multiplying the midrank matrix by the
sparse binary term-membership matrix yields every rank sum at once, so all `c * t` tests reduce
to one matrix product plus closed-form arithmetic. This is preferable to a Spearman correlation
on raw activations because it is invariant to the pooling transform and comparable across
features whose activation scales differ by orders of magnitude.

The question for a local term is "does feature `f` fire inside annotated spans of type `j` more
than elsewhere in the same protein". Conditioning on the protein is essential: without it a
feature that fires across a whole protein family scores highly on every span type that family
happens to contain. The stratified form is the Cochran-Mantel-Haenszel test, with one 2x2 table
per protein and an exact hypergeometric null within each stratum.

Symbols: `n` proteins, `c` codebook features, `t` vocabulary terms, `k` active features per
residue, `r` residues.
"""

import numpy as np
import torch

from dataclasses import dataclass
from scipy import stats
from torch import Tensor


DEFAULT_FEATURE_CHUNK = 256
Z_HISTOGRAM_MAX = 60.0
Z_HISTOGRAM_BINS = 240_000


@dataclass(frozen=True, slots=True)
class GlobalAssociation:
    """Per-(feature, term) global association results."""

    auroc: np.ndarray
    z_score: np.ndarray
    n_positive: np.ndarray
    n_proteins: int

    def top_terms(self, n_top: int) -> tuple[np.ndarray, np.ndarray]:
        """Return `(term_index, z_score)` for the strongest positive terms of each feature."""
        # self.z_score: (c, t)
        order = np.argsort(-self.z_score, axis=1)[:, :n_top]  # (c, n_top)
        scores = np.take_along_axis(self.z_score, order, axis=1)  # (c, n_top)
        return order, scores


def column_midranks(X: Tensor) -> tuple[Tensor, Tensor]:
    """Return per-column midranks and the per-column tie-correction sum.

    Midranks are required rather than ordinal ranks because TopK sparse activations put a large
    tied mass at zero: most features are inactive in most proteins, and treating that block as an
    arbitrary ordering would inflate the statistic.
    """
    # X: (n, mc)
    n, n_features = X.shape
    sorted_values, sort_index = torch.sort(X, dim=0)  # (n, mc), (n, mc)
    positions = torch.arange(n, device=X.device, dtype=torch.float32).unsqueeze(1)  # (n, 1)
    positions = positions.expand(n, n_features)  # (n, mc)

    is_group_start = torch.ones_like(sorted_values, dtype=torch.bool)  # (n, mc)
    is_group_start[1:] = sorted_values[1:] != sorted_values[:-1]
    group_index = is_group_start.to(torch.int64).cumsum(0) - 1  # (n, mc)

    group_first = torch.full_like(positions, float(n))  # (n, mc)
    group_first.scatter_reduce_(0, group_index, positions, reduce="amin", include_self=True)
    group_last = torch.full_like(positions, -1.0)  # (n, mc)
    group_last.scatter_reduce_(0, group_index, positions, reduce="amax", include_self=True)

    midrank_sorted = (
        group_first.gather(0, group_index) + group_last.gather(0, group_index)
    ) / 2.0 + 1.0  # (n, mc)
    ranks = torch.empty_like(midrank_sorted)  # (n, mc)
    ranks.scatter_(0, sort_index, midrank_sorted)

    group_size = group_last - group_first + 1.0  # (n, mc), meaningful only at occupied slots
    is_occupied = group_last >= 0  # (n, mc)
    tie_correction = torch.where(
        is_occupied, group_size.pow(3) - group_size, torch.zeros_like(group_size)
    ).sum(dim=0)  # (mc,)

    return ranks, tie_correction


def mann_whitney_from_rank_sums(
    rank_sum: Tensor,
    n_positive: Tensor,
    tie_correction: Tensor,
    n_proteins: int,
) -> tuple[Tensor, Tensor]:
    """Convert rank sums to AUROC and a tie-corrected, continuity-corrected normal deviate."""
    # rank_sum: (mc, t); n_positive: (t,); tie_correction: (mc,)
    n = float(n_proteins)
    n_pos = n_positive.to(torch.float64).unsqueeze(0)  # (1, t)
    n_neg = n - n_pos  # (1, t)

    u_statistic = rank_sum.to(torch.float64) - n_pos * (n_pos + 1.0) / 2.0  # (mc, t)
    auroc = u_statistic / (n_pos * n_neg)  # (mc, t)

    mean_u = n_pos * n_neg / 2.0  # (1, t)
    tie_term = tie_correction.to(torch.float64).unsqueeze(1) / (n * (n - 1.0))  # (mc, 1)
    variance_u = (n_pos * n_neg / 12.0) * ((n + 1.0) - tie_term)  # (mc, t)

    deviation = u_statistic - mean_u  # (mc, t)
    corrected = torch.sign(deviation) * torch.clamp(deviation.abs() - 0.5, min=0.0)  # (mc, t)
    z_score = corrected / torch.sqrt(torch.clamp(variance_u, min=1e-12))  # (mc, t)

    return auroc, z_score


def _stratum_term_matrices(
    term_matrix: torch.Tensor,
    strata: np.ndarray,
    device: str,
) -> list[tuple[torch.Tensor, np.ndarray]]:
    """Split a `(t, n)` membership matrix into one `(t, n_s)` block per stratum."""
    # term_matrix: (t, n) sparse; strata: (n,)
    coordinates = term_matrix.to_sparse_coo().coalesce()
    term_index = coordinates.indices()[0].cpu().numpy()  # (nnz,)
    protein_index = coordinates.indices()[1].cpu().numpy()  # (nnz,)
    n_terms = term_matrix.shape[0]

    blocks: list[tuple[torch.Tensor, np.ndarray]] = []
    for stratum in np.unique(strata):
        members = np.flatnonzero(strata == stratum)  # (n_s,)
        position = np.full(len(strata), -1, dtype=np.int64)  # (n,)
        position[members] = np.arange(members.size)

        selected = position[protein_index] >= 0  # (nnz,)
        rows = torch.from_numpy(term_index[selected].astype(np.int64))
        columns = torch.from_numpy(position[protein_index[selected]])
        block = torch.sparse_coo_tensor(
            torch.stack([rows, columns]),
            torch.ones(rows.numel(), dtype=torch.float32),
            size=(n_terms, members.size),
        ).coalesce().to_sparse_csr().to(device)
        blocks.append((block, members))

    return blocks


def global_association(
    pooled: np.ndarray,
    term_matrix: torch.Tensor,
    device: str = "cuda",
    feature_chunk: int = DEFAULT_FEATURE_CHUNK,
    min_positive: int = 10,
    strata: np.ndarray | None = None,
) -> GlobalAssociation:
    """Score every (feature, term) pair by tie-corrected Mann-Whitney U.

    With `strata`, the test becomes the stratified form of the same statistic: ranks are computed
    inside each stratum and the per-stratum `U` statistics, means, and variances are summed. This
    is the van Elteren construction, and it is required here rather than optional. Both the pooled
    activation of a feature and the number of annotations a protein carries grow with sequence
    length, so an unstratified test reports a strong association between almost any feature and
    almost any term. Stratifying by length decile removes that confound by construction; the
    permutation null in `pipeline.cluster_block_null` measures whether it worked.

    Args:
        pooled: per-protein pooled activation, shape `(n, c)`.
        term_matrix: sparse membership with shape `(t, n)`, one row per term.
        device: device for the rank and matrix-product work.
        feature_chunk: number of feature columns ranked at once.
        min_positive: terms with fewer carriers overall are zeroed out.
        strata: optional `(n,)` stratum label per protein.
    """
    # pooled: (n, c); term_matrix: (t, n) sparse
    n_proteins, n_features = pooled.shape
    n_terms = term_matrix.shape[0]
    assert term_matrix.shape[1] == n_proteins, "term matrix and pooled matrix disagree on n"

    if strata is None:
        strata = np.zeros(n_proteins, dtype=np.int64)  # (n,)
    blocks = _stratum_term_matrices(term_matrix.cpu(), strata, device)

    n_positive_total = torch.zeros(n_terms, dtype=torch.float64, device=device)  # (t,)
    pair_count = torch.zeros(n_terms, dtype=torch.float64, device=device)  # (t,)
    for block, members in blocks:
        ones = torch.ones((members.size, 1), dtype=torch.float32, device=device)  # (n_s, 1)
        n_positive_s = torch.sparse.mm(block, ones).squeeze(1).to(torch.float64)  # (t,)
        n_positive_total += n_positive_s
        pair_count += n_positive_s * (members.size - n_positive_s)

    auroc_out = np.empty((n_features, n_terms), dtype=np.float16)  # (c, t)
    z_out = np.empty((n_features, n_terms), dtype=np.float32)  # (c, t)

    for start in range(0, n_features, feature_chunk):
        stop = min(start + feature_chunk, n_features)
        n_chunk = stop - start
        u_total = torch.zeros((n_chunk, n_terms), dtype=torch.float64, device=device)
        mean_total = torch.zeros((n_chunk, n_terms), dtype=torch.float64, device=device)
        variance_total = torch.zeros((n_chunk, n_terms), dtype=torch.float64, device=device)

        for block, members in blocks:
            activation = torch.from_numpy(
                np.ascontiguousarray(pooled[members, start:stop])
            ).to(device=device, dtype=torch.float32)  # (n_s, mc)
            ranks, tie_correction = column_midranks(activation)  # (n_s, mc), (mc,)
            rank_sum = torch.sparse.mm(block, ranks).transpose(0, 1)  # (mc, t)

            n_s = float(members.size)
            n_pos = torch.sparse.mm(
                block, torch.ones((members.size, 1), dtype=torch.float32, device=device)
            ).squeeze(1).to(torch.float64).unsqueeze(0)  # (1, t)
            n_neg = n_s - n_pos  # (1, t)

            u_total += rank_sum.to(torch.float64) - n_pos * (n_pos + 1.0) / 2.0
            mean_total += n_pos * n_neg / 2.0
            tie_term = tie_correction.to(torch.float64).unsqueeze(1) / max(n_s * (n_s - 1.0), 1.0)
            variance_total += (n_pos * n_neg / 12.0) * ((n_s + 1.0) - tie_term)

        deviation = u_total - mean_total  # (mc, t)
        corrected = torch.sign(deviation) * torch.clamp(deviation.abs() - 0.5, min=0.0)
        z_score = corrected / torch.sqrt(torch.clamp(variance_total, min=1e-12))  # (mc, t)
        auroc = u_total / torch.clamp(pair_count.unsqueeze(0), min=1.0)  # (mc, t)

        auroc_out[start:stop] = auroc.to(torch.float16).cpu().numpy()
        z_out[start:stop] = z_score.to(torch.float32).cpu().numpy()

    n_positive = n_positive_total.cpu().numpy()  # (t,)
    unusable = (n_positive < min_positive) | (n_positive > n_proteins - min_positive)
    z_out[:, unusable] = 0.0

    return GlobalAssociation(
        auroc=auroc_out,
        z_score=z_out,
        n_positive=n_positive.astype(np.int64),
        n_proteins=n_proteins,
    )


def benjamini_hochberg_threshold(
    z_score: np.ndarray,
    alpha: float = 0.01,
    row_block: int = 512,
) -> float:
    """Return the smallest `|z|` that survives Benjamini-Hochberg control at level `alpha`.

    The test count is `c * t`, up to about 1.5 billion here, which is too large to sort and too
    large to pass through `numpy.histogram` in one call without materializing several copies of a
    multi-gigabyte array. The histogram is accumulated over row blocks instead, which touches each
    value once and holds only one block at a time.

    Because the two-sided p-value is a strictly decreasing function of `|z|`, counting tests above a
    threshold is equivalent to counting p-values below the matching cutoff, so the ordering BH needs
    is recovered from the histogram without sorting.
    """
    # z_score: (c, t)
    edges = np.linspace(0.0, Z_HISTOGRAM_MAX, Z_HISTOGRAM_BINS + 1)  # (bins+1,)
    counts = np.zeros(Z_HISTOGRAM_BINS, dtype=np.int64)  # (bins,)
    n_tests = 0

    for start in range(0, z_score.shape[0], row_block):
        block = np.abs(z_score[start : start + row_block]).ravel()  # (block*t,)
        np.clip(block, 0.0, Z_HISTOGRAM_MAX, out=block)
        counts += np.bincount(
            np.minimum((block * (Z_HISTOGRAM_BINS / Z_HISTOGRAM_MAX)).astype(np.int64), Z_HISTOGRAM_BINS - 1),
            minlength=Z_HISTOGRAM_BINS,
        )
        n_tests += block.size

    n_at_least = np.cumsum(counts[::-1])[::-1]  # (bins,) tests with |z| >= edges[i]
    p_at_edge = 2.0 * stats.norm.sf(edges[:-1])  # (bins,)
    survives = p_at_edge <= (n_at_least * alpha / max(n_tests, 1))
    if not survives.any():
        return float("inf")

    return float(edges[:-1][survives][0])


def merge_spans(
    span_protein: np.ndarray,
    span_term: np.ndarray,
    span_start: np.ndarray,
    span_end: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Merge overlapping and touching spans that share a protein and a term.

    UniProt records several features of the same type on one protein and they can overlap, and the
    InterPro coordinate map produces overlapping intervals for the same entry routinely. Left
    unmerged, a residue inside two overlapping spans is counted twice in the observed activation
    count and twice in the coverage, so the observed count and the hypergeometric variance stop
    describing the same set of positions and the test is no longer calibrated.
    """
    # span_*: (s,)
    order = np.lexsort((span_start, span_term, span_protein))  # (s,)
    protein = span_protein[order]  # (s,)
    term = span_term[order]  # (s,)
    start = span_start[order]  # (s,)
    end = span_end[order]  # (s,)

    keep_protein: list[int] = []
    keep_term: list[int] = []
    keep_start: list[int] = []
    keep_end: list[int] = []

    for index in range(len(order)):
        same_group = (
            keep_protein
            and keep_protein[-1] == protein[index]
            and keep_term[-1] == term[index]
        )
        if same_group and start[index] <= keep_end[-1] + 1:
            keep_end[-1] = max(keep_end[-1], int(end[index]))
            continue
        keep_protein.append(int(protein[index]))
        keep_term.append(int(term[index]))
        keep_start.append(int(start[index]))
        keep_end.append(int(end[index]))

    return (
        np.asarray(keep_protein, dtype=np.int64),
        np.asarray(keep_term, dtype=np.int64),
        np.asarray(keep_start, dtype=np.int64),
        np.asarray(keep_end, dtype=np.int64),
    )


def _span_residue_pairs(
    span_protein: np.ndarray,
    span_term: np.ndarray,
    span_start: np.ndarray,
    span_end: np.ndarray,
    residue_offset: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Expand annotated spans into `(residue_row, term_index)` pairs.

    Coordinates arrive 1-based inclusive in sequence space; residue rows are 0-based into the
    concatenated per-residue activation array. Spans must already be merged, so each pair is
    distinct.
    """
    # span_*: (s,); residue_offset: (n,)
    lengths = (span_end - span_start + 1).astype(np.int64)  # (s,)
    assert bool((lengths > 0).all()), "span end precedes span start"

    total = int(lengths.sum())
    repeat_index = np.repeat(np.arange(len(lengths)), lengths)  # (p,)
    within_span = np.arange(total) - np.repeat(np.cumsum(lengths) - lengths, lengths)  # (p,)

    residue_row = (
        residue_offset[span_protein[repeat_index]] + span_start[repeat_index] - 1 + within_span
    )  # (p,)
    return residue_row, span_term[repeat_index]


@dataclass(frozen=True, slots=True)
class LocalAssociation:
    """Per-(feature, local term) stratified association results."""

    observed: np.ndarray
    expected: np.ndarray
    variance: np.ndarray
    n_strata: np.ndarray

    @property
    def z_score(self) -> np.ndarray:
        """Return the continuity-corrected Cochran-Mantel-Haenszel deviate."""
        # observed, expected, variance: (c, t_local)
        deviation = self.observed - self.expected  # (c, t_local)
        corrected = np.sign(deviation) * np.maximum(np.abs(deviation) - 0.5, 0.0)  # (c, t_local)
        return corrected / np.sqrt(np.maximum(self.variance, 1e-12))

    @property
    def enrichment(self) -> np.ndarray:
        """Return observed over expected inside-span activation counts."""
        return self.observed / np.maximum(self.expected, 1e-9)


def local_association(
    residue_features: np.ndarray,
    residue_offset: np.ndarray,
    n_residues: np.ndarray,
    pooled_count: np.ndarray,
    span_protein: np.ndarray,
    span_term: np.ndarray,
    span_start: np.ndarray,
    span_end: np.ndarray,
    n_local_terms: int,
    n_features: int,
    device: str = "cuda",
    residue_chunk: int = 20_000_000,
    min_strata: int = 1,
) -> LocalAssociation:
    """Score every (feature, local term) pair by a protein-stratified CMH test.

    Within one protein of length `l`, treat the `k_f` residues where feature `f` is active as a
    random draw without replacement from the `l` positions. Under that null, the count of active
    residues falling inside the `n_1` positions annotated with term `j` is hypergeometric, so the
    stratum contributes mean `n_1 k_f / l` and variance `n_1 (l - n_1) k_f (l - k_f) / (l^2 (l-1))`.
    Summing observed counts, means, and variances over proteins gives the CMH statistic.

    Args:
        residue_features: TopK feature indices per residue, shape `(r, k)`.
        residue_offset: first residue row of each protein, shape `(n,)`.
        n_residues: residue count of each protein, shape `(n,)`.
        pooled_count: active-residue count per protein and feature, shape `(n, c)`.
        span_protein, span_term, span_start, span_end: parallel span arrays of shape `(s,)`.
        n_local_terms: number of distinct local terms, `t_local`.
        n_features: codebook size, `c`.
    """
    # residue_features: (r, k)
    span_protein, span_term, span_start, span_end = merge_spans(
        span_protein, span_term, span_start, span_end
    )
    residue_row, term_index = _span_residue_pairs(
        span_protein, span_term, span_start, span_end, residue_offset
    )  # (p,), (p,)

    observed = torch.zeros(n_features * n_local_terms, dtype=torch.float32, device=device)  # (c*t,)
    for start in range(0, len(residue_row), residue_chunk):
        stop = min(start + residue_chunk, len(residue_row))
        rows = torch.from_numpy(residue_row[start:stop].astype(np.int64))
        terms = torch.from_numpy(term_index[start:stop].astype(np.int64)).to(device)  # (p_chunk,)
        features = torch.from_numpy(
            residue_features[residue_row[start:stop]].astype(np.int64)
        ).to(device)  # (p_chunk, k)
        flat = features * n_local_terms + terms.unsqueeze(1)  # (p_chunk, k)
        observed.scatter_add_(
            0, flat.reshape(-1), torch.ones(flat.numel(), dtype=torch.float32, device=device)
        )
        del rows

    # Per-protein span coverage per term. Kept sparse: a dense (n, t_local) coverage matrix would
    # need tens of gigabytes at Swiss-Prot scale, while only a few (protein, term) pairs per
    # protein are ever nonzero.
    span_length = (span_end - span_start + 1).astype(np.float64)  # (s,)
    pair_key = span_protein.astype(np.int64) * n_local_terms + span_term.astype(np.int64)  # (s,)
    unique_key, inverse = np.unique(pair_key, return_inverse=True)  # (q,), (s,)
    coverage_value = np.zeros(unique_key.size, dtype=np.float64)  # (q,)
    np.add.at(coverage_value, inverse, span_length)

    pair_protein = (unique_key // n_local_terms).astype(np.int64)  # (q,)
    pair_term = (unique_key % n_local_terms).astype(np.int64)  # (q,)
    protein_length = n_residues.astype(np.float64)  # (n,)
    coverage_value = np.minimum(coverage_value, protein_length[pair_protein])

    expected = torch.zeros(n_local_terms, n_features, dtype=torch.float32, device=device)
    variance = torch.zeros(n_local_terms, n_features, dtype=torch.float32, device=device)
    n_strata = torch.zeros(n_local_terms, n_features, dtype=torch.float32, device=device)

    protein_chunk = max(1, 400_000_000 // max(n_features, 1))
    for start in range(0, len(n_residues), protein_chunk):
        stop = min(start + protein_chunk, len(n_residues))
        in_chunk = (pair_protein >= start) & (pair_protein < stop)
        if not in_chunk.any():
            continue

        active = torch.from_numpy(pooled_count[start:stop].astype(np.float32)).to(device)  # (m, c)
        chunk_length = torch.from_numpy(protein_length[start:stop]).to(
            device=device, dtype=torch.float32
        ).unsqueeze(1)  # (m, 1)

        rows = torch.from_numpy(pair_term[in_chunk]).to(device)  # (q_chunk,)
        columns = torch.from_numpy(pair_protein[in_chunk] - start).to(device)  # (q_chunk,)
        coverage = torch.from_numpy(coverage_value[in_chunk]).to(
            device=device, dtype=torch.float32
        )  # (q_chunk,)
        pair_index = torch.stack([rows, columns])  # (2, q_chunk)
        chunk_size = (n_local_terms, stop - start)

        def sparse_by(values: torch.Tensor) -> torch.Tensor:
            """Return a sparse `(t_local, m)` matrix carrying one weight per coverage pair."""
            return torch.sparse_coo_tensor(pair_index, values, size=chunk_size).coalesce()

        mean_weight = active / chunk_length  # (m, c)
        expected += torch.sparse.mm(sparse_by(coverage), mean_weight)  # (t_local, c)

        variance_weight = active * (chunk_length - active) / (
            chunk_length.pow(2) * torch.clamp(chunk_length - 1.0, min=1.0)
        )  # (m, c)
        outside = chunk_length.squeeze(1)[columns] - coverage  # (q_chunk,)
        variance += torch.sparse.mm(sparse_by(coverage * outside), variance_weight)  # (t_local, c)

        n_strata += torch.sparse.mm(
            sparse_by(torch.ones_like(coverage)), (active > 0).to(torch.float32)
        )  # (t_local, c)

    return LocalAssociation(
        observed=observed.view(n_features, n_local_terms).cpu().numpy().astype(np.float64),
        expected=expected.transpose(0, 1).cpu().numpy().astype(np.float64),
        variance=variance.transpose(0, 1).cpu().numpy().astype(np.float64),
        n_strata=n_strata.transpose(0, 1).cpu().numpy().astype(np.float64),
    )
