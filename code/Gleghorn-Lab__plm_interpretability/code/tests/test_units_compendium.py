from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import compendium_fixtures as fixtures

from pathlib import Path
from annotation_vocabulary.compendium.views import DISORDERED, TYPE_TERMS

from plm_interpretability.units import atlas_set, compendium, split
from plm_interpretability.units.intrinsic import AMINO_ACIDS


def test_vocabulary_gives_units_scopes_and_leaves_organism_out() -> None:
    words = fixtures.release().words
    terms = words.terms.set_index("term_id")
    assert "taxonomy/organism" not in words.units and terms.loc["av::taxonomy::NCBITaxon::9606", "unit"] == -1
    assert words.units[terms.loc["av::go_mf::GO::GO:0000001", "unit"]] == "go_mf/enzyme"
    assert terms.loc[fixtures.SITE, "scope"] == AMINO_ACIDS.index("S")
    assert terms.loc[DISORDERED, "scope"] == compendium.CHAIN and bool(terms.loc[DISORDERED, "is_local"])
    assert not bool(terms.loc["av::go_bp::GO::GO:0000003", "is_local"])
    with pytest.raises(ValueError):
        compendium.vocabulary(fixtures.TERMS, pd.DataFrame({"term_id": fixtures.TERMS["term_id"], "token": np.arange(1, 10)}), {})


def test_global_labels_drop_organism_and_observe_every_positive() -> None:
    found = fixtures.release()
    rows = pd.DataFrame({"protein_id": ["a"], "tokens": [[1, 8]], "masked": [["av::go_mf::GO::GO:0000001", "unknown"]],
                         "observed_units": [["taxonomy/organism"]]})
    labels = compendium.global_labels(rows, found.words).iloc[0]
    assert labels["annotations"].tolist() == [1]  # the organism token is left out
    assert labels["masked"].tolist() == [0]  # a masked term that is not a token is dropped
    assert labels["units"].tolist() == [found.words.units.index("go_mf/enzyme")]  # the positive's unit is observed


def test_local_runs_and_signature_spans() -> None:
    found = fixtures.release()
    lengths = dict(zip(found.proteins["protein_id"], found.proteins["sequence"].str.len(), strict=True))
    rare = found.assertions.iloc[:2].assign(term_id="av::local_interpro::InterPro::IPR999999")  # no token: under 10 carriers
    signatures = compendium.signature_spans(pd.concat([found.assertions, rare], ignore_index=True), lengths,
                                            found.words.terms["term_id"])
    spans = signatures.spans
    # each protein's span past its end is left out, and so are the rare term's spans
    assert signatures.off_sequence == len(found.proteins) + int((rare["end"] > rare["protein_id"].map(lengths)).sum())
    assert len(spans) == len(found.proteins) and not spans["term_id"].eq("av::local_interpro::InterPro::IPR999999").any()
    assert signatures.terms_outside_vocabulary == 1 and signatures.outside_vocabulary == int(
        (rare["end"] <= rare["protein_id"].map(lengths)).sum())
    local = compendium.local_runs(found.located, found.sites, found.disorder, spans, found.words).set_index("protein_id")
    token_of = found.words.token_of()
    row = local.loc["p0000"]
    pairs = list(zip(row["local_term_ids"].tolist(), row["local_starts"].tolist(), row["local_ends"].tolist(), strict=True))
    assert (token_of[DISORDERED], 1, 8) in pairs and (token_of["av::local_binding::ChEBI::CHEBI:0001"], 3, 5) in pairs
    assert (token_of["av::local_interpro::InterPro::IPR000001"], 20, 30) in pairs
    masked = list(zip(row["masked_term_ids"].tolist(), row["masked_starts"].tolist(), row["masked_ends"].tolist(), strict=True))
    assert (token_of[DISORDERED], 9, 10) in masked and (token_of["av::local_binding::ChEBI::CHEBI:0001"], 10, 12) in masked
    assert compendium.runs_of([5, 3, 4, 9, 9]) == [(3, 5), (9, 9)]


