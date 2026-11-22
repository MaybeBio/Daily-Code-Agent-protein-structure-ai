"""Run the full SAE-to-vocabulary association analysis for one extraction run.

Four protein sets are kept strictly separate, which is what makes the comparison honest. Splits are
assigned to whole MMseqs2 clusters, so disjointness holds at cluster level and is asserted at run
time rather than assumed:

- **Discovery**, the train split only, one representative per cluster, with every cluster containing
  a released Biohub exemplar removed. This fits the feature-to-term assignment.
- **Validation**, the validation split only, same exemplar exclusion. This chooses the ranking rule
  and support floor. Nothing else is tuned.
- **Test**, the test split only, same exemplar exclusion. Evaluated once against the frozen choice,
  with no reselection.
- **Concordance**, the released exemplars, which none of the three ever saw.

An earlier version of this module drew discovery representatives from every split, so test clusters
contributed to the assignment they were then used to evaluate. Every held-out number produced before
that fix is invalid.

Symbols: `n` proteins, `c` codebook features, `t` vocabulary terms, `k` active features per
residue, `r` residues.
"""

import argparse
import json
import math
import time
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import torch

from dataclasses import dataclass
from pathlib import Path

from .association import (
    GlobalAssociation,
    merge_spans,
    benjamini_hochberg_threshold,
    global_association,
    local_association,
)
from .biohub import (
    category_recovery,
    lexical_agreement,
    load_feature_table,
    pipeline_fidelity,
    reference_accessions,
    term_concordance,
)
from .provenance import (
    POOLING_MODES,
    _digest,
    analysis_input_inventory,
    external_provenance,
    require_file,
    require_unchanged_inputs,
)
from .uncertainty import cluster_bootstrap_auroc, recall_at_precision
from ..feature_cache import RESIDUE_TOPK
from ..feature_views import ExtractionArrays, open_extraction


DEFAULT_SEED = 20260826
DEFAULT_PERMUTATIONS = 8
DEFAULT_LENGTH_BINS = 20
DEFAULT_ANNOTATION_BINS = 10
MIN_STRATUM_SIZE = 250
DOMAIN_CATEGORIES = ("Bacteria", "Archaea", "Eukaryota", "Viruses", "Other")
DOMAIN_BY_TAXON_ID = {2: "Bacteria", 2157: "Archaea", 2759: "Eukaryota", 10239: "Viruses"}
DOMAIN_BY_CASEFOLDED_NAME = {
    domain.casefold(): domain for domain in DOMAIN_CATEGORIES[:-1]
}
DOMAIN_MAPPING_VERSION = "ncbi-superkingdom-ids-v1"
UNRESOLVED_DOMAIN_EXCLUSION_REASON = (
    "domain mapping resolved to Other; excluded before discovery cluster representative "
    "selection for both primary and length-density-only stratification"
)
DOMAIN_OTHER_POLICY = (
    "empty or wholly unrecognized lineage metadata maps to Other; "
    "Other rows are excluded from discovery before both stratification strategies and remain "
    "eligible for validation and test evaluation"
)


def strict_json(value: object) -> object:
    """Return nested values that serialize as strict JSON.

    `json.dumps` emits bare `NaN` and `Infinity` by default, which are not valid JSON and are
    rejected by strict parsers. A quantity that could not be computed is written as null, which
    every parser accepts and which reads as "not measured" rather than as a number.
    """
    if isinstance(value, dict):
        return {str(key): strict_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@dataclass(slots=True)
class ExtractionRun:
    """Feature-store views of one extraction pass, aligned to a protein table."""

    directory: Path
    protein_index: pd.DataFrame
    manifest: dict
    arrays: ExtractionArrays

    @property
    def n_features(self) -> int:
        return int(self.manifest["metrics"]["codebook_dim"])

    @property
    def k(self) -> int:
        return int(self.manifest["metrics"]["k"])

    def pooled(self, name: str) -> np.ndarray:
        """Return the `(n, c)` pooled activation view for one pooling mode.

        `fraction` is derived rather than stored: it is the active-residue count divided by protein
        length. Biohub's tutorial recommends raw prevalence for ranking features within one protein,
        where length is constant. Across proteins the raw count tracks length directly, and the
        confound probe measures a pseudo-term AUROC of 0.94 for it even after stratification, so the
        length-normalized form is the one that can be compared between proteins.
        """
        if name == "fraction":
            counts = self.arrays.pooled_count  # (n, c)
            length = self.protein_index["n_residues"].to_numpy().astype(np.float32)  # (n,)
            return np.asarray(counts, dtype=np.float32) / np.maximum(length[:, None], 1.0)  # (n, c)
        return self.arrays.pooled(name)  # (n, c)

    def residue_features(self) -> np.ndarray:
        """Return the `(r, k)` TopK feature-index view."""
        return self.arrays.residue_features  # (r, k)

    def residue_values(self) -> np.ndarray:
        """Return the `(r, k)` TopK activation view."""
        return self.arrays.residue_values  # (r, k)

    def close(self) -> None:
        """Release the store readers; views obtained earlier refuse further reads."""
        self.arrays.close()


def load_run(run_dir: str) -> ExtractionRun:
    """Load one extraction run from its feature store, tolerating a missing manifest.

    Every indexed protein must have a stored row, so a pass that is still running cannot be
    opened: the store refuses a run whose rows are incomplete rather than serving zeros for the
    rows it has not written. Without a manifest the shapes are read from the stored features.
    """
    directory = Path(run_dir)
    manifest_path = directory / "manifest.json"
    arrays = open_extraction(directory)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
    else:
        manifest = {
            "config": {},
            "metrics": {
                "codebook_dim": arrays.n_features,
                "k": arrays.k if RESIDUE_TOPK in arrays.readers else 0,
                "incomplete": 1.0,
            },
        }

    return ExtractionRun(
        directory=directory,
        protein_index=pd.read_parquet(directory / "protein_index.parquet"),
        manifest=manifest,
        arrays=arrays,
    )


def align_proteins(run: ExtractionRun, proteins: pd.DataFrame) -> pd.DataFrame:
    """Join the vocabulary protein table onto the extraction row order.

    The extraction indexes rows by accession sort order; the vocabulary release may not. Joining
    rather than assuming a shared order is the only safe option, and the inner join also drops
    proteins the vocabulary build excluded.
    """
    merged = (
        run.protein_index.reset_index(names="activation_row")
        .merge(proteins, on="accession", how="inner", validate="one_to_one")
        .reset_index(drop=True)
    )
    assert len(merged) > 0, "no accessions shared between extraction and vocabulary tables"
    return merged


def build_term_matrix(
    token_lists: pd.Series,
    n_terms: int,
    row_subset: np.ndarray,
) -> torch.Tensor:
    """Return a sparse `(t, n_subset)` binary term-membership matrix.

    Terms index the rows so that `torch.sparse.mm(term_matrix, ranks)` gives `(t, mc)` rank sums
    directly, which is the layout the Mann-Whitney conversion expects.
    """
    # token_lists: (n,) of variable-length int arrays; row_subset: (n_subset,)
    term_index: list[np.ndarray] = []
    protein_index: list[np.ndarray] = []

    for position, source_row in enumerate(row_subset):
        tokens = np.unique(np.asarray(token_lists.iat[int(source_row)], dtype=np.int64))
        tokens = tokens[(tokens >= 0) & (tokens < n_terms)]
        term_index.append(tokens)
        protein_index.append(np.full(tokens.size, position, dtype=np.int64))

    rows = np.concatenate(term_index) if term_index else np.zeros(0, dtype=np.int64)
    columns = np.concatenate(protein_index) if protein_index else np.zeros(0, dtype=np.int64)
    indices = torch.from_numpy(np.stack([rows, columns]))  # (2, nnz)
    values = torch.ones(rows.size, dtype=torch.float32)  # (nnz,)

    return (
        torch.sparse_coo_tensor(indices, values, size=(n_terms, len(row_subset)))
        .coalesce()
        .to_sparse_csr()  # (t, n_subset)
    )


def cluster_representatives(
    aligned: pd.DataFrame,
    eligible: np.ndarray,
    rule: str = "mmseqs",
    members_per_cluster: int = 1,
) -> np.ndarray:
    """Return positions into `aligned`, at most `members_per_cluster` per cluster.

    One member per cluster is the primary setting. Taking more raises the support available to rare
    terms, at the cost of homologous proteins entering discovery together, and that cost is **not**
    absorbed by the null: `cluster_block_null` permutes rows, so homologous members move
    independently and the null loses the within-cluster correlation the observed statistic keeps. A
    run with `members_per_cluster > 1` therefore has an under-corrected threshold and its assignment
    count is not comparable with a one-representative run. Members are ordered by accession, which
    is independent of the annotations being tested.

    The default picks the MMseqs2 cluster representative, whose accession equals `cluster_id`,
    falling back to the lowest accession when that representative is not eligible. That choice is
    independent of the annotations, which matters: selecting the best-annotated member would
    condition the discovery sample on the very labels being tested, and on how well studied a
    protein is. `annotated` reproduces the old behavior and is kept only as a labeled sensitivity.
    """
    # aligned: (n,) rows; eligible: (n,) boolean mask
    working = aligned.loc[eligible, ["accession", "cluster_id", "annotations"]].copy()
    working["position"] = np.flatnonzero(eligible)

    if rule == "annotated":
        working["priority"] = -working["annotations"].map(len)
    else:
        working["priority"] = (working["accession"] != working["cluster_id"]).astype(int)

    working = working.sort_values(
        ["cluster_id", "priority", "accession"], ascending=[True, True, True], kind="stable"
    )
    if members_per_cluster <= 1:
        return np.sort(working.groupby("cluster_id", sort=False)["position"].first().to_numpy())  # (n_rep,) positions into aligned, one per cluster
    taken = working.groupby("cluster_id", sort=False).head(members_per_cluster)
    return np.sort(taken["position"].to_numpy())  # (n_rep,)


def stratified_permutation(
    values: np.ndarray, strata: np.ndarray, generator: np.random.Generator
) -> np.ndarray:
    """Shuffle `values` only within each stratum, leaving the stratum composition unchanged."""
    # values: (m,); strata: (m,)
    permuted = values.copy()  # (m,)
    for stratum in np.unique(strata):
        selected = strata == stratum
        permuted[selected] = generator.permutation(values[selected])
    return permuted  # (m,)


def assign_terms(
    association: GlobalAssociation,
    min_auroc: float,
    z_threshold: float,
    min_support: int = 50,
    rank_by: str = "auroc",
    term_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pick one vocabulary term per feature, or -1 where no term clears every threshold.

    Significance and specificity are separate decisions and are made separately here. A term must
    first clear the permutation-calibrated `z_threshold`, a minimum AUROC, and a minimum number of
    carriers; among the survivors the term is chosen by `rank_by`.

    The default ranks by AUROC rather than by `z`, because `z` grows with the number of carriers and
    would systematically prefer a broad term over the specific one that actually describes the
    feature. For a feature that fires on trypsin-like serine proteases, ranking by `z` tends to
    return "proteolysis", which is true of far more proteins and therefore better powered; ranking
    by AUROC returns the trypsin domain. The support floor keeps AUROC from being decided by a
    handful of proteins.

    `term_mask` withholds terms from assignment without removing them from the association, which is
    how a vocabulary revision is evaluated on an existing run: the statistics are unchanged and only
    the pool a feature may be described from shrinks.
    """
    # association.z_score, association.auroc: (c, t); association.n_positive: (t,); term_mask: (t,) or None
    z_score = association.z_score  # (c, t)
    auroc = association.auroc.astype(np.float32)  # (c, t)
    eligible = (
        (z_score >= z_threshold)
        & (auroc >= min_auroc)
        & (association.n_positive >= min_support)[None, :]
    )  # (c, t)
    if term_mask is not None:
        eligible &= term_mask[None, :]  # (c, t)

    score = auroc if rank_by == "auroc" else z_score  # (c, t)
    masked = np.where(eligible, score, -np.inf)  # (c, t)

    best_term = np.argmax(masked, axis=1)  # (c,)
    best_score = np.take_along_axis(masked, best_term[:, None], axis=1).ravel()  # (c,)
    best_z = np.take_along_axis(z_score, best_term[:, None], axis=1).ravel()  # (c,)
    best_auroc = np.take_along_axis(auroc, best_term[:, None], axis=1).ravel()  # (c,)

    unassigned = ~np.isfinite(best_score)
    best_term[unassigned] = -1
    best_z[unassigned] = np.nan
    best_auroc[unassigned] = np.nan
    return best_term, best_z, best_auroc  # (c,), (c,), (c,)


def evaluate_held_out(
    pooled: np.ndarray,
    token_lists: pd.Series,
    positions: np.ndarray,
    activation_rows: np.ndarray,
    assigned_term: np.ndarray,
    n_terms: int,
) -> pd.DataFrame:
    """Score each feature's assigned term on held-out proteins by AUROC and average precision."""
    from sklearn.metrics import average_precision_score, roc_auc_score

    # pooled: (n_all, c); positions: (n_eval,) rows of the aligned frame; activation_rows: (n,) map into pooled
    # assigned_term: (c,)
    membership = np.zeros((len(positions), n_terms), dtype=bool)  # (n_eval, t)
    for offset, position in enumerate(positions):
        tokens = np.asarray(token_lists.iat[int(position)], dtype=np.int64)
        tokens = tokens[(tokens >= 0) & (tokens < n_terms)]
        membership[offset, tokens] = True

    activations = np.asarray(pooled[activation_rows[positions]], dtype=np.float32)  # (n_eval, c)
    records: list[dict[str, float]] = []

    for feature in range(activations.shape[1]):
        term = int(assigned_term[feature])
        if term < 0:
            continue
        labels = membership[:, term]  # (n_eval,)
        n_positive = int(labels.sum())
        if n_positive < 5 or n_positive == len(labels):
            continue
        scores = activations[:, feature]  # (n_eval,)
        records.append(
            {
                "feature_id": feature,
                "term": term,
                "n_positive": n_positive,
                "n_total": len(labels),
                "auroc": float(roc_auc_score(labels, scores)),
                "average_precision": float(average_precision_score(labels, scores)),
                "prevalence": n_positive / len(labels),
                "recall_at_precision_50": recall_at_precision(scores, labels, 0.5),
                # Average precision is bounded below by prevalence, so a rare term looks bad and a
                # common one looks good regardless of the feature. The lift is the comparable number.
                "ap_lift": float(average_precision_score(labels, scores)) / (n_positive / len(labels)),
            }
        )

    return pd.DataFrame(records)


def _quantile_bin(values: np.ndarray, n_bins: int) -> np.ndarray:
    """Return a quantile bin index per element, tolerating heavily tied inputs."""
    # values: (m,)
    if n_bins <= 1:
        return np.zeros(len(values), dtype=np.int64)  # (m,)
    labels = pd.qcut(pd.Series(values).rank(method="first"), q=n_bins, labels=False, duplicates="drop")
    return np.asarray(labels, dtype=np.int64)  # (m,)


def _lineage_values(value: object, *, split_scalar: bool) -> tuple[object, ...]:
    """Return one list-valued field or a delimiter-separated legacy scalar as a tuple."""
    if isinstance(value, np.ndarray):
        return tuple(value.tolist())
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, float) and math.isnan(value):
        return ()
    if split_scalar:
        return tuple(str(value).replace(";", ">").split(">"))
    return (value,)


def _paired_domain(names_value: object, ids_value: object, row_id: str) -> str:
    """Resolve one validated V2 lineage pair to a pinned domain."""
    sequence_types = (list, tuple, np.ndarray)
    if not isinstance(names_value, sequence_types) or not isinstance(ids_value, sequence_types):
        raise ValueError(f"row {row_id}: V2 lineage fields must both be arrays")
    raw_names = _lineage_values(names_value, split_scalar=False)
    raw_ids = _lineage_values(ids_value, split_scalar=False)
    if len(raw_names) != len(raw_ids):
        raise ValueError(
            f"row {row_id}: lineage_taxon_ids and lineage_names have unequal lengths "
            f"({len(raw_ids)} != {len(raw_names)})"
        )

    recognized: list[str] = []
    for position, (raw_id, raw_name) in enumerate(zip(raw_ids, raw_names, strict=False)):
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, np.integer)):
            raise ValueError(
                f"row {row_id}, lineage position {position}: taxon ID must be a positive integer"
            )
        taxon_id = int(raw_id)
        if taxon_id <= 0:
            raise ValueError(
                f"row {row_id}, lineage position {position}: taxon ID must be positive"
            )
        if not isinstance(raw_name, str) or not raw_name or raw_name != raw_name.strip():
            raise ValueError(
                f"row {row_id}, lineage position {position}: name must be a nonempty "
                "stripped string"
            )

        id_domain = DOMAIN_BY_TAXON_ID.get(taxon_id)
        name_domain = DOMAIN_BY_CASEFOLDED_NAME.get(raw_name.casefold())
        if (id_domain is None) != (name_domain is None):
            raise ValueError(
                f"row {row_id}, lineage position {position}: domain ID/name recognition disagrees "
                f"for ({taxon_id}, {raw_name!r})"
            )
        if id_domain is not None and id_domain != name_domain:
            raise ValueError(
                f"row {row_id}, lineage position {position}: domain ID/name conflict for "
                f"({taxon_id}, {raw_name!r})"
            )
        if id_domain is not None:
            recognized.append(id_domain)

    if len(recognized) > 1:
        raise ValueError(f"row {row_id}: lineage contains multiple domain anchors: {recognized}")
    return recognized[0] if recognized else "Other"


