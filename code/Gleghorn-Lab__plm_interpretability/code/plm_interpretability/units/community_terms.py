"""Curated annotation at the predictions a neuron community explains, beyond what its residue alone carries.

    python -m plm_interpretability.units.community_terms --root RUN --out TABLE.csv

Reads the community tests of the neuron study's archive (`RUN/communities/tests`) and its vocabulary (`RUN/inputs`).
A community that predicts one residue would look enriched for every term common at that residue, so each of the
communities that explain the most held-out predictions is compared within its most predicted residue: the predictions
it explains against every other tested prediction of that residue. For each curated term a prediction of that residue
carries, a one-sided Fisher's exact test asks whether the community's predictions carry it more often, and the
Benjamini-Hochberg procedure runs over every community and term. The test was added after the community tests and is
not among the study's readings fixed in advance.

Symbols: n tested predictions of one residue; t tests (one a community and a term).
"""

from __future__ import annotations

import argparse
import json
import pandas as pd

from pathlib import Path
from scipy.stats import false_discovery_control, hypergeom


DISCOVERED = "discovered"  # the dictionary of discovered communities, beside the shuffled ones
COMMUNITIES = 30  # the communities that explain the most predictions, as the study's record describes them
LEVEL = 0.05  # the false discovery rate over every community and term
COLUMNS = ("community", "residue", "explained", "others", "term", "explained_with", "others_with", "p_value")


def explained_predictions(results: pd.DataFrame) -> pd.DataFrame:
    """One row for each prediction a discovered community explains, with that community."""
    # results: the community tests' `results.parquet`, one row a prediction, dictionary, community and span
    found = results[(results["dictionary"] == DISCOVERED) & results["explains"]]
    return found[["community", "prompt"]].drop_duplicates().reset_index(drop=True)


def term_tests(prompts: pd.DataFrame, explained: pd.DataFrame, curated: set[int],
               communities: int = COMMUNITIES) -> pd.DataFrame:
    """One row for each of the most used communities and each curated term carried at its most predicted residue: how
    many of the community's predictions of that residue and of the other tested predictions of it carry the term, and
    the one-sided Fisher's exact p-value that the community's carry it more often."""
    # prompts: the community tests' `prompts.parquet`, indexed by prediction; explained: `explained_predictions`
    most_used = explained.groupby("community")["prompt"].nunique().sort_values(ascending=False, kind="stable")
    tables = []
    for community in most_used.index[:communities]:
        chosen = prompts.loc[explained.loc[explained["community"] == community, "prompt"]]
        residue = chosen["predicted_residue"].value_counts().index[0]
        stratum = prompts[prompts["predicted_residue"] == residue]
        inside = stratum.index.isin(chosen.index)  # (n,): the community explains this prediction of the residue
        carried = stratum["local_terms"].explode().dropna().astype(int)  # one row a prediction and a term it carries
        carried = carried[carried.isin(curated)]
        with_term = carried.groupby(carried).size()  # (t,): predictions of the residue that carry each term
        explained_with = carried[carried.index.isin(stratum.index[inside])]
        explained_with = explained_with.groupby(explained_with).size().reindex(with_term.index, fill_value=0)  # (t,)
        # P(X >= explained_with) for X the carriers among `inside.sum()` predictions drawn from the residue's `n`.
        p_values = hypergeom.sf(explained_with.to_numpy() - 1, len(stratum), with_term.to_numpy(), int(inside.sum()))  # (t,)
        tables.append(pd.DataFrame({
            "community": community, "residue": residue, "explained": int(inside.sum()),
            "others": int((~inside).sum()), "term": with_term.index.to_numpy(),
            "explained_with": explained_with.to_numpy(),
            "others_with": with_term.to_numpy() - explained_with.to_numpy(), "p_value": p_values}))
    return pd.concat(tables, ignore_index=True)[list(COLUMNS)]


def enrichment_table(prompts: pd.DataFrame, results: pd.DataFrame, labels: dict[int, str], curated: set[int],
                     communities: int = COMMUNITIES) -> pd.DataFrame:
    """`term_tests` with each term's label, the share of each group that carries it and the Benjamini-Hochberg
    q-value over every community and term, most significant first."""
    table = term_tests(prompts, explained_predictions(results), curated, communities)
    table["q_value"] = false_discovery_control(table["p_value"].to_numpy(), method="bh")  # (t,)
    table["explained_share"] = table["explained_with"] / table["explained"]
    table["others_share"] = table["others_with"] / table["others"]
    table["label"] = table["term"].map(labels)
    return table.sort_values(["q_value", "p_value"], kind="stable").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, required=True, help="The neuron study's archive.")
    parser.add_argument("--out", type=Path, required=True, help="The table of every test, as CSV.")
    arguments = parser.parse_args()
    tests, inputs = arguments.root / "communities" / "tests", arguments.root / "inputs"
    prompts = pd.read_parquet(tests / "prompts.parquet").reset_index(drop=True)
    results = pd.read_parquet(tests / "results.parquet", columns=["prompt", "dictionary", "community", "explains"])
    terms = pd.read_parquet(inputs / "terms.parquet", columns=["token", "label", "aspect"])
    intrinsic = json.loads((inputs / "atlas_set.json").read_text(encoding="utf-8"))["intrinsic_tokens"]
    curated = set(terms["token"].astype(int)) - {int(token) for token in intrinsic.values()}
    labels = (terms["aspect"] + ": " + terms["label"]).set_axis(terms["token"].astype(int)).to_dict()
    table = enrichment_table(prompts, results, labels, curated)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(arguments.out, index=False)
    enriched = table[table["q_value"] < LEVEL]
    print(json.dumps({
        "tests": int(len(table)), "communities": int(table["community"].nunique()),
        "enriched_tests": int(len(enriched)), "enriched_communities": int(enriched["community"].nunique()),
        "largest_explained_share_enriched": float(enriched["explained_share"].max()) if len(enriched) else None,
        "smallest_p_value": float(table["p_value"].min()), "smallest_q_value": float(table["q_value"].min())}, indent=2))


if __name__ == "__main__":
    main()
