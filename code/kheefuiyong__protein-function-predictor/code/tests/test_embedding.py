import pytest

from protein_function_predictor.embedding import ProteinEmbedder


def test_valid_sequence():
    sequence = ProteinEmbedder.validate_sequence("ACDEFGHIK")

    assert sequence == "ACDEFGHIK"


def test_sequence_is_normalized():
    sequence = ProteinEmbedder.validate_sequence(" acd efghik ")

    assert sequence == "ACDEFGHIK"


def test_empty_sequence_raises_error():
    with pytest.raises(ValueError):
        ProteinEmbedder.validate_sequence("")


def test_invalid_amino_acid_raises_error():
    with pytest.raises(ValueError):
        ProteinEmbedder.validate_sequence("ABCDE")


def test_sequence_above_maximum_length_raises_error():
    sequence = "A" * 1025

    try:
        ProteinEmbedder.validate_sequence(
            sequence
        )
    except ValueError as error:
        assert "maximum length" in str(error)
    else:
        raise AssertionError(
            "Expected ValueError."
        )