def _legacy_domain(value: object, row_id: str) -> str:
    """Resolve a legacy scalar by exact components, mapping unknown or missing values to Other."""
    if value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return "Other"
    if not isinstance(value, str):
        raise ValueError(f"row {row_id}: legacy lineage must be a scalar string or null")
    names = [part.strip() for part in value.replace(";", ">").split(">") if part.strip()]
    recognized = [
        DOMAIN_BY_CASEFOLDED_NAME[name.casefold()]
        for name in names
        if name.casefold() in DOMAIN_BY_CASEFOLDED_NAME
    ]
    if len(recognized) > 1:
        raise ValueError(
            f"row {row_id}: legacy lineage contains multiple domain anchors: {recognized}"
        )
    return recognized[0] if recognized else "Other"


def coarse_domain(
    lineage_names: np.ndarray,
    lineage_taxon_ids: np.ndarray | None = None,
    row_ids: np.ndarray | None = None,
) -> np.ndarray:
    """Map paired V2 lineages or a legacy scalar column to fixed domain categories.

    Pinned NCBI superkingdom IDs are authoritative in paired V2 mode. Each recognized ID must align
    with its exact canonical name component after stripping and case folding. Unknown ID/name pairs,
    empty V2 arrays, and missing or unrecognized legacy scalars map explicitly to ``Other``.
    """
    # lineage_names: (m,) object, one scalar or array per protein; lineage_taxon_ids: (m,) object or None
    # row_ids: (m,) or None
    if lineage_names.ndim != 1:
        raise ValueError("lineage_names must be a one-dimensional array")
    n_rows = len(lineage_names)
    if lineage_taxon_ids is not None and (
        lineage_taxon_ids.ndim != 1 or len(lineage_taxon_ids) != n_rows
    ):
        raise ValueError("lineage_taxon_ids must be a one-dimensional array aligned to names")
    if row_ids is None:
        row_ids = np.asarray([str(index) for index in range(n_rows)], dtype=object)
    elif row_ids.ndim != 1 or len(row_ids) != n_rows:
        raise ValueError("row_ids must be a one-dimensional array aligned to lineage metadata")

    domains = []
    for index in range(n_rows):
        row_id = str(row_ids[index])
        if lineage_taxon_ids is None:
            domains.append(_legacy_domain(lineage_names[index], row_id))
        else:
            domains.append(
                _paired_domain(lineage_names[index], lineage_taxon_ids[index], row_id)
            )
    return np.asarray(domains, dtype=object)  # (m,)


@dataclass(slots=True)
class DomainMapping:
    """Prevalidated domain labels and their dataset-level provenance."""

    domains: np.ndarray
    mode: str
    source_columns: tuple[str, ...]


