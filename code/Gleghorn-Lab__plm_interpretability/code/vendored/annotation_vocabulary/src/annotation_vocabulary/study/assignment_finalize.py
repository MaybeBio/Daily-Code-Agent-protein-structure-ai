"""Stream exact assignment tables from disjoint feature metric shards.

This module changes table materialization only. Statistical functions and the
joint nominal correction are supplied by the association implementation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .association import RoundedBH, resolution_coverage, select_global, select_local


def selected_frame(
    metrics: dict[str, np.ndarray], features: np.ndarray, tokens: np.ndarray,
    kind: str, correction: RoundedBH, config: dict[str, Any],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray | None]:
    """Apply the original endpoint gates and preserve metric column order."""
    # metrics: (f,t) matrices, (f,) global n_active, (t,) term vectors; features: (f,); tokens: (t,)
    support = int(config.get("min_support", 10))
    gates = dict(alpha=float(config.get("alpha", .01)), enrichment=float(config.get("min_enrichment", 2)), min_support=support, min_active_proteins=int(config.get("min_active_proteins", support)))
    auroc = float(config.get("min_auroc", .60))
    presence_q = None
    if kind == "global":
        rank_q = correction.transform(metrics["rank_p"])  # (f,t)
        presence_q = correction.transform(metrics["presence_p"])  # (f,t)
        selected = select_global(metrics, rank_q, presence_q, auroc=auroc, **gates)  # (f,t)
        q_value = np.minimum(np.where(metrics["auroc"] >= auroc, rank_q, 1), np.where(metrics["activation_enrichment"] >= gates["enrichment"], presence_q, 1))  # (f,t)
    else:
        rank_q = correction.transform(metrics["local_p"])  # (f,t), local endpoint q
        q_value = rank_q
        selected = select_local(metrics, q_value, **gates)  # (f,t)
    feature_rows, term_columns = np.nonzero(selected)  # (a,), (a,)
    columns: dict[str, Any] = {"feature_id": features[feature_rows], "token": tokens[term_columns], "association_kind": kind, "nominal_q": q_value[feature_rows, term_columns]}
    if kind == "global":
        columns["rank_q"] = rank_q[feature_rows, term_columns]
        columns["presence_q"] = presence_q[feature_rows, term_columns]
    for name, values in metrics.items():
        if values.ndim == 2:
            columns[name] = values[feature_rows, term_columns]  # (a,)
        elif name == "n_active" and kind == "global":
            columns[name] = values[feature_rows]  # (a,)
        else:
            columns[name] = values[term_columns]  # (a,)
    return pd.DataFrame(columns), rank_q, presence_q  # frame of a rows; rank_q: (f, t); presence_q: (f, t) or None


def _read(path: Path) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, str]:
    with np.load(path, allow_pickle=False) as archive:
        metrics = dict(archive)
    features = metrics.pop("feature_indices")  # (f,)
    tokens = metrics.pop("term_tokens")  # (t,)
    return metrics, features, tokens, "local" if "local_p" in metrics else "global"  # metrics: (f, t) matrices and vectors; features: (f,); tokens: (t,)


def _annotate(frame: pd.DataFrame, terms: pd.DataFrame, any_selected: bool) -> pd.DataFrame:
    assigned = frame.merge(terms, on="token", how="left", validate="many_to_one")
    assigned["scope"] = assigned["association_kind"]
    assigned["endpoint"] = assigned["association_kind"].map({"global": "protein_presence", "local": "residue_localization"})
    assigned["selected"] = True
    assigned["representative"] = False
    if any_selected:
        assigned["selection_effect"] = assigned["auroc"].where(assigned["association_kind"] == "global", assigned.get("mean_difference", np.nan))
        winners = assigned.sort_values(["nominal_q", "selection_effect", "token"], ascending=[True, False, True], kind="stable").drop_duplicates(["feature_id", "scope"]).index
        assigned.loc[winners, "representative"] = True
    return assigned


def finalize_assignments(
    metric_files: Iterable[Path], terms: pd.DataFrame, correction: RoundedBH,
    feature_indices: np.ndarray, active_features: set[int], global_evaluable: set[int],
    local_evaluable: set[int], codebook_features: int, output_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Write bounded-memory tables in original shard, feature, and token order.

    Every feature must occur once per scope. This makes the representative for
    each feature/scope computable inside one shard without a global sort. The
    first pass establishes pandas' union-column dtypes, selection counts, and
    sensitivity sets. The second emits the identical rows as Parquet row groups.
    The caller owns completed-input verification and the final run manifest.
    """
    # feature_indices: (evaluated_f,); each metric shard: (block_f,terms)
    paths = list(map(Path, metric_files))
    output_dir = Path(output_dir)
    for name in ("assignments.parquet", "assignments.parquet.pending", "feature_coverage.parquet", "threshold_curves.parquet"):
        if (output_dir / name).exists():
            raise FileExistsError(f"Refusing to replace an existing finalized table: {name}")
    if correction.adjusted is None:
        raise ValueError("A finalized joint correction is required")
    if terms.token.duplicated().any():
        raise ValueError("Term identities must join uniquely")
    support = int(config.get("min_support", 10))
    alpha = float(config.get("alpha", .01))
    min_auroc = float(config.get("min_auroc", .60))
    min_enrichment = float(config.get("min_enrichment", 2))
    min_active = int(config.get("min_active_proteins", support))
    auc_grid = sorted(set(map(float, config.get("auroc_sensitivity", [.55, .60, .65]))) | {min_auroc})
    enrichment_grid = sorted(set(map(float, config.get("enrichment_sensitivity", [1.5, 2, 3]))) | {min_enrichment})
    curves = {(auc, enrich): (set(), set()) for auc in auc_grid for enrich in enrichment_grid}
    seen: dict[str, set[int]] = {"global": set(), "local": set()}
    allowed = set(map(int, feature_indices))
    samples: list[pd.DataFrame] = []
    row_counts: list[int] = []
    selected_tokens: set[int] = set()
    for path in paths:
        metrics, features, tokens, kind = _read(path)
        current = set(map(int, features))
        if len(current) != len(features) or current & seen[kind] or not current <= allowed:
            raise ValueError("Each evaluated feature must occur at most once per scope")
        if len(np.unique(tokens)) != len(tokens) or not set(map(int, tokens)) <= set(map(int, terms.token)):
            raise ValueError("Metric tokens must join uniquely to the supplied vocabulary")
        seen[kind].update(current)
        frame, first_q, presence_q = selected_frame(metrics, features, tokens, kind, correction, config)
        samples.append(frame.iloc[:1].copy(deep=True))
        row_counts.append(len(frame))
        selected_tokens.update(map(int, frame.token))
        for (auc, enrich), (global_set, local_set) in curves.items():
            gates = dict(alpha=alpha, enrichment=enrich, min_support=support, min_active_proteins=min_active)
            if kind == "global":
                passed = select_global(metrics, first_q, presence_q, auroc=auc, **gates)  # (f,t)
                global_set.update(features[np.any(passed, axis=1)].tolist())
            else:
                passed = select_local(metrics, first_q, **gates)  # (f,t)
                local_set.update(features[np.any(passed, axis=1)].tolist())
    if seen["global"] != allowed:
        raise ValueError("Global metric shards do not cover all evaluated features")
    if config.get("include_local", True) and terms.is_local.astype(bool).any() and seen["local"] != allowed:
        raise ValueError("Local metric shards do not cover all evaluated features")
    template = pd.concat(samples, ignore_index=True)  # (at_most_shards, union_columns)
    assignment_count = sum(row_counts)
    output_dir.mkdir(parents=True, exist_ok=True)
    global_set, local_set = curves[(min_auroc, min_enrichment)]
    coverage = pd.DataFrame({"feature_id": feature_indices})
    for name, members in (("active", active_features), ("global_evaluable", global_evaluable), ("local_evaluable", local_evaluable)):
        coverage[name] = coverage.feature_id.isin(members)
    coverage["evaluable"] = coverage.global_evaluable | coverage.local_evaluable
    coverage["global_assigned"] = coverage.feature_id.isin(global_set)
    coverage["local_assigned"] = coverage.feature_id.isin(local_set)
    coverage["assigned"] = coverage.global_assigned | coverage.local_assigned
    empty = _annotate(template.iloc[:0], terms, bool(assignment_count))
    if "is_derived" in empty:
        coverage["existing_vocabulary_assigned"] = False
        coverage["derived_local_assigned"] = False
    resolution = resolution_coverage(coverage, empty)
    resolution_columns = [name for name in coverage if name.startswith(("coarse_parent_", "finer_local_concept_"))]
    if not assignment_count:
        empty.to_parquet(output_dir / "assignments.parquet", index=False)
    else:
        # Include every selected term once to infer nested/list/object types;
        # numeric dtypes come from the cross-scope pandas concatenation above.
        selected_term_ids = terms.loc[terms.token.isin(selected_tokens), "token"].to_numpy()
        schema_rows = template.iloc[np.zeros(len(selected_term_ids), dtype=np.int64)].reset_index(drop=True)
        schema_rows["token"] = selected_term_ids.astype(template.token.dtype, copy=False)
        schema = pa.Table.from_pandas(_annotate(schema_rows, terms, True), preserve_index=False).schema
        del schema_rows
        pending = output_dir / "assignments.parquet.pending"
        with pq.ParquetWriter(pending, schema) as writer:
            for path, expected_count in zip(paths, row_counts, strict=False):
                metrics, features, tokens, kind = _read(path)
                frame, _, _ = selected_frame(metrics, features, tokens, kind, correction, config)
                if len(frame) != expected_count:
                    raise ValueError("Metric selection changed between finalization passes")
                if not len(frame):
                    continue
                # Reproduce concat's cross-scope NaNs and integer promotions.
                frame = frame.reindex(columns=template.columns).astype(template.dtypes.to_dict())
                assigned = _annotate(frame, terms, True)
                table = pa.Table.from_pandas(assigned, schema=schema, preserve_index=False)
                writer.write_table(table)
                if "is_derived" in assigned:
                    derived = assigned.is_derived.fillna(False).astype(bool)
                    coverage["existing_vocabulary_assigned"] |= coverage.feature_id.isin(assigned.loc[~derived, "feature_id"])
                    coverage["derived_local_assigned"] |= coverage.feature_id.isin(assigned.loc[derived, "feature_id"])
                block_coverage = pd.DataFrame({"feature_id": feature_indices})
                resolution_coverage(block_coverage, assigned)
                if resolution["status"] == "computed":
                    for name in resolution_columns:
                        coverage[name] |= block_coverage[name]
        pending.replace(output_dir / "assignments.parquet")
    coverage.to_parquet(output_dir / "feature_coverage.parquet", index=False)
    pd.DataFrame([{"auroc_threshold": auc, "enrichment_threshold": enrich, "global": len(global_set), "local": len(local_set), "both": len(global_set & local_set), "union": len(global_set | local_set), "evaluated_features": len(feature_indices), "codebook_features": codebook_features} for (auc, enrich), (global_set, local_set) in curves.items()]).to_parquet(output_dir / "threshold_curves.parquet", index=False)
    return {"assignment_pairs": assignment_count, "assigned_features": int(coverage.assigned.sum()), "local_resolution_coverage": resolution}