def test_readers_rebuild_the_atlas_set_from_a_release_folder(tmp_path: Path) -> None:
    built, found = fixtures.build()
    folder, examined_folder = fixtures.write_release(found, tmp_path)
    examined = compendium.read_examined(examined_folder)
    assert examined == found.examined
    sample = split.atlas_sample(compendium.read_pool(folder), examined, sizes=fixtures.SIZES)
    assert split.assignment_digest(sample) == built.digest
    words, hierarchy = compendium.read_vocabulary(folder)
    assert words.units == found.words.units
    assert words.terms[["token", "unit", "scope"]].astype(int).equals(found.words.terms[["token", "unit", "scope"]].astype(int))
    chosen = set(sample["protein_id"])
    proteins = compendium.read_proteins(folder, chosen, atlas_set.PROTEIN_COLUMNS)
    lengths = dict(zip(proteins["protein_id"], proteins["sequence"].str.len(), strict=True))
    signatures = compendium.signature_spans(compendium.read_signature_assertions(folder, chosen), lengths, words.terms["term_id"])
    assert signatures.off_sequence == len(chosen)  # the fixture's second span of each protein runs past its end
    assert signatures.outside_vocabulary == 0
    local = compendium.local_runs(*compendium.read_residue_tables(folder, chosen), signatures.spans, words)
    labels = compendium.global_labels(compendium.read_rows(folder, chosen), words)
    rebuilt = atlas_set.build_atlas_set(sample, proteins, labels, local, words)
    assert rebuilt.informative == built.informative and rebuilt.scopes == built.scopes
    assert rebuilt.proteins[["protein_id", "accession", "split"]].equals(built.proteins[["protein_id", "accession", "split"]])
    for column in ("annotations", "masked", "units", *compendium.LOCAL_COLUMNS):
        assert all(np.array_equal(first, second) for first, second
                   in zip(rebuilt.proteins[column], built.proteins[column], strict=True)), column
    assert compendium.ancestor_matrix(words, hierarchy).nnz == compendium.ancestor_matrix(found.words, fixtures.HIERARCHY).nnz
    with pytest.raises(ValueError, match="shards"):
        compendium.read_examined(tmp_path)


def test_site_classes_sit_on_one_amino_acid() -> None:
    sites = pd.DataFrame({"sites": [[{"modification": "m", "residue": "S"}], [{"modification": "m", "residue": "T"}]]})
    with pytest.raises(ValueError):
        compendium.site_residues(sites)
    assert compendium.site_residues(sites.iloc[:1]) == {"m": "S"}


def test_ancestors_follow_edges_concepts_and_type_terms() -> None:
    words = fixtures.release().words
    token_of = words.token_of()
    ancestors = compendium.ancestor_matrix(words, fixtures.HIERARCHY).toarray()
    kinase, catalysis = token_of["av::go_mf::GO::GO:0000002"], token_of["av::go_mf::GO::GO:0000001"]
    assert ancestors[kinase, catalysis] and not ancestors[catalysis, kinase]
    located, protein = token_of["av::local_interpro::InterPro::IPR000001"], token_of["av::interpro::InterPro::IPR000001"]
    assert ancestors[located, protein] and ancestors[protein, located]  # one concept read two ways
    table = pd.concat([fixtures.TERMS, pd.DataFrame([(TYPE_TERMS["local_binding"], "local_binding", "molecular_function",
                                                      "UniProtKB-FT", "Binding site", "Binding site")],
                                                    columns=fixtures.TERMS.columns)], ignore_index=True)
    typed = compendium.vocabulary(table, pd.DataFrame({"term_id": table["term_id"], "token": np.arange(len(table))}), {})
    typed_ancestors = compendium.ancestor_matrix(typed, fixtures.HIERARCHY).toarray()
    zinc, binding = typed.token_of()["av::local_binding::ChEBI::CHEBI:0001"], typed.token_of()[TYPE_TERMS["local_binding"]]
    assert typed_ancestors[zinc, binding] and not typed_ancestors[binding, zinc]