def resolve_domain_metadata(frame: pd.DataFrame) -> DomainMapping:
    """Select paired V2 metadata without falling back from a malformed V2 representation."""
    has_names = "lineage_names" in frame.columns
    has_ids = "lineage_taxon_ids" in frame.columns
    row_ids = (
        frame["accession"].astype(str).to_numpy()
        if "accession" in frame.columns
        else frame.index.astype(str).to_numpy()
    )
    if has_names != has_ids:
        present = "lineage_names" if has_names else "lineage_taxon_ids"
        raise ValueError(f"V2 domain mapping requires both lineage arrays; found only {present}")
    if has_names:
        return DomainMapping(
            domains=coarse_domain(
                frame["lineage_names"].to_numpy(),
                frame["lineage_taxon_ids"].to_numpy(),
                row_ids,
            ),
            mode="paired_v2_lineage",
            source_columns=("lineage_names", "lineage_taxon_ids"),
        )

    legacy_columns = tuple(
        name for name in ("coarse_lineage", "lineage") if name in frame.columns
    )
    if not legacy_columns:
        raise ValueError("domain adjustment requires paired V2 lineage arrays or a legacy scalar")
    mapped = [coarse_domain(frame[name].to_numpy(), row_ids=row_ids) for name in legacy_columns]
    for candidate in mapped[1:]:
        if not np.array_equal(candidate, mapped[0]):
            raise ValueError(f"legacy lineage columns disagree: {legacy_columns}")
    return DomainMapping(
        domains=mapped[0],
        mode="legacy_scalar_lineage",
        source_columns=legacy_columns,
    )


def summarize_domain_mapping(mapping: DomainMapping) -> dict[str, object]:
    """Serialize the exact domain-mapping contract used for one aligned population."""
    return {
        "mode": mapping.mode,
        "source_columns": list(mapping.source_columns),
        "mapping_version": DOMAIN_MAPPING_VERSION,
        "taxon_id_to_domain": {
            str(taxon_id): domain for taxon_id, domain in DOMAIN_BY_TAXON_ID.items()
        },
        "other_policy": DOMAIN_OTHER_POLICY,
        "population_size": int(len(mapping.domains)),
        "domain_counts": {
            domain: int((mapping.domains == domain).sum()) for domain in DOMAIN_CATEGORIES
        },
    }


def exclude_unresolved_discovery_candidates(
    candidate_mask: np.ndarray,
    domains: np.ndarray,
    accessions: np.ndarray,
) -> tuple[np.ndarray, dict[str, object]]:
    """Exclude predeclared unresolved-domain rows from discovery candidates only."""
    # candidate_mask: (m,) bool; domains: (m,); accessions: (m,)
    if candidate_mask.ndim != 1 or candidate_mask.dtype != np.bool_:
        raise ValueError("candidate_mask must be a one-dimensional boolean array")
    if domains.ndim != 1 or accessions.ndim != 1:
        raise ValueError("domains and accessions must be one-dimensional arrays")
    if len(candidate_mask) != len(domains) or len(candidate_mask) != len(accessions):
        raise ValueError("candidate_mask, domains, and accessions must be aligned")

    excluded_mask = candidate_mask & (domains == "Other")
    retained_mask = candidate_mask & ~excluded_mask
    candidate_count = int(candidate_mask.sum())
    excluded_count = int(excluded_mask.sum())
    retained_count = int(retained_mask.sum())
    excluded_accessions = sorted(str(value) for value in accessions[excluded_mask])
    report: dict[str, object] = {
        "category": "Other",
        "count": excluded_count,
        "candidate_count_before_exclusion": candidate_count,
        "retained_candidate_count": retained_count,
        "accessions": excluded_accessions,
        "reason": UNRESOLVED_DOMAIN_EXCLUSION_REASON,
        "scope": "discovery candidates only; validation and test evaluation unchanged",
        "applied_to": ["primary", "length_density_only_sensitivity"],
    }
    if np.any(retained_mask & (domains == "Other")):
        raise AssertionError("an unresolved-domain discovery candidate silently remained")
    if candidate_count != retained_count + excluded_count:
        raise AssertionError("unresolved-domain discovery exclusion did not conserve rows")
    return retained_mask, report  # retained_mask: (m,) bool


def _stratum_size_summary(sizes: np.ndarray, min_size: int) -> dict[str, object]:
    """Return the complete realized size distribution for a nonempty set of strata."""
    # sizes: (s,) protein count per stratum
    if sizes.size == 0:
        raise ValueError("cannot summarize an empty stratum collection")
    quartiles = np.quantile(sizes, [0.25, 0.5, 0.75])
    unique, counts = np.unique(sizes, return_counts=True)
    return {
        "n_strata": int(sizes.size),
        "target_met": bool((sizes >= min_size).all()),
        "minimum": int(sizes.min()),
        "first_quartile": float(quartiles[0]),
        "median": float(quartiles[1]),
        "third_quartile": float(quartiles[2]),
        "maximum": int(sizes.max()),
        "singleton_count": int((sizes == 1).sum()),
        "count_below_floor": int((sizes < min_size).sum()),
        "proteins_below_floor": int(sizes[sizes < min_size].sum()),
        "quantile_method": "linear",
        "sizes": [int(size) for size in np.sort(sizes)],
        "size_histogram": {str(int(size)): int(count) for size, count in zip(unique, counts, strict=False)},
    }


def summarize_strata(
    strata: np.ndarray,
    domains: np.ndarray,
    min_size: int,
    *,
    domain_adjusted: bool,
) -> dict[str, object]:
    """Serialize population, domain, and realized stratum-size distributions."""
    # strata: (m,) integer stratum label per protein; domains: (m,) domain category per protein
    if strata.ndim != 1 or domains.ndim != 1 or len(strata) != len(domains):
        raise ValueError("strata and domains must be aligned one-dimensional arrays")
    if len(strata) == 0:
        raise ValueError("cannot summarize zero proteins")

    sizes = np.bincount(strata)
    report: dict[str, object] = {
        "population_size": int(len(strata)),
        "floor": int(min_size),
        "domain_mapping_version": DOMAIN_MAPPING_VERSION,
        "other_policy": DOMAIN_OTHER_POLICY,
        "domain_adjusted": domain_adjusted,
        "domain_counts": {
            domain: int((domains == domain).sum()) for domain in DOMAIN_CATEGORIES
        },
        **_stratum_size_summary(sizes, min_size),
    }
    if domain_adjusted:
        per_domain: dict[str, object] = {}
        for domain in DOMAIN_CATEGORIES:
            members = np.flatnonzero(domains == domain)
            if members.size == 0:
                continue
            domain_labels = np.unique(strata[members])
            if any(np.any(domains[strata == label] != domain) for label in domain_labels):
                raise ValueError(f"domain-adjusted stratum crosses domain boundary: {domain}")
            per_domain[domain] = {
                "population_size": int(members.size),
                **_stratum_size_summary(sizes[domain_labels], min_size),
            }
        report["per_domain"] = per_domain
    return report


def summarize_strata_pair(
    primary_strata: np.ndarray,
    sensitivity_strata: np.ndarray,
    domains: np.ndarray,
    *,
    use_taxonomy: bool,
    min_size: int,
) -> dict[str, object]:
    """Summarize two strategies over one resolved-domain discovery population."""
    # primary_strata, sensitivity_strata, domains: (m,)
    if np.any(domains == "Other"):
        raise AssertionError("unresolved-domain rows remain in the discovery population")
    primary_name = (
        "primary_domain_adjusted" if use_taxonomy else "primary_length_density_only"
    )
    primary_report = summarize_strata(
        primary_strata,
        domains,
        min_size,
        domain_adjusted=use_taxonomy,
    )
    sensitivity_report = summarize_strata(
        sensitivity_strata,
        domains,
        min_size,
        domain_adjusted=False,
    )
    reports = {
        primary_name: primary_report,
        "sensitivity_length_density_only": sensitivity_report,
    }
    for name, report in reports.items():
        if report["population_size"] != len(domains):
            raise AssertionError(f"{name} does not retain the shared discovery population")
        if report["count_below_floor"] != 0:
            raise AssertionError(f"{name} contains a stratum below the declared floor")
    return reports


