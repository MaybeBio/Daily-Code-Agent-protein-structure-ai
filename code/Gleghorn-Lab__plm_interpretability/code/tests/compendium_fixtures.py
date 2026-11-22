"""A synthetic compendium release in the shapes `plm_interpretability.units.compendium` reads, and the atlas set built from it."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dataclasses import dataclass
from pathlib import Path
from annotation_vocabulary.compendium.views import DISORDERED

from plm_interpretability.units import atlas_set, compendium, split
from plm_interpretability.units.intrinsic import AMINO_ACIDS


SITE = "av::local_modified_residue::UniProtKB-PTM::PTM-0253"
TERMS = pd.DataFrame([
    # term_id, aspect, fundamental_aspect, source_database, accession, name
    ("av::go_mf::GO::GO:0000001", "go_mf", "enzyme", "GO", "GO:0000001", "catalysis"),
    ("av::go_mf::GO::GO:0000002", "go_mf", "enzyme", "GO", "GO:0000002", "kinase"),
    ("av::go_bp::GO::GO:0000003", "go_bp", "process_pathway", "GO", "GO:0000003", "signalling"),
    (DISORDERED, "local_region", "domain_family", "UniProtKB-FT", "Disordered", "Disordered"),
    ("av::local_binding::ChEBI::CHEBI:0001", "local_binding", "molecular_function", "ChEBI", "CHEBI:0001", "zinc"),
    (SITE, "local_modified_residue", "ptm_processing", "UniProtKB-PTM", "PTM-0253", "Phosphoserine"),
    ("av::local_interpro::InterPro::IPR000001", "local_interpro", "domain_family", "InterPro", "IPR000001", "kinase domain"),
    ("av::interpro::InterPro::IPR000001", "interpro", "domain_family", "InterPro", "IPR000001", "kinase domain"),
    ("av::taxonomy::NCBITaxon::9606", "taxonomy", "organism", "NCBITaxon", "9606", "Homo sapiens"),
], columns=["term_id", "aspect", "fundamental_aspect", "source_database", "accession", "name"])
HIERARCHY = pd.DataFrame({"child_database": ["GO", "InterPro"], "child": ["GO:0000002", "IPR000001"],
                          "parent_database": ["GO", "InterPro"], "parent": ["GO:0000001", "IPR999999"],
                          "relation": ["is_a", "is_a"]})


@dataclass
class Release:
    words: compendium.Vocabulary
    pool: pd.DataFrame
    examined: frozenset[str]
    proteins: pd.DataFrame
    rows: pd.DataFrame
    located: pd.DataFrame
    sites: pd.DataFrame
    disorder: pd.DataFrame
    assertions: pd.DataFrame


def release(seed: int = 0, n_clusters: int = 60, members: int = 3) -> Release:
    """Clusters of proteins across the four splits with labels, masked labels, units and residue tables."""
    rng = np.random.default_rng(seed)
    tokens = pd.DataFrame({"term_id": TERMS["term_id"], "token": np.arange(len(TERMS), dtype=np.int32)})
    words = compendium.vocabulary(TERMS, tokens, {SITE: "S"})
    proteins, pool, rows, located, sites, disorder, assertions = [], [], [], [], [], [], []
    names = ("train",) * 6 + ("validation", "test", "calibration")
    for cluster in range(n_clusters):
        name = names[cluster % len(names)]
        for member in range(members):
            protein = f"p{cluster:03d}{member}"
            length = int(rng.integers(40, 80))
            sequence = "".join(rng.choice(list(AMINO_ACIDS), size=length))
            serines = [index + 1 for index, letter in enumerate(sequence) if letter == "S"]
            accession = f"P{cluster:03d}{member}"
            proteins.append({"protein_id": protein, "primary_accession": accession, "sequence": sequence,
                             "reviewed": member != 2})
            pool.append({"protein_id": protein, "accessions": [accession], "split": name, "eligible": member != 1,
                         "reviewed": member != 2, "cluster": f"c{cluster}"})
            held = [0, 1] if rng.random() < 0.5 else [0]
            rows.append({"protein_id": protein, "tokens": [*held, 7, 8], "masked": ["av::go_bp::GO::GO:0000003", "unknown"],
                         "observed_units": ["go_mf/enzyme", "interpro/domain_family", "taxonomy/organism"]})
            located.append({"protein_id": protein, "split": name, "features": [
                {"feature": "av::local_binding::ChEBI::CHEBI:0001", "residues": [{"start": 3, "end": 5}],
                 "masked": [{"start": 10, "end": 12}]}]})
            if len(serines) >= 3:
                sites.append({"protein_id": protein, "split": name, "sites": [
                    {"modification": SITE, "residue": "S", "positions": [serines[0]], "masked": [serines[1]]}]})
            if member == 0:
                disorder.append({"protein_id": protein, "split": name, "disordered": list(range(1, 9)), "masked": [9, 10]})
            assertions.append({"protein_id": protein, "term_id": "av::local_interpro::InterPro::IPR000001",
                               "aspect": "local_interpro", "tier": "signature", "negated": False, "start": 20, "end": 30})
            assertions.append({"protein_id": protein, "term_id": "av::local_interpro::InterPro::IPR000001",
                               "aspect": "local_interpro", "tier": "signature", "negated": False, "start": 70, "end": length + 5})
    return Release(words, pd.DataFrame(pool), frozenset({"P0060", "P0070"}), pd.DataFrame(proteins), pd.DataFrame(rows),
                   pd.DataFrame(located), pd.DataFrame(sites), pd.DataFrame(disorder), pd.DataFrame(assertions))


def write_release(found: Release, folder: Path) -> tuple[Path, Path]:
    """The release in its Hub layout (`compendium.RELEASE_FILES`) and the atlas study's held-out shards beside it."""
    tables = folder / "release" / "tables"
    tables.mkdir(parents=True)
    split_of = dict(zip(found.pool["protein_id"], found.pool["split"], strict=True))
    for name in split.SPLITS:
        found.rows[found.rows["protein_id"].map(split_of) == name].to_parquet(folder / "release" / f"{name}.parquet", index=False)
    found.pool[["protein_id", "split", "eligible"]].to_parquet(tables / "split.parquet", index=False)
    found.proteins.merge(found.pool[["protein_id", "accessions"]], on="protein_id").to_parquet(tables / "proteins.parquet", index=False)
    found.pool[["protein_id", "cluster"]].rename(columns={"cluster": split.CLUSTER_LEVEL}).to_parquet(tables / "clusters.parquet",
                                                                                                      index=False)
    TERMS.to_parquet(tables / "vocabulary.parquet", index=False)
    pd.DataFrame({"term_id": TERMS["term_id"], "token": np.arange(len(TERMS), dtype=np.int32)}).to_parquet(
        tables / "tokens.parquet", index=False)
    HIERARCHY.to_parquet(tables / "hierarchy.parquet", index=False)
    for name, frame in (("located_features", found.located), ("modification_sites", found.sites),
                        ("disordered_regions", found.disorder), ("assertions", found.assertions)):
        frame.to_parquet(tables / f"{name}.parquet", index=False)
    shards = folder / "examined" / "data"
    shards.mkdir(parents=True)
    examined = sorted(found.examined)
    for index, name in enumerate(("validation", "test")):
        pd.DataFrame({"accession": examined[index::2]}).to_parquet(shards / f"{name}-00000-of-00001.parquet", index=False)
    return folder / "release", folder / "examined"


SIZES = {"validation": 6, "calibration": 4}


def build(seed: int = 0, n_clusters: int = 60, members: int = 3) -> tuple[atlas_set.AtlasSet, Release]:
    """The atlas set of a synthetic release, through every reader of `compendium`."""
    found = release(seed, n_clusters, members)
    sample = split.atlas_sample(found.pool, found.examined, sizes=SIZES)
    chosen = set(sample["protein_id"])
    lengths = dict(zip(found.proteins["protein_id"], found.proteins["sequence"].str.len(), strict=True))
    spans = compendium.signature_spans(found.assertions, {protein: lengths[protein] for protein in chosen},
                                       found.words.terms["term_id"]).spans
    local = compendium.local_runs(found.located[found.located["protein_id"].isin(chosen)],
                                  found.sites[found.sites["protein_id"].isin(chosen)],
                                  found.disorder[found.disorder["protein_id"].isin(chosen)], spans, found.words)
    labels = compendium.global_labels(found.rows[found.rows["protein_id"].isin(chosen)], found.words)
    return atlas_set.build_atlas_set(sample, found.proteins, labels, local, found.words), found
