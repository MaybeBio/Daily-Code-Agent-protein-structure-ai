import pandas as pd

from protein_function_predictor.dataset import (
    normalize_sequence,
    parse_go_terms,
    remove_duplicate_sequences,
    remove_invalid_records,
    select_frequent_labels,
)


def test_sequence_normalization():
    assert normalize_sequence(" acd efg ") == "ACDEFG"


def test_invalid_residue_is_removed():
    dataframe = pd.DataFrame(
        {
            "accession": ["P1", "P2"],
            "sequence": ["ACDEFG", "ACDZFG"],
            "go_mf": ["", ""],
        }
    )

    result = remove_invalid_records(dataframe)

    assert result["accession"].tolist() == ["P1"]


def test_empty_sequence_is_removed():
    dataframe = pd.DataFrame(
        {
            "accession": ["P1", "P2"],
            "sequence": ["", "ACDEFG"],
            "go_mf": ["", ""],
        }
    )

    result = remove_invalid_records(dataframe)

    assert result["accession"].tolist() == ["P2"]


def test_go_term_parsing():
    value = (
        "ATP binding [GO:0005524]; "
        "protein kinase activity [GO:0004672]; "
        "ATP binding [GO:0005524]"
    )

    assert parse_go_terms(value) == [
        "GO:0004672",
        "GO:0005524",
    ]


def test_duplicate_sequences_are_removed():
    dataframe = pd.DataFrame(
        {
            "accession": ["P1", "P2", "P3"],
            "sequence": ["ACDE", "ACDE", "FGHI"],
        }
    )

    result = remove_duplicate_sequences(dataframe)

    assert result["accession"].tolist() == ["P1", "P3"]


def test_overlength_sequence_is_removed():
    dataframe = pd.DataFrame(
        {
            "accession": ["P1", "P2"],
            "sequence": ["A" * 1024, "A" * 1025],
            "go_mf": ["", ""],
        }
    )

    result = remove_invalid_records(dataframe)

    assert result["accession"].tolist() == ["P1"]


def test_label_frequency_selection():
    dataframe = pd.DataFrame(
        {
            "go_terms": [
                ["GO:0000001", "GO:0000002"],
                ["GO:0000001"],
                ["GO:0000002"],
                ["GO:0000003"],
            ]
        }
    )

    result = select_frequent_labels(
        dataframe,
        top_k=2,
        min_positives=2,
    )

    assert result == [
        "GO:0000001",
        "GO:0000002",
    ]


def test_label_order_is_deterministic():
    dataframe = pd.DataFrame(
        {
            "go_terms": [
                ["GO:0000002"],
                ["GO:0000001"],
            ]
        }
    )

    result = select_frequent_labels(
        dataframe,
        top_k=2,
        min_positives=1,
    )

    assert result == [
        "GO:0000001",
        "GO:0000002",
    ]