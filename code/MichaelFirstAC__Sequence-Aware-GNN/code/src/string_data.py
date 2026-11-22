"""
Phase 8 (part 1): Build the STRING v12.0 physical-PPI graph restricted to proteins shared with PrimeKG.

Inputs (config.yaml -> string:, plus data/raw/9606.protein.aliases.v12.0.txt.gz):
  * physical links  (protein1 protein2 combined_score, space-separated, gz)
  * aliases         (#string_protein_id <TAB> alias <TAB> source, gz)
  * data/processed/ppi_edges_uniprot.csv  (defines the PrimeKG protein set)
Outputs:
  data/processed/string_edges_uniprot.csv   columns: uniprot1, uniprot2, combined_score
  results/string_mapping_report.csv         counts at each filtering step

Because only PrimeKG proteins are kept, the cached ESM-2 / classical features
(keyed by UniProt accession) are reused directly -- no re-embedding needed.
Edges are deduplicated as undirected pairs and self-loops are removed.
"""
import os
import re
import pandas as pd
from utils import load_config, setup_logger

logger = setup_logger("string_data")

# UniProt accession pattern (official regex, isoform suffix not allowed here)
UNIPROT_RE = re.compile(
    r"^([OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})$"
)


def load_primekg_proteins(edges_path):
    df = pd.read_csv(edges_path)
    return set(df["uniprot1"]).union(df["uniprot2"])


def load_alias_map(aliases_path, keep_accessions):
    """
    STRING protein id -> set of UniProt accessions that are in `keep_accessions`.
    Any alias that looks like a UniProt accession and is a PrimeKG protein is used,
    regardless of the STRING 'source' label (labels differ between STRING releases).
    """
    logger.info(f"Reading aliases: {aliases_path}")
    al = pd.read_csv(aliases_path, sep="\t", compression="infer", dtype=str,
                     names=["string_id", "alias", "source"], header=0)
    al = al.dropna(subset=["string_id", "alias"])
    al = al[al["alias"].isin(keep_accessions)]
    al = al[al["alias"].map(lambda a: bool(UNIPROT_RE.match(a)))]
    al = al.drop_duplicates(["string_id", "alias"])
    mapping = al.groupby("string_id")["alias"].apply(set).to_dict()
    return mapping


def build_string_edges(links_path, aliases_path, primekg_edges_path, threshold):
    keep = load_primekg_proteins(primekg_edges_path)
    report = {"primekg_proteins": len(keep)}

    logger.info(f"Reading links: {links_path}")
    links = pd.read_csv(links_path, sep=" ", compression="infer",
                        dtype={"protein1": str, "protein2": str, "combined_score": int})
    report["string_link_rows_total"] = len(links)
    links = links[links["combined_score"] >= threshold]
    report[f"string_link_rows_score>={threshold}"] = len(links)

    amap = load_alias_map(aliases_path, keep)
    report["string_ids_mapped_to_primekg"] = len(amap)
    report["string_ids_ambiguous(>1 accession)"] = sum(len(v) > 1 for v in amap.values())

    rows = []
    for p1, p2, s in zip(links["protein1"], links["protein2"], links["combined_score"]):
        a1, a2 = amap.get(p1), amap.get(p2)
        if not a1 or not a2:
            continue
        for u in a1:
            for v in a2:
                if u != v:
                    rows.append((min(u, v), max(u, v), s))
    out = pd.DataFrame(rows, columns=["uniprot1", "uniprot2", "combined_score"])
    out = out.sort_values("combined_score", ascending=False).drop_duplicates(["uniprot1", "uniprot2"])
    out = out.sort_values(["uniprot1", "uniprot2"]).reset_index(drop=True)

    nodes = set(out["uniprot1"]).union(out["uniprot2"])
    report["final_undirected_edges"] = len(out)
    report["final_nodes"] = len(nodes)
    report["primekg_proteins_missing_from_string_graph"] = len(keep - nodes)
    return out, report


def main():
    cfg = load_config("config.yaml")
    s, d = cfg["string"], cfg["data"]
    aliases = os.path.join(d["raw_dir"], f"{s['taxon_id']}.protein.aliases.v12.0.txt.gz")
    for p in (s["raw_links_path"], aliases, os.path.join(d["processed_dir"], "ppi_edges_uniprot.csv")):
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing input file: {p}")

    edges, report = build_string_edges(
        s["raw_links_path"], aliases,
        os.path.join(d["processed_dir"], "ppi_edges_uniprot.csv"), s["score_threshold"])

    out_path = os.path.join(d["processed_dir"], "string_edges_uniprot.csv")
    edges.to_csv(out_path, index=False)
    pd.Series(report, name="value").to_csv(os.path.join(d["results_dir"], "string_mapping_report.csv"),
                                           index_label="step")
    for k, v in report.items():
        print(f"{k:50s} {v}")
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
