"""Choose a structure set from the PDB by a fixed, documented query, not by hand.

Picking structures one by one invites picking the ones that work. The query below is recorded in the
results so the set can be rebuilt: X-ray structures at 2.0 Angstrom or better, a single protein
chain, 80 to 200 residues, no nucleic acid. A fixed seed then samples from everything that matches.
"""
import json
import os
import random
import urllib.request

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DOWNLOAD = "https://files.rcsb.org/download/{pdb_id}.pdb"

QUERY = {
    "query": {"type": "group", "logical_operator": "and", "nodes": [
        {"type": "terminal", "service": "text", "parameters": {
            "attribute": "exptl.method", "operator": "exact_match", "value": "X-RAY DIFFRACTION"}},
        {"type": "terminal", "service": "text", "parameters": {
            "attribute": "rcsb_entry_info.resolution_combined", "operator": "less_or_equal", "value": 2.0}},
        {"type": "terminal", "service": "text", "parameters": {
            "attribute": "rcsb_entry_info.polymer_entity_count_protein", "operator": "equals", "value": 1}},
        {"type": "terminal", "service": "text", "parameters": {
            "attribute": "rcsb_entry_info.polymer_entity_count_nucleic_acid", "operator": "equals", "value": 0}},
        {"type": "terminal", "service": "text", "parameters": {
            "attribute": "rcsb_entry_info.deposited_polymer_monomer_count",
            "operator": "range", "value": {"from": 80, "to": 200}}},
    ]},
    "return_type": "entry",
    "request_options": {"return_all_hits": True},
}


def search_ids(timeout=120):
    req = urllib.request.Request(SEARCH_URL, data=json.dumps(QUERY).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        hits = json.load(fh)["result_set"]
    return [h["identifier"] for h in hits]


def sample_ids(ids, n=60, seed=0):
    ids = sorted(ids)
    return sorted(random.Random(seed).sample(ids, min(n, len(ids))))


def fetch(pdb_id, out_dir, timeout=60):
    path = os.path.join(out_dir, f"{pdb_id}.pdb")
    if not os.path.exists(path):
        urllib.request.urlretrieve(DOWNLOAD.format(pdb_id=pdb_id), path)
    return path


def build_set(out_dir="data/structures", n=60, seed=0):
    os.makedirs(out_dir, exist_ok=True)
    all_ids = search_ids()
    chosen = sample_ids(all_ids, n=n, seed=seed)
    paths = []
    for pdb_id in chosen:
        try:
            paths.append(fetch(pdb_id, out_dir))
        except Exception as exc:                                  # noqa: BLE001
            print(f"  skipped {pdb_id}: {type(exc).__name__}", flush=True)
    with open(os.path.join(out_dir, "selection.json"), "w") as fh:
        json.dump({"query": QUERY, "matched_entries": len(all_ids), "seed": seed,
                   "requested": n, "downloaded": len(paths),
                   "pdb_ids": [os.path.basename(p)[:-4] for p in paths]}, fh, indent=2)
    return paths
