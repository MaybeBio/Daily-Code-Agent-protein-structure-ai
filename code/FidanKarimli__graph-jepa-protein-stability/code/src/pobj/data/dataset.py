"""Protein-level dataset for ddG fine-tuning.

One item is one protein carrying all of its mutations, so a batch encodes a handful of
structures and scores every mutation on them. That turns 215k training examples into 239
encoder passes per epoch.
"""
from pathlib import Path

import pandas as pd
import torch
from torch_geometric.data import Data

from .graph import K_NEIGHBOURS, build_graphs
from .megascale import AA_IDX, load_labels, load_structures


class ProteinData(Data):
    """Node indices stored on a graph must shift when graphs are batched together."""

    def __inc__(self, key, value, *args, **kwargs):
        if key == "mut_node":
            return self.num_nodes
        return super().__inc__(key, value, *args, **kwargs)


def load_all(raw_dir: Path | str | None = None, pdb_dir: Path | str | None = None,
             k: int = K_NEIGHBOURS,
             cache_dir: Path | str = "data/processed") -> tuple[pd.DataFrame, dict[str, Data]]:
    """Labels and graphs, cached after the first call."""
    kwargs = {}
    if raw_dir is not None:
        kwargs["raw_dir"] = raw_dir

    cache = Path(cache_dir) / f"megascale_k{k}.pt"
    if cache.exists():
        blob = torch.load(cache, weights_only=False)
        return blob["labels"], blob["graphs"]

    labels = load_labels(**kwargs)
    names = labels.WT_name.unique()
    structures = (load_structures(names, pdb_dir=pdb_dir) if pdb_dir
                  else load_structures(names))
    graphs = build_graphs(structures, k=k)

    cache.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"labels": labels, "graphs": graphs}, cache)
    return labels, graphs


def protein_items(labels: pd.DataFrame, graphs: dict[str, Data],
                  split: str | None = None) -> list["ProteinData"]:
    """-> list of ProteinData, one per protein."""
    rows = labels if split is None else labels[labels.split == split]
    items = []
    for name, group in rows.groupby("WT_name", sort=True):
        g = graphs[name]
        items.append(ProteinData(
            x=g.x,
            node_feat=g.node_feat,
            edge_index=g.edge_index,
            edge_attr=g.edge_attr,
            num_nodes=g.num_nodes,
            mut_node=torch.tensor(group.pos.values - 1, dtype=torch.long),
            mut_wt=torch.tensor([AA_IDX[a] for a in group.wt_aa], dtype=torch.long),
            mut_aa=torch.tensor([AA_IDX[a] for a in group.mut_aa], dtype=torch.long),
            ddg=torch.tensor(group.ddG.values, dtype=torch.float32),
            name=name,
        ))
    return items


def batch_protein_names(batch: Data) -> list[str]:
    """The protein each mutation in a batch belongs to, for per-protein metrics."""
    names = batch.name if isinstance(batch.name, list) else [batch.name]
    return [names[i] for i in batch.batch[batch.mut_node].tolist()]