def build_strata(
    length: np.ndarray,
    n_annotations: np.ndarray,
    domains: np.ndarray | None = None,
    min_size: int = MIN_STRATUM_SIZE,
    tie_breaker: np.ndarray | None = None,
) -> np.ndarray:
    """Return a stratum label per protein, with every stratum guaranteed at least `min_size`.

    Length alone is not enough. Annotation count rises with length but also independently with how
    well studied a protein is, so a narrow length bin can still span a ten-fold range of annotation
    density, and a feature that merely prefers well-annotated proteins would look like a real
    association. Taxonomy matters too, because some protein biology is genuinely clade-specific and
    the defensible claim is association beyond clade rather than instead of it.

    Crossing three quantile grids produced mostly-empty cells. Sorting on both covariates at once
    and cutting into blocks does not work either: a lexicographic order has a primary key, so a
    block is narrow in length and spans the full range of annotation density, and the density probe
    catches it immediately.

    The construction is therefore nested. Inside each taxonomic domain, proteins are sorted by
    length and cut into roughly `sqrt(n / min_size)` length groups; inside each length group they
    are sorted by annotation count and cut into blocks of at least `min_size`. Every block is then
    narrow in length and, at that length, narrow in density, while still meeting the size floor.
    """
    # length, n_annotations: (m,); domains: (m,) prevalidated labels or None; tie_breaker: (m,) or None
    if min_size < 1:
        raise ValueError("min_size must be positive")
    if length.ndim != 1 or n_annotations.ndim != 1 or len(length) != len(n_annotations):
        raise ValueError("length and n_annotations must be aligned one-dimensional arrays")
    if len(length) == 0:
        raise ValueError("cannot build strata for zero proteins")
    if tie_breaker is None:
        tie_breaker = np.arange(len(length), dtype=np.int64)
    elif tie_breaker.ndim != 1 or len(tie_breaker) != len(length):
        raise ValueError("tie_breaker must be a one-dimensional array aligned to length")

    domain_adjusted = domains is not None
    if domains is None:
        domain = np.full(len(length), "All", dtype=object)
    else:
        if domains.ndim != 1 or len(domains) != len(length):
            raise ValueError("domains must be a one-dimensional array aligned to length")
        invalid_domains = sorted(set(domains) - set(DOMAIN_CATEGORIES))
        if invalid_domains:
            raise ValueError(
                f"domains contain values outside the predeclared mapping: {invalid_domains}"
            )
        domain = domains
    label = np.full(len(length), -1, dtype=np.int64)  # (m,)
    next_label = 0

    domain_order = DOMAIN_CATEGORIES if domain_adjusted else ("All",)
    for value in domain_order:
        members = np.flatnonzero(domain == value)  # (m_d,)
        if members.size == 0:
            continue
        if members.size < min_size:
            raise ValueError(
                f"domain {value!r} has {members.size} proteins, below the stratum floor {min_size}"
            )
        total_blocks = max(1, len(members) // max(min_size, 1))
        n_length_groups = max(1, int(round(total_blocks**0.5)))

        by_length = members[
            np.lexsort((tie_breaker[members], length[members]))
        ]  # (m_d,)
        for group in np.array_split(by_length, n_length_groups):
            if group.size == 0:
                continue
            by_density = group[
                np.lexsort((tie_breaker[group], n_annotations[group]))
            ]  # (m_g,)
            n_density_blocks = max(1, len(by_density) // max(min_size, 1))
            for block in np.array_split(by_density, n_density_blocks):
                if block.size == 0:
                    continue
                label[block] = next_label
                next_label += 1

    if (label < 0).any():
        raise ValueError("a protein was not assigned to a stratum")
    realized_sizes = np.bincount(label)
    if (realized_sizes < min_size).any():
        failed = {
            int(index): int(size)
            for index, size in enumerate(realized_sizes)
            if size < min_size
        }
        raise ValueError(f"realized strata below the floor {min_size}: {failed}")
    return label  # (m,)


def length_strata(length: np.ndarray, n_strata: int = DEFAULT_LENGTH_BINS) -> np.ndarray:
    """Return a stratum label per protein from length quantiles alone."""
    # length: (m,)
    return _quantile_bin(length, n_strata)  # (m,)


def confound_probe(
    pooled: np.ndarray,
    positions: np.ndarray,
    activation_rows: np.ndarray,
    strata: np.ndarray,
    length: np.ndarray,
    n_annotations: np.ndarray,
    n_features_sampled: int = 2048,
    seed: int = DEFAULT_SEED,
) -> dict[str, float]:
    """Measure how strongly the stratified statistic still tracks length and annotation count.

    Binning is assumed to remove a confound; this checks it. Two pseudo-terms are constructed, one
    marking the longest quartile of proteins and one marking the most heavily annotated quartile,
    and the real statistic is run against them. A pseudo-term that still scores like a real term
    means the stratification did not do its job.
    """
    # pooled: (n_all, c); positions: (m,) rows of the aligned frame; activation_rows: (n,) map into pooled
    # strata: (m,); length, n_annotations: (n,)
    generator = np.random.default_rng(seed)
    sampled = np.sort(
        generator.choice(pooled.shape[1], size=min(n_features_sampled, pooled.shape[1]), replace=False)
    )  # (c_sampled,)
    activation = np.asarray(pooled[activation_rows[positions]][:, sampled], dtype=np.float32)

    subset_length = length[positions]  # (m,)
    subset_annotations = n_annotations[positions]  # (m,)
    pseudo = np.stack(
        [
            subset_length >= np.quantile(subset_length, 0.75),
            subset_annotations >= np.quantile(subset_annotations, 0.75),
        ]
    ).astype(np.float32)  # (2, m)

    term_matrix = torch.from_numpy(pseudo).to_sparse_csr()
    global_association_result = global_association(activation, term_matrix, feature_chunk=256, strata=strata, min_positive=1)

    return {
        "length_probe_max_abs_z": float(np.abs(global_association_result.z_score[:, 0]).max()),
        "length_probe_median_abs_z": float(np.median(np.abs(global_association_result.z_score[:, 0]))),
        "length_probe_max_abs_auroc_gap": float(np.abs(global_association_result.auroc[:, 0].astype(np.float32) - 0.5).max()),
        "density_probe_max_abs_z": float(np.abs(global_association_result.z_score[:, 1]).max()),
        "density_probe_median_abs_z": float(np.median(np.abs(global_association_result.z_score[:, 1]))),
        "density_probe_max_abs_auroc_gap": float(np.abs(global_association_result.auroc[:, 1].astype(np.float32) - 0.5).max()),
    }


def cluster_block_null(
    pooled: np.ndarray,
    token_lists: pd.Series,
    positions: np.ndarray,
    activation_rows: np.ndarray,
    strata: np.ndarray,
    n_terms: int,
    n_features_sampled: int = 0,
    seed: int = DEFAULT_SEED,
    n_permutations: int = DEFAULT_PERMUTATIONS,
) -> np.ndarray:
    """Return the null distribution of the best-term z under stratified label permutation.

    This permutes individual discovery rows within strata. It is a **cluster-block** permutation
    only when discovery holds exactly one representative per cluster, which is the primary setting:
    there, one row is one cluster, so shuffling rows shuffles whole clusters and the null inherits
    the same homology structure as the observed statistic.

    With more than one member per cluster that equivalence breaks. Homologous members move
    independently under the shuffle, so the null does **not** reproduce within-cluster correlation
    and the resulting threshold cannot be read as correcting for it. `run_analysis` records
    `null_is_cluster_block` so a run that violates the assumption is identifiable from its summary
    rather than from this docstring.

    Restricting the shuffle to strata keeps the length and density composition of every label
    fixed, which matters because both activation counts and annotation counts grow with length.
    """
    # The threshold is a maximum over features, so the null has to be drawn from the same family.
    # Sampling a subset and applying its maximum understates the threshold by exactly what the
    # unsampled features would have contributed, so the default is every feature. One permutation
    # gives one draw of the maximum statistic, which cannot calibrate a tail, so several
    # deterministic permutations are run and their best-term z values are pooled.
    # pooled: (n_all, c); positions: (m,) rows of the aligned frame; activation_rows: (n,) map into pooled
    # strata: (m,)
    generator = np.random.default_rng(seed)
    n_features = pooled.shape[1]
    sampled = (
        np.arange(n_features)
        if n_features_sampled <= 0 or n_features_sampled >= n_features
        else np.sort(generator.choice(n_features, size=n_features_sampled, replace=False))
    )  # (c_sampled,)
    activation = np.asarray(pooled[activation_rows[positions]][:, sampled], dtype=np.float32)

    draws: list[np.ndarray] = []
    for index in range(max(1, n_permutations)):
        permuted = stratified_permutation(
            positions, strata, np.random.default_rng(seed + index)
        )
        term_matrix = build_term_matrix(token_lists, n_terms, permuted)
        null = global_association(activation, term_matrix, feature_chunk=256, strata=strata)
        draws.append(null.z_score.max(axis=1))  # (c_sampled,)
        print(
            f"  null permutation {index + 1}/{n_permutations}: max z {draws[-1].max():.2f}",
            flush=True,
        )

    return np.concatenate(draws)  # (c_sampled * n_permutations,)


@dataclass(slots=True)
class AssociationArm:
    """Observed association, calibrated null, and confound probe for one stratum design."""

    association: GlobalAssociation
    null_z: np.ndarray
    confound_probe: dict[str, float]


def run_association_arm(
    pooled: np.ndarray,
    token_lists: pd.Series,
    positions: np.ndarray,
    activation_rows: np.ndarray,
    strata: np.ndarray,
    length: np.ndarray,
    n_annotations: np.ndarray,
    term_matrix: torch.Tensor,
    n_terms: int,
    n_permutations: int = DEFAULT_PERMUTATIONS,
) -> AssociationArm:
    """Run every stratum-dependent calculation for one explicitly labeled analysis arm."""
    # pooled: (n_all, c); positions: (m,) rows of the aligned frame; activation_rows: (n,) map into pooled
    # strata: (m,); length, n_annotations: (n,); term_matrix: (t, m) sparse
    null_z = cluster_block_null(
        pooled,
        token_lists,
        positions,
        activation_rows,
        strata,
        n_terms,
        n_permutations=n_permutations,
    )
    probe = confound_probe(
        pooled,
        positions,
        activation_rows,
        strata,
        length,
        n_annotations,
    )
    association = global_association(
        np.asarray(pooled[activation_rows[positions]], dtype=np.float32),
        term_matrix,
        feature_chunk=256,
        strata=strata,
    )
    return AssociationArm(association=association, null_z=null_z, confound_probe=probe)


def run_local_analysis(
    run: ExtractionRun,
    aligned: pd.DataFrame,
    positions: np.ndarray,
    terms: pd.DataFrame,
    n_terms: int,
    min_pairs: int = 20,
    min_z: float = 4.0,
    randomize_positions: bool = False,
    seed: int = DEFAULT_SEED,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Run the protein-stratified local test.

    Returns the feature-term pairs above `min_z` together with unfiltered summary statistics over
    every usable pair. Reporting only the selected pairs would overstate enrichment, because
    selecting on the statistic guarantees a median above one.

    Setting `randomize_positions` shuffles each span to a random start inside its own protein while
    keeping its length. That is the positional null: it removes any real localization but preserves
    span lengths, span counts, protein identity, and the fact that SAE activity is not uniform
    along a sequence.
    """
    # positions: (m,) rows of the aligned frame
    generator = np.random.default_rng(seed)
    span_protein: list[np.ndarray] = []
    span_term: list[np.ndarray] = []
    span_start: list[np.ndarray] = []
    span_end: list[np.ndarray] = []

    activation_rows = aligned["activation_row"].to_numpy()  # (n,)
    for position in positions:
        token_ids = np.asarray(aligned["local_term_ids"].iat[int(position)], dtype=np.int64)
        if token_ids.size == 0:
            continue
        starts = np.asarray(aligned["local_starts"].iat[int(position)], dtype=np.int64)
        ends = np.asarray(aligned["local_ends"].iat[int(position)], dtype=np.int64)
        row = int(activation_rows[position])
        n_residues = int(run.protein_index["n_residues"].iat[row])

        keep = (token_ids >= 0) & (token_ids < n_terms) & (starts >= 1) & (ends <= n_residues) & (ends >= starts)
        if not keep.any():
            continue

        kept_starts = starts[keep]
        kept_ends = ends[keep]
        if randomize_positions:
            # Randomize the merged geometry, not the raw one, so the null and the observed data have
            # the same span-length composition after merging.
            _, kept_terms, kept_starts, kept_ends = merge_spans(
                np.zeros(int(keep.sum()), dtype=np.int64), token_ids[keep], kept_starts, kept_ends
            )
            span_lengths = kept_ends - kept_starts + 1  # (s_p,)
            highest_start = np.maximum(1, n_residues - span_lengths + 1)  # (s_p,)
            kept_starts = generator.integers(1, highest_start + 1)
            kept_ends = kept_starts + span_lengths - 1
        else:
            kept_terms = token_ids[keep]

        span_protein.append(np.full(len(kept_starts), row, dtype=np.int64))
        span_term.append(kept_terms)
        span_start.append(kept_starts)
        span_end.append(kept_ends)

    if not span_protein:
        return pd.DataFrame(), {}

    # Local terms occupy a small, high range of the shared token space. The statistic allocates a
    # dense `(c, t)` matrix, so passing the full token count would reserve tens of gigabytes of
    # columns that can never be nonzero. Remap to the local terms actually present.
    all_terms = np.concatenate(span_term)
    present_terms = np.unique(all_terms)  # (t_local,)
    dense_of_token = {int(token): index for index, token in enumerate(present_terms)}
    dense_terms = np.array([dense_of_token[int(t)] for t in all_terms], dtype=np.int64)

    local_association_result = local_association(
        residue_features=run.residue_features(),
        residue_offset=run.protein_index["residue_offset"].to_numpy(),
        n_residues=run.protein_index["n_residues"].to_numpy().astype(np.int64),
        pooled_count=run.pooled("count"),
        span_protein=np.concatenate(span_protein),
        span_term=dense_terms,
        span_start=np.concatenate(span_start),
        span_end=np.concatenate(span_end),
        n_local_terms=len(present_terms),
        n_features=run.n_features,
    )

    z_score = local_association_result.z_score  # (c, t)
    enrichment = local_association_result.enrichment  # (c, t)
    usable = (local_association_result.n_strata >= min_pairs) & (local_association_result.expected > 0)  # (c, t)

    statistics = {
        "n_usable_pairs": float(usable.sum()),
        "unfiltered_median_enrichment": float(np.median(enrichment[usable])) if usable.any() else float("nan"),
        "unfiltered_median_z": float(np.median(z_score[usable])) if usable.any() else float("nan"),
        "unfiltered_p95_z": float(np.percentile(z_score[usable], 95)) if usable.any() else float("nan"),
        "max_z": float(z_score[usable].max()) if usable.any() else float("nan"),
        "fraction_above_min_z": float((z_score[usable] > min_z).mean()) if usable.any() else float("nan"),
    }

    feature_index, term_index = np.nonzero(usable & (z_score > min_z))
    if feature_index.size == 0:
        return pd.DataFrame(), statistics

    aspect_by_token = dict(zip(terms["token"].astype(int), terms["aspect"].astype(str), strict=False))
    label_by_token = dict(zip(terms["token"].astype(int), terms["label"].astype(str), strict=False))
    frame = pd.DataFrame(
        {
            "feature_id": feature_index,
            "term": term_index,
            "z_score": z_score[feature_index, term_index],
            "enrichment": enrichment[feature_index, term_index],
            "observed": local_association_result.observed[feature_index, term_index],
            "expected": local_association_result.expected[feature_index, term_index],
            "n_strata": local_association_result.n_strata[feature_index, term_index],
        }
    )
    frame["term"] = present_terms[frame["term"].to_numpy()]
    frame["aspect"] = [aspect_by_token.get(int(t), "") for t in frame["term"]]
    frame["label"] = [label_by_token.get(int(t), "") for t in frame["term"]]
    statistics["n_local_terms_present"] = float(len(present_terms))
    return frame.sort_values("z_score", ascending=False).reset_index(drop=True), statistics


def run_analysis(
    run_dir: str,
    protein_table: str,
    term_table: str,
    output_dir: str,
    pooling: str = "max",
    feature_table_path: str = "",
    min_auroc: float = 0.6,
    min_support: int = 50,
    rank_by: str = "auroc",
    exemplar_exclusion: str = "cluster",
    representative_rule: str = "mmseqs",
    n_permutations: int = DEFAULT_PERMUTATIONS,
    agent_label_table: str = "",
    skip_local: bool = False,
    overwrite: bool = False,
    excluded_aspects: tuple[str, ...] = (),
    members_per_cluster: int = 1,
    min_stratum_size: int = MIN_STRATUM_SIZE,
    use_taxonomy: bool = True,
    base_model_revision: str = "",
    sae_revision: str = "",
    feature_table_revision: str = "",
    agent_label_source_revision: str = "",
) -> dict[str, object]:
    """Execute discovery, held-out evaluation, the local test, and the Biohub comparison."""
    started = time.perf_counter()
    if min_stratum_size < 1:
        raise ValueError("--min_stratum_size must be positive")
    if not feature_table_path.strip():
        raise ValueError("--feature_table_path must name an explicit local file")
    output = Path(output_dir)
    if output.exists() and any(output.iterdir()) and not overwrite:
        raise FileExistsError(
            f"{output} is not empty. Analysis writes to a fresh directory so that a partial or "
            "concurrent earlier run cannot leave artifacts that look like this one's. Pass "
            "--overwrite only when you intend to discard what is there."
        )

    run_directory = Path(run_dir).expanduser().resolve()
    protein_table_file = require_file(Path(protein_table), "protein table")
    term_table_file = require_file(Path(term_table), "term table")
    feature_table_file = require_file(Path(feature_table_path), "feature table")
    agent_label_file = (
        require_file(Path(agent_label_table), "agent label table")
        if agent_label_table.strip()
        else None
    )
    external_provenance_record, extraction_source_manifests = external_provenance(
        extraction_manifest=run_directory / "manifest.json",
        base_model_revision=base_model_revision,
        sae_revision=sae_revision,
        feature_table_revision=feature_table_revision,
        agent_label_source_revision=agent_label_source_revision,
        agent_labels_used=agent_label_file is not None,
    )

    def current_input_inventory() -> dict[str, object]:
        return analysis_input_inventory(
            run_directory=run_directory,
            protein_table=protein_table_file,
            term_table=term_table_file,
            feature_table=feature_table_file,
            agent_label_table=agent_label_file,
            pooling=pooling,
            skip_local=skip_local,
            extraction_source_manifests=extraction_source_manifests,
        )

    def current_code_inventory() -> dict[str, str]:
        return {
            module.name: _digest(module)
            for module in sorted(Path(__file__).parent.glob("*.py"))
        }

    initial_input_inventory = current_input_inventory()
    initial_code_inventory = current_code_inventory()
    output.mkdir(parents=True, exist_ok=True)

    run = load_run(str(run_directory))
    # `.schema` is the physical parquet schema, whose names include nested paths such as
    # `annotations.list.element`. `.schema_arrow` gives the top-level column names.
    available = set(pq.ParquetFile(protein_table_file).schema_arrow.names)
    wanted = [
        "accession", "annotations", "local_term_ids", "local_starts", "local_ends",
        "cluster_id", "split", "coarse_lineage", "lineage", "lineage_names",
        "lineage_taxon_ids",
    ]
    proteins = pd.read_parquet(
        protein_table_file, columns=[c for c in wanted if c in available]
    )
    terms = pd.read_parquet(term_table_file)
    n_terms = int(terms["token"].max()) + 1

    # A vocabulary revision is evaluated by withholding its removed aspects from assignment.
    # The association is computed over every term either way, so the two runs stay comparable
    # term by term and the difference is attributable to the revision alone.
    term_mask: np.ndarray | None = None  # (t,)
    if excluded_aspects:
        term_mask = np.ones(n_terms, dtype=bool)
        removed = terms.loc[terms["aspect"].isin(excluded_aspects), "token"].astype(int)
        term_mask[removed.to_numpy()] = False
        print(f"withholding {len(removed):,} terms from {sorted(excluded_aspects)}", flush=True)

    aligned = align_proteins(run, proteins)
    pooled_all = run.pooled(pooling)  # (n_all, c)
    activation_rows = aligned["activation_row"].to_numpy()  # (n,)
    length = run.protein_index["n_residues"].to_numpy()[activation_rows]  # (n,)

    feature_table = load_feature_table(str(feature_table_file))
    reference = reference_accessions(feature_table)
    exemplar_accessions = set(reference["accession"])
    is_exemplar = aligned["accession"].isin(exemplar_accessions).to_numpy()  # (n,)
    exemplar_clusters = set(aligned.loc[is_exemplar, "cluster_id"])
    if exemplar_exclusion == "cluster":
        # Strict: a homolog of an exemplar could carry the same annotations, so drop the whole
        # cluster. This is the primary setting and it costs a large share of the discovery set.
        in_exemplar_cluster = aligned["cluster_id"].isin(exemplar_clusters).to_numpy()  # (n,)
    else:
        # Relaxed: drop only the exemplars themselves. Reported as a power check, never as the
        # headline, because homologs of exemplars remain in discovery.
        in_exemplar_cluster = is_exemplar  # (n,)

    # Three partitions, mutually disjoint by construction because splits are assigned to whole
    # clusters. Discovery fits the assignment, validation picks the rule, test is touched once.
    split = aligned["split"].to_numpy()  # (n,)
    usable = ~in_exemplar_cluster  # (n,)
    domain_mapping = resolve_domain_metadata(aligned)
    aligned_accessions = aligned["accession"].astype(str).to_numpy()
    discovery_candidate_mask, discovery_exclusion = exclude_unresolved_discovery_candidates(
        usable & (split == "train"),
        domain_mapping.domains,
        aligned_accessions,
    )
    discovery_positions = cluster_representatives(
        aligned,
        discovery_candidate_mask,
        rule=representative_rule,
        members_per_cluster=members_per_cluster,
    )  # (n_discovery,)
    validation_positions = np.flatnonzero(usable & (split == "validation"))  # (n_val,)
    evaluation_positions = np.flatnonzero(usable & (split == "test"))  # (n_eval,)

    if np.any(domain_mapping.domains[discovery_positions] == "Other"):
        raise AssertionError("an unresolved-domain row silently remained in discovery")
    discovery_clusters = set(aligned["cluster_id"].to_numpy()[discovery_positions])
    validation_clusters = set(aligned["cluster_id"].to_numpy()[validation_positions])
    evaluation_clusters = set(aligned["cluster_id"].to_numpy()[evaluation_positions])
    assert not discovery_clusters & validation_clusters, "discovery and validation share a cluster"
    assert not discovery_clusters & evaluation_clusters, "discovery and test share a cluster"
    assert not validation_clusters & evaluation_clusters, "validation and test share a cluster"
    assert not discovery_clusters & exemplar_clusters, "discovery contains an exemplar cluster"

    print(
        f"aligned {len(aligned):,} | exemplars {int(is_exemplar.sum()):,} | "
        f"exemplar clusters {len(exemplar_clusters):,} | "
        f"discovery {len(discovery_positions):,} | unresolved discovery exclusions "
        f"{discovery_exclusion['count']:,} | validation {len(validation_positions):,} | "
        f"test {len(evaluation_positions):,} | terms {n_terms:,}",
        flush=True,
    )

    n_annotations = aligned["annotations"].map(len).to_numpy()  # (n,)
    discovery_domains = domain_mapping.domains[discovery_positions]
    discovery_accessions = aligned_accessions[discovery_positions]
    discovery_strata = build_strata(
        length[discovery_positions],
        n_annotations[discovery_positions],
        discovery_domains if use_taxonomy else None,
        min_size=min_stratum_size,
        tie_breaker=discovery_accessions,
    )  # (n_discovery,)
    sensitivity_strata = build_strata(
        length[discovery_positions],
        n_annotations[discovery_positions],
        domains=None,
        min_size=min_stratum_size,
        tie_breaker=discovery_accessions,
    )  # (n_discovery,)
    strata_report = {
        "domain_mapping": summarize_domain_mapping(domain_mapping),
        "discovery_exclusion": discovery_exclusion,
        "min_stratum_size": min_stratum_size,
        **summarize_strata_pair(
            discovery_strata,
            sensitivity_strata,
            discovery_domains,
            use_taxonomy=use_taxonomy,
            min_size=min_stratum_size,
        ),
    }
    print("strata:", json.dumps(strict_json(strata_report)), flush=True)
    term_matrix = build_term_matrix(aligned["annotations"], n_terms, discovery_positions)
    association = global_association(
        np.asarray(pooled_all[activation_rows[discovery_positions]], dtype=np.float32),
        term_matrix,
        feature_chunk=256,
        strata=discovery_strata,
    )
    np.save(output / "global_auroc.npy", association.auroc)
    # Saved so that an ablation or a re-threshold can reconstruct eligibility later without
    # repeating the association. Without them, a post-hoc analysis can only filter on AUROC, and a
    # term carried by two proteins reaches AUROC 1.0 for free.
    np.save(output / "global_z.npy", association.z_score.astype(np.float16))
    np.save(output / "term_support.npy", association.n_positive.astype(np.int32))

    # The threshold is the larger of the asymptotic Benjamini-Hochberg cut and the largest best-term
    # z produced by the permutation null. The null cut is the operative one whenever the normal
    # approximation is optimistic, which the local test showed it can be in this regime.
    null_z = cluster_block_null(
        pooled_all,
        aligned["annotations"],
        discovery_positions,
        activation_rows,
        discovery_strata,
        n_terms,
        n_permutations=n_permutations,
    )
    np.save(output / "null_z.npy", null_z)
    probe = confound_probe(
        pooled_all,
        discovery_positions,
        activation_rows,
        discovery_strata,
        length,
        n_annotations,
    )
    print("confound probe:", json.dumps(probe), flush=True)
    # The probe bounds how much of an assignment the confound could explain. An assigned term whose
    # AUROC exceeds the largest AUROC any pseudo-term achieves cannot be a repackaged length or
    # annotation-density effect.
    confound_ceiling = 0.5 + max(
        probe["length_probe_max_abs_auroc_gap"], probe["density_probe_max_abs_auroc_gap"]
    )
    bh_threshold = benjamini_hochberg_threshold(association.z_score, alpha=0.01)
    empirical_threshold = float(null_z.max()) if null_z.size else 0.0
    z_threshold = max(bh_threshold, empirical_threshold)
    # The ranking rule and support floor are chosen on validation, never on test. Every candidate
    # is scored on validation proteins whose clusters discovery never saw, the winner is frozen, and
    # test is evaluated exactly once against that frozen choice.
    arguments_min_support = min_support
    candidates = [
        (rule, support)
        for rule in ("auroc", "z")
        for support in (min_support, max(10, min_support // 2), min_support * 2)
    ]
    selection_rows: list[dict[str, float | str]] = []
    best_key: tuple[str, int] | None = None
    best_score = -np.inf

    for rule, support in candidates:
        candidate_term, _, _ = assign_terms(
            association, min_auroc, z_threshold, min_support=support, rank_by=rule,
            term_mask=term_mask,
        )
        scored = evaluate_held_out(
            pooled_all, aligned["annotations"], validation_positions, activation_rows,
            candidate_term, n_terms,
        )
        n_assigned_candidate = int((candidate_term >= 0).sum())
        score = float(scored["auroc"].median()) if len(scored) else float("-inf")
        selection_rows.append(
            {
                "rank_by": rule,
                "min_support": support,
                "n_assigned": n_assigned_candidate,
                "validation_median_auroc": score,
                "validation_n_scored": len(scored),
            }
        )
        if score > best_score:
            best_score, best_key = score, (rule, support)

    selection = pd.DataFrame(selection_rows)
    selection.to_parquet(output / "rule_selection.parquet", index=False)
    rank_by, min_support = best_key if best_key else (rank_by, min_support)
    print(f"validation selected rank_by={rank_by} min_support={min_support}", flush=True)

    assigned_term, assigned_z, assigned_auroc = assign_terms(
        association, min_auroc, z_threshold, min_support=min_support, rank_by=rank_by,
        term_mask=term_mask,
    )
    by_z_term, _, by_z_auroc = assign_terms(
        association, min_auroc, z_threshold, min_support=min_support, rank_by="z",
        term_mask=term_mask,
    )

    label_by_token = dict(zip(terms["token"].astype(int), terms["label"].astype(str), strict=False))
    aspect_by_token = dict(zip(terms["token"].astype(int), terms["aspect"].astype(str), strict=False))
    primary_variant = (
        "domain_adjusted_primary" if use_taxonomy else "length_density_only_sensitivity"
    )
    assignment = pd.DataFrame(
        {
            "analysis_variant": primary_variant,
            "feature_id": np.arange(len(assigned_term)),
            "term": assigned_term,
            "z_score": assigned_z,
            "auroc": assigned_auroc,
            "label": [label_by_token.get(int(t), "") for t in assigned_term],
            "aspect": [aspect_by_token.get(int(t), "") for t in assigned_term],
            "term_by_z": by_z_term,
            "label_by_z": [label_by_token.get(int(t), "") for t in by_z_term],
            "auroc_by_z": by_z_auroc,
            "n_carriers": [
                int(association.n_positive[int(t)]) if t >= 0 else 0 for t in assigned_term
            ],
        }
    )
    assignment.to_parquet(output / "feature_assignment.parquet", index=False)

    # Which aspects actually describe features. For each feature, the best eligible term inside each
    # aspect, so an aspect that never supplies a winner can be identified as carrying structure that
    # nothing downstream uses. This is the measurable form of "does this aspect earn its place".
    eligible_mask = (
        (association.z_score >= z_threshold)
        & (association.auroc.astype(np.float32) >= min_auroc)
        & (association.n_positive >= min_support)[None, :]
    )  # (c, t)
    aspect_rows: list[dict[str, object]] = []
    for aspect in sorted(set(aspect_by_token.values())):
        columns = np.array(
            [token for token, name in aspect_by_token.items() if name == aspect and token < n_terms],
            dtype=np.int64,
        )
        if columns.size == 0:
            continue
        block = np.where(
            eligible_mask[:, columns], association.auroc[:, columns].astype(np.float32), -np.inf
        )  # (c, t_aspect)
        best = block.max(axis=1)  # (c,)
        aspect_rows.append(
            {
                "aspect": aspect,
                "n_terms": int(columns.size),
                "n_features_with_eligible_term": int(np.isfinite(best).sum()),
                "n_features_won": int(
                    ((assignment["aspect"] == aspect) & (assignment["term"] >= 0)).sum()
                ),
                "median_best_auroc": float(np.median(best[np.isfinite(best)])) if np.isfinite(best).any() else float("nan"),
            }
        )
    pd.DataFrame(aspect_rows).to_parquet(output / "aspect_value.parquet", index=False)
    print(
        f"assigned {int((assigned_term >= 0).sum()):,} features | "
        f"threshold {z_threshold:.2f} (BH {bh_threshold:.2f}, null max {empirical_threshold:.2f})",
        flush=True,
    )

    held_out = evaluate_held_out(
        pooled_all, aligned["annotations"], evaluation_positions, activation_rows, assigned_term, n_terms
    )
    held_out.to_parquet(output / "held_out_metrics.parquet", index=False)

    # The default domain-adjusted run executes the required length-and-density-only sensitivity on
    # the same discovery and held-out populations. Its permutation threshold is recalibrated for its
    # own strata, while the validation-selected rank rule and support floor remain frozen so the
    # comparison isolates domain adjustment. A --no_taxonomy run is already this sensitivity and is
    # labeled accordingly without duplicating the full calculation.
    del eligible_mask, association
    if use_taxonomy:
        sensitivity_arm = run_association_arm(
            pooled_all,
            aligned["annotations"],
            discovery_positions,
            activation_rows,
            sensitivity_strata,
            length,
            n_annotations,
            term_matrix,
            n_terms,
            n_permutations=n_permutations,
        )
        sensitivity_null_z = sensitivity_arm.null_z
        sensitivity_probe = sensitivity_arm.confound_probe
        sensitivity_association = sensitivity_arm.association
        np.save(
            output / "sensitivity_length_density_only_global_auroc.npy",
            sensitivity_association.auroc,
        )
        np.save(
            output / "sensitivity_length_density_only_global_z.npy",
            sensitivity_association.z_score.astype(np.float16),
        )
        np.save(output / "sensitivity_length_density_only_null_z.npy", sensitivity_null_z)
        sensitivity_bh_threshold = benjamini_hochberg_threshold(
            sensitivity_association.z_score,
            alpha=0.01,
        )
        sensitivity_empirical_threshold = (
            float(sensitivity_null_z.max()) if sensitivity_null_z.size else 0.0
        )
        sensitivity_z_threshold = max(
            sensitivity_bh_threshold,
            sensitivity_empirical_threshold,
        )
        sensitivity_term, sensitivity_z, sensitivity_auroc = assign_terms(
            sensitivity_association,
            min_auroc,
            sensitivity_z_threshold,
            min_support=min_support,
            rank_by=rank_by,
            term_mask=term_mask,
        )
        sensitivity_by_z_term, _, sensitivity_by_z_auroc = assign_terms(
            sensitivity_association,
            min_auroc,
            sensitivity_z_threshold,
            min_support=min_support,
            rank_by="z",
            term_mask=term_mask,
        )
        sensitivity_assignment = pd.DataFrame(
            {
                "analysis_variant": "length_density_only_sensitivity",
                "feature_id": np.arange(len(sensitivity_term)),
                "term": sensitivity_term,
                "z_score": sensitivity_z,
                "auroc": sensitivity_auroc,
                "label": [label_by_token.get(int(term), "") for term in sensitivity_term],
                "aspect": [aspect_by_token.get(int(term), "") for term in sensitivity_term],
                "term_by_z": sensitivity_by_z_term,
                "label_by_z": [
                    label_by_token.get(int(term), "") for term in sensitivity_by_z_term
                ],
                "auroc_by_z": sensitivity_by_z_auroc,
                "n_carriers": [
                    int(sensitivity_association.n_positive[int(term)]) if term >= 0 else 0
                    for term in sensitivity_term
                ],
            }
        )
        sensitivity_assignment.to_parquet(
            output / "sensitivity_length_density_only_feature_assignment.parquet",
            index=False,
        )
        sensitivity_held_out = evaluate_held_out(
            pooled_all,
            aligned["annotations"],
            evaluation_positions,
            activation_rows,
            sensitivity_term,
            n_terms,
        )
        sensitivity_held_out.insert(
            0,
            "analysis_variant",
            "length_density_only_sensitivity",
        )
        sensitivity_held_out.to_parquet(
            output / "sensitivity_length_density_only_held_out_metrics.parquet",
            index=False,
        )
        primary_assigned = assigned_term >= 0
        sensitivity_assigned = sensitivity_term >= 0
        sensitivity_summary: dict[str, object] = {
            "analysis_variant": "length_density_only_sensitivity",
            "executed_as_primary": False,
            "comparison_rule": (
                "same population, labels, validation-selected rank rule, and support floor"
            ),
            "stratification": strata_report["sensitivity_length_density_only"],
            "n_assigned": int(sensitivity_assigned.sum()),
            "n_distinct_assigned_terms": int(
                len(set(sensitivity_term[sensitivity_assigned].tolist()))
            ),
            "z_threshold": float(sensitivity_z_threshold),
            "z_threshold_bh01": float(sensitivity_bh_threshold),
            "z_threshold_null_max": float(sensitivity_empirical_threshold),
            "median_assigned_auroc": (
                float(np.nanmedian(sensitivity_auroc[sensitivity_assigned]))
                if sensitivity_assigned.any()
                else float("nan")
            ),
            "held_out_median_auroc": (
                float(sensitivity_held_out["auroc"].median())
                if len(sensitivity_held_out)
                else float("nan")
            ),
            "fraction_primary_assignments_unchanged": (
                float(
                    (
                        sensitivity_term[primary_assigned]
                        == assigned_term[primary_assigned]
                    ).mean()
                )
                if primary_assigned.any()
                else float("nan")
            ),
            "confound_probe": sensitivity_probe,
        }
        del sensitivity_association, sensitivity_arm
    else:
        primary_assigned = assigned_term >= 0
        sensitivity_summary = {
            "analysis_variant": "length_density_only_sensitivity",
            "executed_as_primary": True,
            "comparison_rule": "this run omits domain adjustment by explicit request",
            "stratification": strata_report["sensitivity_length_density_only"],
            "n_assigned": int(primary_assigned.sum()),
            "n_distinct_assigned_terms": int(
                len(set(assigned_term[primary_assigned].tolist()))
            ),
            "z_threshold": float(z_threshold),
            "z_threshold_bh01": float(bh_threshold),
            "z_threshold_null_max": float(empirical_threshold),
            "median_assigned_auroc": (
                float(np.nanmedian(assigned_auroc[primary_assigned]))
                if primary_assigned.any()
                else float("nan")
            ),
            "held_out_median_auroc": (
                float(held_out["auroc"].median()) if len(held_out) else float("nan")
            ),
            "confound_probe": probe,
        }
    (output / "sensitivity_length_density_only_summary.json").write_text(
        json.dumps(strict_json(sensitivity_summary), indent=2, allow_nan=False)
    )

    # Cluster-bootstrap interval on the headline held-out statistic. Proteins inside a cluster are
    # homologous, so the cluster is the resampling unit; resampling proteins would understate the
    # interval by treating correlated observations as independent.
    # The bootstrap must resample exactly the features the point estimate summarizes. Including
    # features that `evaluate_held_out` skipped for having too few positives puts their unstable
    # AUROCs into the median and produces an interval that does not cover the point estimate.
    assigned_features = held_out["feature_id"].to_numpy() if len(held_out) else np.zeros(0, dtype=np.int64)
    bootstrap = {}
    if assigned_features.size and len(evaluation_positions):
        evaluation_rows = activation_rows[evaluation_positions]  # (n_eval,)
        activation_block = np.asarray(
            pooled_all[evaluation_rows][:, assigned_features], dtype=np.float32
        )  # (n_eval, c_assigned)
        membership_block = np.zeros_like(activation_block, dtype=bool)  # (n_eval, c_assigned)
        for offset, position in enumerate(evaluation_positions):
            carried = set(int(t) for t in aligned["annotations"].iat[int(position)])
            membership_block[offset] = [
                int(assigned_term[feature]) in carried for feature in assigned_features
            ]
        bootstrap = cluster_bootstrap_auroc(
            activation_block,
            membership_block,
            aligned["cluster_id"].to_numpy()[evaluation_positions],
        ).as_dict("held_out_bootstrap_median_auroc")

    # Base rates must come from the population the released exemplars were drawn from, which is
    # Swiss-Prot, not the extraction subset. The ESMC-6B subset deliberately contains every released
    # exemplar plus a seeded background, so a base rate estimated on it is ascertainment-biased.
    # Carrier sets need annotations only, never activations, so the full table is available here.
    assigned_tokens = set(int(t) for t in assigned_term if t >= 0)
    term_carriers: dict[int, set[str]] = {token: set() for token in assigned_tokens}
    for accession, tokens in zip(proteins["accession"], proteins["annotations"], strict=False):
        for token in set(int(t) for t in tokens) & assigned_tokens:
            term_carriers[token].add(accession)

    cluster_of_accession = dict(zip(proteins["accession"], proteins["cluster_id"], strict=False))
    concordance = term_concordance(
        assigned_term,
        term_carriers,
        reference,
        set(proteins["accession"]),
        unit_of=cluster_of_accession,
    )
    concordance_protein_level = term_concordance(
        assigned_term, term_carriers, reference, set(proteins["accession"])
    )

    # Sensitivity on the base rate only. The draw stays the released exemplars, since restricting
    # it to the background would remove every exemplar by construction, but each term's prevalence
    # is re-estimated on the seeded uniform background, which is a random Swiss-Prot sample rather
    # than an exemplar-enriched one.
    background = set(aligned.loc[~is_exemplar, "accession"])
    concordance_background = term_concordance(
        assigned_term,
        term_carriers,
        reference,
        set(proteins["accession"]),
        prevalence={
            token: len({cluster_of_accession.get(a, a) for a in carriers & background})
            / max(len({cluster_of_accession.get(a, a) for a in background}), 1)
            for token, carriers in term_carriers.items()
        },
        unit_of=cluster_of_accession,
    )
    concordance.frame.to_parquet(output / "concordance.parquet", index=False)

    accession_to_row = dict(zip(aligned["accession"], activation_rows, strict=False))
    fidelity = pipeline_fidelity(pooled_all, accession_to_row, reference)
    np.save(output / "fidelity_percentile.npy", fidelity.percentile_rank)

    recovery = category_recovery(
        {int(row.feature_id): row.aspect for row in assignment.itertuples() if row.term >= 0},
        feature_table,
    )
    recovery.to_parquet(output / "category_recovery.parquet", index=False)

    agent_labels: dict[int, str] = {}
    if agent_label_file is not None:
        labels_frame = pd.read_parquet(agent_label_file)
        agent_labels = dict(
            zip(labels_frame["feature_id"].astype(int), labels_frame["label"].astype(str), strict=False)
        )
    lexical = lexical_agreement(
        {int(row.feature_id): row.label for row in assignment.itertuples() if row.term >= 0},
        feature_table,
        agent_labels=agent_labels,
    )
    lexical.to_parquet(output / "lexical_agreement.parquet", index=False)

    local_frame = pd.DataFrame()
    local_statistics: dict[str, float] = {}
    local_null: dict[str, float] = {}
    if not skip_local:
        local_frame, local_statistics = run_local_analysis(
            run, aligned, discovery_positions, terms, n_terms
        )
        local_frame.to_parquet(output / "local_association.parquet", index=False)
        _, local_null = run_local_analysis(
            run, aligned, discovery_positions, terms, n_terms, randomize_positions=True
        )
        (output / "local_position_null.json").write_text(json.dumps(local_null, indent=2))

    assignment_carriers = assignment.loc[assignment["term"] >= 0, "n_carriers"].to_numpy()
    summary = {
        "analysis_variant": primary_variant,
        "n_features": float(len(assigned_term)),
        "n_assigned": float(int((assigned_term >= 0).sum())),
        # Held-out statistics summarize only features whose term has enough test carriers to
        # score, which is a smaller set than the assignment. Recording it keeps the two
        # denominators from being conflated downstream.
        "n_held_out_scored": float(len(held_out)),
        "n_discovery_proteins": float(len(discovery_positions)),
        "min_stratum_size": int(min_stratum_size),
        "discovery_exclusion": discovery_exclusion,
        "members_per_cluster": float(members_per_cluster),
        # The permutation shuffles discovery rows, which equals a whole-cluster shuffle only when
        # each row is its own cluster. Anything else leaves within-cluster correlation out of the
        # null, so the threshold from such a run is not homology-corrected and must not be compared
        # against a one-representative threshold as though it were.
        "null_is_cluster_block": float(
            len(discovery_clusters) == len(discovery_positions)
        ),
        "n_validation_proteins": float(len(validation_positions)),
        "n_discovery_clusters": float(len(discovery_clusters)),
        "n_validation_clusters": float(len(validation_clusters)),
        "n_test_clusters": float(len(evaluation_clusters)),
        "taxonomy_adjustment_active": float(use_taxonomy),
        "domain_mapping_mode": domain_mapping.mode,
        "domain_mapping_source_columns": list(domain_mapping.source_columns),
        "domain_mapping_version": DOMAIN_MAPPING_VERSION,
        "domain_other_policy": DOMAIN_OTHER_POLICY,
        "stratification": strata_report,
        "sensitivity_length_density_only": sensitivity_summary,
        "null_features_sampled": float(null_z.size),
        "n_permutations": float(n_permutations),
        "null_q999_z": float(np.quantile(null_z, 0.999)) if null_z.size else float("nan"),
        "null_q99_z": float(np.quantile(null_z, 0.99)) if null_z.size else float("nan"),
        "stratum_median_size": float(np.median(np.bincount(discovery_strata))),
        "stratum_min_size": float(np.bincount(discovery_strata).min()),
        "selected_rank_by_is_auroc": float(rank_by == "auroc"),
        "n_exemplar_clusters": float(len(exemplar_clusters)),
        "min_support": float(min_support),
        "pooling_is_length_normalized": float(pooling in ("max", "mean", "fraction")),
        "n_evaluation_proteins": float(len(evaluation_positions)),
        "n_terms": float(n_terms),
        "z_threshold": z_threshold,
        "z_threshold_bh01": bh_threshold,
        "z_threshold_null_max": empirical_threshold,
        "n_strata": float(len(np.unique(discovery_strata))),
        "confound_auroc_ceiling": confound_ceiling,
        "fraction_assigned_above_confound_ceiling": float(
            (assigned_auroc[assigned_term >= 0] > confound_ceiling).mean()
        ) if (assigned_term >= 0).any() else float("nan"),
        **probe,
        "null_max_z": float(null_z.max()) if null_z.size else float("nan"),
        "null_fraction_above_threshold": float((null_z > z_threshold).mean()) if null_z.size else float("nan"),
        "median_assigned_auroc": float(np.nanmedian(assigned_auroc[assigned_term >= 0])) if (assigned_term >= 0).any() else float("nan"),
        "median_assigned_carriers": float(np.median(assignment_carriers)) if len(assignment_carriers) else float("nan"),
        "fraction_assignment_agrees_by_z": float((assigned_term == by_z_term)[assigned_term >= 0].mean()) if (assigned_term >= 0).any() else float("nan"),
        "held_out_median_auroc": float(held_out["auroc"].median()) if len(held_out) else float("nan"),
        "held_out_median_ap": float(held_out["average_precision"].median()) if len(held_out) else float("nan"),
        "held_out_median_ap_lift": float(held_out["ap_lift"].median()) if len(held_out) else float("nan"),
        "held_out_median_prevalence": float(held_out["prevalence"].median()) if len(held_out) else float("nan"),
        "held_out_recall_at_precision_50_defined": float(
            held_out["recall_at_precision_50"].notna().mean()
        ) if len(held_out) else float("nan"),
        "held_out_median_recall_at_precision_50": float(
            held_out["recall_at_precision_50"].median()
        ) if len(held_out) else float("nan"),
        **bootstrap,
        # An interval that does not contain its own point estimate means the two summarize
        # different feature sets. That happened once and was caught by eye; it is checked here so
        # the next occurrence is visible in the summary rather than in a rendered table.
        "bootstrap_interval_covers_point": float(
            bool(
                bootstrap
                and bootstrap.get("held_out_bootstrap_median_auroc_ci_low", 1.0)
                <= float(held_out["auroc"].median() if len(held_out) else float("nan"))
                <= bootstrap.get("held_out_bootstrap_median_auroc_ci_high", 0.0)
            )
        ),
        "held_out_fraction_auroc_above_0_8": float((held_out["auroc"] > 0.8).mean()) if len(held_out) else float("nan"),
        "concordance_fraction_significant": concordance.fraction_significant,
        "concordance_median_enrichment": concordance.median_enrichment,
        "concordance_pooled_enrichment": concordance.pooled_enrichment,
        "concordance_pooled_enrichment_background": concordance_background.pooled_enrichment,
        "concordance_pooled_enrichment_protein_level": concordance_protein_level.pooled_enrichment,
        "concordance_fraction_significant_protein_level": concordance_protein_level.fraction_significant,
        "concordance_fraction_significant_background": concordance_background.fraction_significant,
        "n_concordance_population": float(len(proteins)),
        "concordance_fraction_any_hit": concordance.fraction_with_any_hit,
        "concordance_expected_fraction_any_hit": concordance.expected_fraction_with_any_hit,
        "n_concordance_scored": float(len(concordance.frame)),
        "fidelity_median_percentile": fidelity.median_percentile,
        "fidelity_fraction_top_100": fidelity.fraction_in_top_100,
        "category_compatible": float(recovery["compatible"].mean()) if len(recovery) else float("nan"),
        "category_local_match": float(recovery["local_match"].mean()) if len(recovery) else float("nan"),
        "fraction_assigned_local_aspect": float(recovery["is_local_aspect"].mean()) if len(recovery) else float("nan"),
        "lexical_any_hit": float(lexical["any_hit"].mean()) if len(lexical) else float("nan"),
        "lexical_label_any_hit": float(lexical["label_any_hit"].mean()) if len(lexical) else float("nan"),
        "lexical_label_jaccard": float(lexical["label_jaccard"].mean()) if len(lexical) else float("nan"),
        "n_local_pairs": float(len(local_frame)),
        "local_selected_median_enrichment": float(local_frame["enrichment"].median()) if len(local_frame) else float("nan"),
        "local_unfiltered_median_enrichment": local_statistics.get("unfiltered_median_enrichment", float("nan")),
        "local_unfiltered_p95_z": local_statistics.get("unfiltered_p95_z", float("nan")),
        "local_fraction_above_min_z": local_statistics.get("fraction_above_min_z", float("nan")),
        "local_null_median_enrichment": local_null.get("unfiltered_median_enrichment", float("nan")),
        "local_null_p95_z": local_null.get("unfiltered_p95_z", float("nan")),
        "local_null_fraction_above_min_z": local_null.get("fraction_above_min_z", float("nan")),
        "n_excluded_aspect_terms": float(0 if term_mask is None else int((~term_mask).sum())),
        "n_distinct_assigned_terms": float(len(set(assigned_term[assigned_term >= 0].tolist()))),
        "analysis_seconds": time.perf_counter() - started,
    }
    final_input_inventory = current_input_inventory()
    final_code_inventory = current_code_inventory()
    require_unchanged_inputs(initial_input_inventory, final_input_inventory)
    require_unchanged_inputs(initial_code_inventory, final_code_inventory)
    # The summary is written before the manifest so that the manifest's output digests cover it.
    # An earlier ordering hashed the directory first and left the headline numbers unbound, which
    # meant the provenance record could not detect a summary that changed after the fact.
    (output / "strata_distribution.json").write_text(
        json.dumps(strict_json(strata_report), indent=2, allow_nan=False)
    )
    (output / "summary.json").write_text(json.dumps(strict_json(summary), indent=2, allow_nan=False))
    (output / "analysis_manifest.json").write_text(
        json.dumps(
            {
                "inputs": final_input_inventory,
                "external_provenance": external_provenance_record,
                "code": final_code_inventory,
                "options": {
                    "pooling": pooling,
                    "min_auroc": min_auroc,
                    "min_support_requested": arguments_min_support,
                    "min_support_selected": min_support,
                    "rank_by_selected": rank_by,
                    "exemplar_exclusion": exemplar_exclusion,
                    "representative_rule": representative_rule,
                    "members_per_cluster": members_per_cluster,
                    "use_taxonomy": use_taxonomy,
                    "n_permutations": n_permutations,
                    "min_stratum_size": min_stratum_size,
                    "stratum_size_floor": min_stratum_size,
                    "domain_mapping_mode": domain_mapping.mode,
                    "domain_mapping_source_columns": list(domain_mapping.source_columns),
                    "domain_mapping_version": DOMAIN_MAPPING_VERSION,
                    "domain_other_policy": DOMAIN_OTHER_POLICY,
                    "domain_taxon_ids": DOMAIN_BY_TAXON_ID,
                    "strata_primary": (
                        "domain_length_density" if use_taxonomy else "length_density_only"
                    ),
                    "strata_sensitivity": "length_density_only",
                    "excluded_aspects": sorted(excluded_aspects),
                    "seed": DEFAULT_SEED,
                },
                "outputs": {
                    path.name: _digest(path)
                    for path in sorted(output.glob("*"))
                    if path.is_file() and path.name != "analysis_manifest.json"
                },
            },
            indent=2,
        )
    )
    print(json.dumps(strict_json(summary), indent=2, allow_nan=False))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run_dir", required=True)
    parser.add_argument("--protein_table", required=True)
    parser.add_argument("--term_table", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--pooling", default="max", choices=sorted(POOLING_MODES))
    parser.add_argument("--feature_table_path", required=True)
    parser.add_argument("--base_model_revision", required=True)
    parser.add_argument("--sae_revision", required=True)
    parser.add_argument("--feature_table_revision", required=True)
    parser.add_argument("--min_auroc", type=float, default=0.6)
    parser.add_argument("--min_support", type=int, default=50)
    parser.add_argument("--rank_by", default="auroc", choices=("auroc", "z"))
    parser.add_argument("--exemplar_exclusion", default="cluster", choices=("cluster", "accession"))
    parser.add_argument("--agent_label_table", default="")
    parser.add_argument("--agent_label_source_revision", default="")
    parser.add_argument("--representative_rule", default="mmseqs", choices=("mmseqs", "annotated"))
    parser.add_argument("--n_permutations", type=int, default=DEFAULT_PERMUTATIONS)
    parser.add_argument("--members_per_cluster", type=int, default=1)
    parser.add_argument("--min_stratum_size", type=int, default=MIN_STRATUM_SIZE)
    parser.add_argument("--no_taxonomy", action="store_true")
    parser.add_argument("--skip_local", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--exclude_aspect",
        action="append",
        default=[],
        help="withhold an aspect from assignment, to evaluate a vocabulary revision",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run_analysis(
        run_dir=arguments.run_dir,
        protein_table=arguments.protein_table,
        term_table=arguments.term_table,
        output_dir=arguments.output_dir,
        pooling=arguments.pooling,
        feature_table_path=arguments.feature_table_path,
        base_model_revision=arguments.base_model_revision,
        sae_revision=arguments.sae_revision,
        feature_table_revision=arguments.feature_table_revision,
        agent_label_source_revision=arguments.agent_label_source_revision,
        min_auroc=arguments.min_auroc,
        min_support=arguments.min_support,
        rank_by=arguments.rank_by,
        exemplar_exclusion=arguments.exemplar_exclusion,
        agent_label_table=arguments.agent_label_table,
        representative_rule=arguments.representative_rule,
        excluded_aspects=tuple(arguments.exclude_aspect),
        min_stratum_size=arguments.min_stratum_size,
        members_per_cluster=arguments.members_per_cluster,
        use_taxonomy=not arguments.no_taxonomy,
        n_permutations=arguments.n_permutations,
        skip_local=arguments.skip_local,
        overwrite=arguments.overwrite,
    )
