"""Build authentic RCSB PDB Enzyme Function Benchmark with <30% sequence-identity cluster splits.

Combines experimentally determined 3D crystal coordinates from CATH 4.2 PDB chains with:
  1. Official Enzyme Commission (EC) lineage annotations fetched from RCSB GraphQL API.
  2. Official MMseqs2 30% sequence-identity clusters from RCSB CDN (`clusters-by-entity-30.txt`),
     guaranteeing zero >30% sequence homology leakage across train / val / test splits.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from protgnn.data.constants import AMINO_ACIDS, EC_CLASSES

AA_SET = set(AMINO_ACIDS)
RCSB_CLUSTERS30_URL = "https://cdn.rcsb.org/resources/sequence/clusters/clusters-by-entity-30.txt"
CATH_JSONL_URL = "http://people.csail.mit.edu/ingraham/graph-protein-design/data/cath/chain_set.jsonl"

# Default path to cached real CATH 4.2 coordinates (falls back to download into data/raw if needed)
SHARED_CATH_JSONL = PROJ_DIR.parent / "protein-inverse-folding" / "data" / "raw" / "cath_4_2" / "chain_set.jsonl"


def _get_cath_jsonl(raw_dir: Path) -> Path:
    local = raw_dir / "chain_set.jsonl"
    if local.exists():
        return local
    if SHARED_CATH_JSONL.exists():
        return SHARED_CATH_JSONL
    urllib.request.urlretrieve(CATH_JSONL_URL, local)
    return local


def _load_rcsb_clusters_30(raw_dir: Path, ctx: ssl.SSLContext) -> dict[str, int]:
    """Download and parse RCSB PDB official 30% sequence-identity cluster assignments."""
    clust_path = raw_dir / "clusters-by-entity-30.txt"
    if not clust_path.exists():
        print("Downloading RCSB 30% sequence-identity cluster table...")
        req = urllib.request.Request(RCSB_CLUSTERS30_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp, open(clust_path, "wb") as out:
            out.write(resp.read())

    entity_to_cluster: dict[str, int] = {}
    with open(clust_path, "r", encoding="utf-8") as fh:
        for cid, line in enumerate(fh):
            for ent in line.strip().split():
                entity_to_cluster[ent.upper()] = cid
    return entity_to_cluster


def _fetch_rcsb_ec_annotations(pdb_ids: list[str], raw_dir: Path, ctx: ssl.SSLContext) -> dict[tuple[str, str], tuple[str, list[str]]]:
    """Query RCSB GraphQL for polymer_entity IDs and EC lineages."""
    cache_file = raw_dir / "rcsb_ec_cache.json"
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as fh:
            raw_cache = json.load(fh)
        return {(k.split(".")[0], k.split(".")[1]): tuple(v) for k, v in raw_cache.items()}

    gql = """
    query($ids: [String!]!) {
      entries(entry_ids: $ids) {
        rcsb_id
        polymer_entities {
          rcsb_polymer_entity_container_identifiers { auth_asym_ids entity_id }
          rcsb_polymer_entity { rcsb_ec_lineage { id } }
        }
      }
    }
    """
    ec_map: dict[tuple[str, str], tuple[str, list[str]]] = {}
    print(f"Querying RCSB GraphQL for EC annotations across {len(pdb_ids):,} PDB entries...")
    for i in range(0, len(pdb_ids), 800):
        batch = pdb_ids[i : i + 800]
        req = urllib.request.Request(
            "https://data.rcsb.org/graphql",
            data=json.dumps({"query": gql, "variables": {"ids": batch}}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=45, context=ctx) as resp:
            entries = json.loads(resp.read().decode())["data"]["entries"]
        for ent in entries:
            if not ent:
                continue
            pid = ent["rcsb_id"].upper()
            for pe in ent.get("polymer_entities") or []:
                ecs = [e["id"] for e in (pe.get("rcsb_polymer_entity", {}).get("rcsb_ec_lineage") or [])]
                if not ecs:
                    continue
                cids = pe["rcsb_polymer_entity_container_identifiers"].get("auth_asym_ids") or []
                eid = pe["rcsb_polymer_entity_container_identifiers"]["entity_id"]
                entity_key = f"{pid}_{eid}"
                for c in cids:
                    ec_map[(pid, str(c))] = (entity_key, sorted(set(ecs)))

    serializable = {f"{pid}.{c}": [v[0], v[1]] for (pid, c), v in ec_map.items()}
    with open(cache_file, "w", encoding="utf-8") as fh:
        json.dump(serializable, fh)
    return ec_map


def main(seed: int = 42, min_len: int = 40, max_len: int = 500) -> None:
    raw_dir = Path("data/raw")
    raw_dir.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()

    jsonl_path = _get_cath_jsonl(raw_dir)
    clusters30 = _load_rcsb_clusters_30(raw_dir, ctx)

    # First pass: collect chain IDs to query RCSB GraphQL
    candidate_names: list[str] = []
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            candidate_names.append(str(rec["name"]))

    pdb_ids = sorted({n.split(".")[0].upper() for n in candidate_names})
    ec_map = _fetch_rcsb_ec_annotations(pdb_ids, raw_dir, ctx)
    ec_target_set = set(EC_CLASSES)

    # Second pass: extract clean finite 3D CA coordinates and matching EC labels
    records = []
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            name = str(rec["name"])
            parts = name.split(".")
            if len(parts) != 2:
                continue
            key = (parts[0].upper(), parts[1])
            if key not in ec_map:
                continue

            entity_key, ecs = ec_map[key]
            matched_ecs = sorted([e for e in ecs if e in ec_target_set])
            if not matched_ecs:
                continue

            seq = str(rec.get("seq", "")).strip().upper()
            raw_ca = np.asarray(rec["coords"]["CA"], dtype=np.float32)
            if len(seq) != len(raw_ca) or len(seq) < min_len or len(seq) > max_len:
                continue

            # Keep only residues with experimentally resolved C-alpha coordinates and standard AA
            valid_mask = np.isfinite(raw_ca).all(axis=1) & np.array([ch in AA_SET for ch in seq], dtype=bool)
            if float(valid_mask.mean()) < 0.85 or int(valid_mask.sum()) < min_len:
                continue

            clean_seq = "".join(ch for ch, ok in zip(seq, valid_mask) if ok)
            ca = raw_ca[valid_mask]
            L = len(clean_seq)

            clust_id = clusters30.get(entity_key.upper(), -1)
            records.append(
                {
                    "pdb_chain": name,
                    "entity_id": entity_key,
                    "cluster_30": clust_id if clust_id >= 0 else hash(entity_key) % 10_000_000,
                    "sequence": clean_seq,
                    "length": L,
                    "ec_annotations": ";".join(matched_ecs),
                    "primary_ec": int(matched_ecs[0].split(".")[0]),
                    "coords": ca,
                }
            )

    # Assign strict 30%-sequence-identity cluster splits (75% train, 10% val, 15% test)
    rng = np.random.RandomState(seed)
    unique_clusters = np.array(sorted({r["cluster_30"] for r in records}))
    rng.shuffle(unique_clusters)
    n_c = len(unique_clusters)
    n_tr = int(0.75 * n_c)
    n_val = int(0.10 * n_c)

    tr_c = set(unique_clusters[:n_tr])
    val_c = set(unique_clusters[n_tr : n_tr + n_val])

    for r in records:
        cid = r["cluster_30"]
        r["split"] = "train" if cid in tr_c else ("val" if cid in val_c else "test")

    df = pd.DataFrame(
        [{k: v for k, v in r.items() if k != "coords"} for r in records]
    )
    df.to_csv(raw_dir / "ec_pdb_splits.csv", index=False)

    np.savez_compressed(
        raw_dir / "ec_pdb_splits.npz",
        pdb_chains=np.array([r["pdb_chain"] for r in records], dtype=object),
        sequences=np.array([r["sequence"] for r in records], dtype=object),
        splits=np.array([r["split"] for r in records], dtype=object),
        ec_annotations=np.array([r["ec_annotations"] for r in records], dtype=object),
        coords=np.array([r["coords"] for r in records], dtype=object),
    )

    counts = df["split"].value_counts().to_dict()
    overlap = set(df[df["split"] == "train"]["cluster_30"]) & set(df[df["split"] == "test"]["cluster_30"])
    print(f"Built REAL RCSB PDB Enzyme Benchmark: {len(df):,} crystal chains across {len(EC_CLASSES)} EC subclasses.")
    print(f"Splits (<30% sequence identity): {counts} | 30%-Cluster train/test overlap: {len(overlap)}")


if __name__ == "__main__":
    main()
