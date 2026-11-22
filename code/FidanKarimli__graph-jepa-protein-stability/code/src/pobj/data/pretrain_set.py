"""The unlabelled structures we pretrain on.

Two corpora: SCOPe domains from ASTRAL, and AlphaFold predictions sampled from Swiss-Prot.
Both are built into graphs by exactly the same code as the MegaScale ones, so the encoder
sees the same kind of input in both stages.

Which structures each corpus contains is decided once and written down —
pretrain_ids.txt for SCOPe, alphafold_ids.txt for the other — so neither can change
underneath a result.
"""
from pathlib import Path

import torch

from .graph import K_NEIGHBOURS, build_graph
from .megascale import read_pdb

SCOPE_DIR = Path("data/raw/scope")
IDS_FILE = Path("data/processed/pretrain_ids.txt")

# SCOPe domains run from a few residues to over a thousand. MegaScale domains are 32-72,
# so we drop the extremes: tiny fragments carry almost no structure, and long chains make
# batches ragged for no benefit at this scale.
MIN_LEN = 30
MAX_LEN = 256


def domain_files(root=SCOPE_DIR):
    """-> {domain id: path}. ASTRAL stores d1dlwa_.ent under a two-letter folder."""
    return {p.stem: p for p in sorted(Path(root).rglob("*.ent"))}


def read_domains(paths, min_len=MIN_LEN, max_len=MAX_LEN):
    """-> ({id: (seq, coords)}, {reason: count})"""
    kept, dropped = {}, {"unreadable": 0, "too_short": 0, "too_long": 0}
    for name, path in paths.items():
        try:
            seq, coords = read_pdb(path)
        except (ValueError, IndexError):
            dropped["unreadable"] += 1
            continue
        if len(seq) < min_len:
            dropped["too_short"] += 1
        elif len(seq) > max_len:
            dropped["too_long"] += 1
        else:
            kept[name] = (seq, coords)
    return kept, dropped


def parse_alphafold(text):
    """One AlphaFold pdb -> (seq, coords [N, 4, 3], mean pLDDT).

    AlphaFold writes its per-residue confidence into the B-factor column, so the quality
    filter needs no extra request.
    """
    from .megascale import AA3, AA_IDX, BACKBONE

    residues = {}
    for line in text.splitlines():
        if not line.startswith("ATOM"):
            continue
        atom = line[12:16].strip()
        if atom not in BACKBONE:
            continue
        key = int(line[22:26])
        r = residues.setdefault(key, {"aa": AA3.get(line[17:20], "X"), "xyz": {},
                                      "plddt": float(line[60:66])})
        r["xyz"].setdefault(atom, (float(line[30:38]), float(line[38:46]), float(line[46:54])))

    kept = [residues[k] for k in sorted(residues)
            if residues[k]["aa"] in AA_IDX and len(residues[k]["xyz"]) == len(BACKBONE)]
    if not kept:
        return "", None, 0.0
    import numpy as np

    seq = "".join(r["aa"] for r in kept)
    coords = np.array([[r["xyz"][a] for a in BACKBONE] for r in kept], dtype=np.float32)
    plddt = float(np.mean([r["plddt"] for r in kept]))
    return seq, coords, plddt


def write_fasta(path, sequences):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for name, seq in sequences.items():
            f.write(f">{name}\n{seq}\n")


def write_megascale_fasta(path):
    """The sequences the pretraining set must not resemble."""
    from .megascale import load_labels

    labels = load_labels().drop_duplicates("WT_name")
    write_fasta(path, dict(zip(labels.WT_name, labels.wt_seq)))
    return len(labels)


def mmseqs_similar(query_fa, target_fa, hits_file, tmp_dir, max_evalue=1e-3,
                   min_seq_id=0.3, rerun=True):
    """Sequences in query_fa that resemble anything in target_fa.

    -> (all hits, hits at or above min_seq_id). We drop everything in the first set, since
    a remote homologue can share a fold while falling below 30% identity.
    """
    import subprocess

    hits_file, tmp_dir = Path(hits_file), Path(tmp_dir)
    if rerun or not hits_file.exists():
        subprocess.run(
            ["mmseqs", "easy-search", str(query_fa), str(target_fa),
             str(hits_file), str(tmp_dir),
             "-s", "7.5", "-e", str(max_evalue), "--min-seq-id", "0.0",
             "-c", "0.5", "--cov-mode", "1",
             "--format-output", "query,target,fident,alnlen,evalue,bits"],
            check=True, stdout=subprocess.DEVNULL)

    any_hit, close = set(), set()
    for line in hits_file.read_text().splitlines():
        query, _, fident, _, evalue, _ = line.split("\t")
        any_hit.add(query)
        if float(fident) >= min_seq_id and float(evalue) <= max_evalue:
            close.add(query)
    return any_hit, close


def load_scope_graphs(ids_file=IDS_FILE, root=SCOPE_DIR, k=K_NEIGHBOURS,
                      cache_dir="data/processed"):
    """Graphs for the domains listed in ids_file, cached after the first call."""
    cache = Path(cache_dir) / f"pretrain_k{k}.pt"
    if cache.exists():
        return torch.load(cache, weights_only=False)

    ids = set(Path(ids_file).read_text().split())
    paths = {name: path for name, path in domain_files(root).items() if name in ids}
    structures, _ = read_domains(paths)
    graphs = [build_graph(seq, coords, name=name)
              for name, (seq, coords) in structures.items()]
    cache.parent.mkdir(parents=True, exist_ok=True)
    torch.save(graphs, cache)
    return graphs


def load_alphafold_graphs(shard_dir="data/processed/alphafold", k=K_NEIGHBOURS,
                          cache_dir="data/processed"):
    """Graphs from the shards written by scripts/download_alphafold.py.

    Those structures were already length- and leakage-filtered before download, so there
    is nothing left to screen here.
    """
    cache = Path(cache_dir) / f"pretrain_alphafold_k{k}.pt"
    if cache.exists():
        return torch.load(cache, weights_only=False)

    shards = sorted(Path(shard_dir).glob("shard_*.pt"))
    if not shards:
        raise FileNotFoundError(f"no shards in {shard_dir}; "
                                f"run scripts/download_alphafold.py first")
    graphs = []
    for shard in shards:
        for record in torch.load(shard, weights_only=False)["structures"]:
            graphs.append(build_graph(record["seq"], record["coords"],
                                      name=record["acc"], k=k))
    cache.parent.mkdir(parents=True, exist_ok=True)
    torch.save(graphs, cache)
    return graphs


def load_pretrain_graphs(corpus="scope", k=K_NEIGHBOURS, cache_dir="data/processed",
                         limit=None):
    if corpus == "scope":
        graphs = load_scope_graphs(k=k, cache_dir=cache_dir)
    elif corpus == "alphafold":
        graphs = load_alphafold_graphs(k=k, cache_dir=cache_dir)
    else:
        raise ValueError(f"unknown corpus {corpus!r}")
    return graphs[:limit] if limit else graphs
