"""Build the residue graphs, print their statistics, and draw one protein.

Run from the repo root:  python scripts/inspect_graph.py
Writes results/figures/example_graph.png
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch

from pobj.data.graph import build_graph, build_graphs
from pobj.data.megascale import load_labels, load_structures

OUT = Path("results/figures")

labels = load_labels()
structures = load_structures(labels.WT_name.unique())
graphs = build_graphs(structures)
print(f"built {len(graphs)} graphs")

# ---- 1. size statistics over all 298 proteins
nodes = np.array([g.num_nodes for g in graphs.values()])
edges = np.array([g.edge_index.shape[1] for g in graphs.values()])
degree = edges / nodes
print(f"residues per protein: min {nodes.min()}  median {np.median(nodes):.0f}  max {nodes.max()}")
print(f"edges per protein:    min {edges.min()}  median {np.median(edges):.0f}  max {edges.max()}")
print(f"average degree:       min {degree.min():.1f}  median {np.median(degree):.1f}  max {degree.max():.1f}")
print(f"total residues: {nodes.sum():,}   total edges: {edges.sum():,}")

# ---- 2. how much of the graph is NOT visible to a sequence model
seps = torch.cat([(g.edge_index[0] - g.edge_index[1]).abs() for g in graphs.values()])
print(f"\nedges with |i-j| == 1 (chain neighbours): {(seps == 1).float().mean():.1%}")
print(f"edges with |i-j| >  4 (contacts from folding): {(seps > 4).float().mean():.1%}")
dists = torch.cat([(g.pos[g.edge_index[0]] - g.pos[g.edge_index[1]]).norm(dim=-1)
                   for g in graphs.values()])
print(f"edge length: median {dists.median():.1f} A, 99th pct {dists.quantile(0.99):.1f} A, "
      f"max {dists.max():.1f} A")

# ---- 3. one example, printed and drawn
name = sorted(graphs)[0]
g = graphs[name]
print(f"\nexample: {name}")
print(f"  {g.num_nodes} residues, {g.edge_index.shape[1]} edges, degree {g.edge_index.shape[1] / g.num_nodes:.1f}")
print(f"  sequence: {g.seq}")
print(f"  x          {tuple(g.x.shape)}  {g.x[:8].tolist()} ...")
print(f"  node_feat  {tuple(g.node_feat.shape)}")
print(f"  edge_attr  {tuple(g.edge_attr.shape)}")

OUT.mkdir(parents=True, exist_ok=True)
pos = g.pos.numpy()
src, dst = g.edge_index.numpy()
keep = src < dst                                          # draw each undirected edge once
sep = np.abs(src - dst)

fig = plt.figure(figsize=(11, 5))
ax = fig.add_subplot(121, projection="3d")
ax.plot(*pos.T, color="0.3", lw=2)                        # the chain, in order
ax.scatter(*pos.T, s=18, color="crimson", depthshade=False)
ax.set_title(f"{name}\nthe fold ({g.num_nodes} residues)")
ax.set_axis_off()

ax = fig.add_subplot(122, projection="3d")
for a, b in zip(src[keep], dst[keep]):
    far = abs(a - b) > 4
    ax.plot(*pos[[a, b]].T, color="tab:blue" if far else "0.75",
            lw=0.7 if far else 1.6, alpha=0.6 if far else 0.9)
ax.scatter(*pos.T, s=18, color="crimson", depthshade=False)
ax.set_title(f"the graph the model sees\n{g.edge_index.shape[1]} edges, "
             f"blue = contacts with |i-j| > 4 ({(sep > 4).mean():.0%})")
ax.set_axis_off()

fig.tight_layout()
fig.savefig(OUT / "example_graph.png", dpi=150)
print(f"\nwrote {OUT / 'example_graph.png'}")
