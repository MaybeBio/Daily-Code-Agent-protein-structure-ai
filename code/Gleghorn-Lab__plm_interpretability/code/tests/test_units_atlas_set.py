from __future__ import annotations

import numpy as np

import compendium_fixtures as fixtures

from annotation_vocabulary.compendium.views import DISORDERED

from plm_interpretability.units import atlas_set, intrinsic


def test_atlas_set_joins_labels_and_counts_informative_proteins() -> None:
    built, found = fixtures.build()
    proteins = built.proteins
    token_of = found.words.token_of()
    assert built.vocabulary_size == len(fixtures.TERMS) and built.intrinsic_tokens["residue:A"] == len(fixtures.TERMS)
    assert built.scopes == {token_of[fixtures.SITE]: intrinsic.AMINO_ACIDS.index("S")}
    train = proteins[proteins["split"] == "train"]
    n_train = len(train)
    binding = token_of["av::local_binding::ChEBI::CHEBI:0001"]
    assert built.informative[binding] == n_train  # every training protein holds a binding run and the rest of its chain
    disordered = token_of[DISORDERED]
    assert built.informative[disordered] == int(train["local_term_ids"].map(lambda tokens: disordered in set(tokens)).sum())
    site = token_of[fixtures.SITE]
    assert 0 < built.informative[site] <= n_train
    columns = built.term_columns(1)
    assert {binding, site} <= set(columns) and list(columns.values()) == list(range(len(columns)))
    labels = built.labels("train")
    assert labels.positives.shape == (n_train, built.vocabulary_size)
    assert int(labels.positives[:, 0].sum()) == n_train  # every protein holds the catalysis term
    assert labels.masked.nnz == 0  # the masked process term lies outside every protein's units
    assert int(labels.positives[:, len(fixtures.TERMS) - 1].sum()) == 0  # the organism term is never a label


def test_intrinsic_annotations_are_appended_under_their_tokens() -> None:
    built, _ = fixtures.build()
    row = built.proteins.iloc[0]
    runs = atlas_set.local_runs(row)
    for term, spans in intrinsic.intrinsic_terms(row["sequence"]).items():
        token = built.intrinsic_tokens[term]
        found = sorted(zip(runs.starts[runs.tokens == token].tolist(), runs.ends[runs.tokens == token].tolist(), strict=True))
        assert found == sorted(spans)


def test_local_ancestors_keep_their_order() -> None:
    import scipy.sparse as sp

    ancestors = sp.csr_matrix(np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=bool))  # 1 under 0, 2 under 1
    local = atlas_set.local_ancestors(ancestors, [2, 1, 5]).toarray()  # (3, 3); 5 lies past the vocabulary
    assert local.tolist() == [[False, True, False], [False, False, False], [False, False, False]]


def test_pass_proteins_and_their_subsets() -> None:
    built, _ = fixtures.build()
    proteins = built.proteins
    whole = atlas_set.pass_proteins(proteins)
    assert set(whole.split) == {"train", "validation", "test"}
    assert len(whole.accession) == int((proteins["split"] != "calibration").sum())
    assert atlas_set.calibration_sequences(proteins) == proteins.loc[proteins["split"] == "calibration", "sequence"].tolist()
    subset = atlas_set.pass_proteins(proteins, subset=40)
    assert abs(len(subset.accession) - 40) <= 3
    assert set(subset.accession) <= set(whole.accession)
    assert subset.accession == atlas_set.pass_proteins(proteins, subset=40).accession  # seeded
    first = whole.accession.index(subset.accession[0])
    assert np.array_equal(subset.local[0].tokens, whole.local[first].tokens)
    assert np.array_equal(subset.local[0].masked_starts, whole.local[first].masked_starts)
    binding = fixtures.release().words.token_of()["av::local_binding::ChEBI::CHEBI:0001"]
    presence = atlas_set.local_presence(proteins, [binding, 99])  # (n, 2)
    assert presence.shape == (len(proteins), 2)
    assert presence[:, 0].sum() == len(proteins) and presence[:, 1].sum() == 0


def test_residue_budget_cuts_a_seeded_order_of_training_proteins() -> None:
    proteins = fixtures.build()[0].proteins
    chosen = atlas_set.residue_budget_proteins(proteins, 1_000)
    assert set(chosen.split) == {"train"} and chosen.lengths.sum() >= 1_000
    assert chosen.lengths.sum() - chosen.lengths.max() < 1_000  # the cut falls at the protein that reached the budget
    again = atlas_set.residue_budget_proteins(proteins, 1_000)
    assert again.accession == chosen.accession  # seeded
    assert atlas_set.residue_budget_proteins(proteins, 1_000, seed=1).accession != chosen.accession
    train = proteins[proteins["split"] == "train"]
    everything = atlas_set.residue_budget_proteins(proteins, 10**9)
    assert len(everything.accession) == len(train)
    order = {accession: row for row, accession in enumerate(proteins["accession"])}
    assert [order[accession] for accession in chosen.accession] == sorted(order[accession] for accession in chosen.accession)
