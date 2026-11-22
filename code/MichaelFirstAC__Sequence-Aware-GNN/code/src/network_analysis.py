"""
Phase 7 (part 1): Topological characterization of the PrimeKG PPI graph.
Saves results/network_stats.csv, results/top10_hubs.csv and
results/figures/degree_distribution.png (log-log, 300 DPI).
Only needs pandas/networkx/matplotlib (no torch).
"""
import os
import re
import numpy as np
import pandas as pd
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yaml


def load_gene_symbols(fasta_path):
    """Map UniProt accession -> gene symbol (GN=) and protein name from FASTA headers."""
    sym, name = {}, {}
    with open(fasta_path) as f:
        for line in f:
            if not line.startswith(">"):
                continue
            m = re.match(r">\w+\|([^|]+)\|\S+\s+(.*?)\s+OS=", line)
            gn = re.search(r"GN=(\S+)", line)
            if m:
                acc = m.group(1)
                name[acc] = m.group(2)
                sym[acc] = gn.group(1) if gn else "NA"
    return sym, name


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    proc, res, figs = cfg["data"]["processed_dir"], cfg["data"]["results_dir"], cfg["data"]["figures_dir"]
    os.makedirs(figs, exist_ok=True)

    df = pd.read_csv(os.path.join(proc, "ppi_edges_uniprot.csv"))
    G = nx.Graph()
    G.add_edges_from(zip(df["uniprot1"], df["uniprot2"]))
    G.remove_edges_from(nx.selfloop_edges(G))

    deg = np.array([d for _, d in G.degree()])
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    stats = {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "density": nx.density(G),
        "degree_mean": deg.mean(),
        "degree_median": float(np.median(deg)),
        "degree_std": deg.std(ddof=0),
        "degree_max": int(deg.max()),
        "avg_clustering": nx.average_clustering(G),
        "transitivity": nx.transitivity(G),
        "n_connected_components": len(comps),
        "largest_cc_size": len(comps[0]),
        "largest_cc_fraction": len(comps[0]) / G.number_of_nodes(),
        "isolated_nodes": sum(1 for c in comps if len(c) == 1),
    }
    pd.DataFrame([stats]).T.rename(columns={0: "value"}).to_csv(os.path.join(res, "network_stats.csv"))
    for k, v in stats.items():
        print(f"{k:24s} {v}")

    sym, name = load_gene_symbols(cfg["data"]["raw_dir"] + "/protein_sequences.fasta")
    top = sorted(G.degree(), key=lambda t: t[1], reverse=True)[:10]
    hubs = pd.DataFrame([{"rank": i + 1, "uniprot": u, "gene_symbol": sym.get(u, "NA"),
                          "protein_name": name.get(u, "NA"), "degree": d} for i, (u, d) in enumerate(top)])
    hubs.to_csv(os.path.join(res, "top10_hubs.csv"), index=False)
    print("\nTop-10 hubs:\n", hubs.to_string(index=False))

    # Degree distribution (log-log): P(k) on log-spaced bins + raw histogram
    ks, counts = np.unique(deg, return_counts=True)
    fig, ax = plt.subplots(1, 2, figsize=(7.16, 3.0))  # IEEE double-column width
    ax[0].loglog(ks, counts / counts.sum(), "o", ms=3, alpha=0.7)
    ax[0].set_xlabel("Degree $k$"); ax[0].set_ylabel("$P(k)$"); ax[0].set_title("Degree distribution")
    srt = np.sort(deg)[::-1]
    ccdf = np.arange(1, len(srt) + 1) / len(srt)
    ax[1].loglog(srt, ccdf, "-", lw=1.5)
    ax[1].set_xlabel("Degree $k$"); ax[1].set_ylabel("$P(K \\geq k)$"); ax[1].set_title("CCDF")
    for a in ax:
        a.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(figs, "degree_distribution.png"), dpi=300)
    print("saved figure")


if __name__ == "__main__":
    main()
