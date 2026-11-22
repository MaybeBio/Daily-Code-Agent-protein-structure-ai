"""Checks on the MegaScale labels and the structures they refer to.

Labels and structures come from different sources, so these run before anything is
trained: a mismatch here would send every mutation to the wrong residue silently.
"""

import pytest

from pobj.data.megascale import load_labels, load_structures

N_SINGLE = 271_231
N_PROTEINS = 298
PER_SPLIT = {"train": (215_731, 239), "val": (27_328, 31), "test": (28_172, 28)}


@pytest.fixture(scope="module")
def labels():
    return load_labels()


def test_counts(labels):
    """Catches a partial or wrong download before anything is trained on it.

    The ThermoMPNN paper quotes 272,712; the difference is 1,481 wild-type reference rows,
    which load_labels drops.
    """
    assert len(labels) == N_SINGLE
    assert labels.WT_name.nunique() == N_PROTEINS
    for split, (n_mutations, n_proteins) in PER_SPLIT.items():
        part = labels[labels.split == split]
        assert (len(part), part.WT_name.nunique()) == (n_mutations, n_proteins), split


def test_no_duplicate_mutations(labels):
    assert not labels.duplicated(["WT_name", "mut_type"]).any()


def test_split_disjoint(labels):
    """No protein may appear in two splits, or the test set leaks into training."""
    by_split = {sp: set(x.WT_name) for sp, x in labels.groupby("split")}
    for a, b in [("train", "val"), ("train", "test"), ("val", "test")]:
        assert not (by_split[a] & by_split[b]), f"{a} and {b} share proteins"


def test_ddg_sign_is_positive_stabilizing(labels):
    """configs/base.yaml says positive = stabilizing. Most mutations destabilize,
    so the majority of values must be negative."""
    assert 0.70 < (labels.ddG < 0).mean() < 0.85


def test_mutation_alignment(labels):
    """For E12Q, letter 12 of the wild-type sequence must be E.

    Checked against the csv's wt_seq AND the structure, since they come from
    different sources (ThermoMPNN github vs Zenodo).
    """
    structures = load_structures(labels.WT_name.unique())

    bad_seq = bad_struct = 0
    for name, seq, pos, wt_aa in zip(
        labels.WT_name, labels.wt_seq, labels.pos, labels.wt_aa
    ):
        if not (1 <= pos <= len(seq) and seq[pos - 1] == wt_aa):
            bad_seq += 1
        struct_seq, _ = structures[name]
        if not (1 <= pos <= len(struct_seq) and struct_seq[pos - 1] == wt_aa):
            bad_struct += 1
    assert bad_seq == 0 and bad_struct == 0


def test_structures_match_sequences(labels):
    """Structure sequence == csv wt_seq, so node index = pos - 1 with no offset."""
    proteins = labels.drop_duplicates("WT_name")[["WT_name", "wt_seq"]]
    structures = load_structures(proteins.WT_name)
    for name, wt_seq in proteins.itertuples(index=False):
        seq, coords = structures[name]
        assert seq == wt_seq, name
        assert coords.shape == (len(seq), 4, 3), name


def test_mutant_differs_from_wildtype(labels):
    assert (labels.wt_aa == labels.mut_aa).sum() == 0
