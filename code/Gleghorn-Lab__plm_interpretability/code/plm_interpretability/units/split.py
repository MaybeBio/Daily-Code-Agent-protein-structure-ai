"""The atlas set's proteins: the compendium's own split, sampled to the GPU budget and locked by its digest before any
activation is computed.

The release split its pooled sequences 85/5/8/2 by cluster with no pair at 0.5 identity or more across splits, held out only
clusters with an experimental assertion outside the organism aspect, and applies to each row the tier rule of its split
(`compendium`), so the atlas set keeps every protein's release split. Train takes one reviewed (Swiss-Prot) protein of each
0.3-identity cluster of the release's train split, drawn uniformly. Validation, test and calibration take at most two of each
0.3-identity cluster's eligible proteins, those with an experimental assertion outside the organism aspect, none of them a
protein the atlas study held out, whose evaluation clusters were examined while that study was developed; validation and
calibration are then cut to their sizes by a seeded draw, while test keeps every protein drawn. The assignment's SHA-256 is
written to the launch record before extraction (preregistration, `split`).

Symbols: n proteins.
"""

from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd

from collections.abc import Collection, Mapping


SEED = 20261106
SPLITS = ("train", "validation", "test", "calibration")
HELD_OUT = ("validation", "test", "calibration")
TRAIN_PER_CLUSTER = 1
HELD_OUT_PER_CLUSTER = 2
SIZES = {"validation": 4_400, "calibration": 1_800}  # test keeps every protein drawn
CLUSTER_LEVEL = "c030"  # the release's 0.3-identity clusters (`tables/clusters.parquet`)
POOL_COLUMNS = ("protein_id", "accessions", "split", "eligible", "reviewed", "cluster")


def draw_members(pool: pd.DataFrame, per_cluster: int, generator: np.random.Generator) -> pd.DataFrame:
    """At most `per_cluster` proteins of each cluster, drawn uniformly; rows keep the input's columns."""
    # pool: n rows with `protein_id` and `cluster`
    if pool["protein_id"].duplicated().any():
        raise ValueError("Each protein must appear once in the pool.")
    ordered = pool.sort_values(["cluster", "protein_id"], kind="mergesort").reset_index(drop=True)
    keys = generator.random(len(ordered))  # (n,)
    ranked = ordered.assign(_key=keys).sort_values(["cluster", "_key"], kind="mergesort")
    kept = ranked.groupby("cluster", sort=False).head(per_cluster)
    return kept.drop(columns="_key").sort_values("protein_id", kind="mergesort").reset_index(drop=True)


def atlas_sample(pool: pd.DataFrame, examined: Collection[str], *, seed: int = SEED,
                 sizes: Mapping[str, int] = SIZES) -> pd.DataFrame:
    """The atlas set's proteins with their release split and cluster, sorted by protein id.

    `pool` holds one row per pooled protein with `POOL_COLUMNS`: its release split, whether it is eligible (an experimental
    assertion outside the organism aspect), whether it is reviewed, and its 0.3-identity cluster. `examined` holds the
    accessions the atlas study held out; a protein carrying one is never held out here.
    """
    missing = sorted(set(POOL_COLUMNS) - set(pool.columns))
    if missing:
        raise ValueError(f"The pool lacks {missing}.")
    unknown = sorted(set(pool["split"]) - set(SPLITS))
    if unknown:
        raise ValueError(f"Unknown splits {unknown}.")
    seen = frozenset(examined)
    was_examined = pool["accessions"].map(lambda accessions: any(accession in seen for accession in accessions))  # (n,)
    parts = [draw_members(pool[(pool["split"] == "train") & pool["reviewed"]], TRAIN_PER_CLUSTER, np.random.default_rng((seed, 0)))]
    for index, name in enumerate(HELD_OUT, start=1):
        candidates = pool[(pool["split"] == name) & pool["eligible"] & ~was_examined]
        drawn = draw_members(candidates, HELD_OUT_PER_CLUSTER, np.random.default_rng((seed, index)))
        if name in sizes:
            if len(drawn) < sizes[name]:
                raise ValueError(f"{name} has {len(drawn)} proteins to draw from, fewer than its {sizes[name]}.")
            chosen = np.random.default_rng((seed, index, 1)).choice(len(drawn), size=sizes[name], replace=False)  # (size,)
            drawn = drawn.iloc[np.sort(chosen)]
        parts.append(drawn)
    sample = pd.concat(parts, ignore_index=True)[["protein_id", "cluster", "split"]]
    return sample.sort_values("protein_id", kind="mergesort").reset_index(drop=True)


def assignment_digest(sample: pd.DataFrame) -> str:
    """SHA-256 of the sorted (protein id, cluster, split) rows, the value the preregistration locks."""
    rows = sample[["protein_id", "cluster", "split"]].astype(str).sort_values("protein_id", kind="mergesort")
    text = "\n".join("\t".join(row) for row in rows.itertuples(index=False, name=None))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
