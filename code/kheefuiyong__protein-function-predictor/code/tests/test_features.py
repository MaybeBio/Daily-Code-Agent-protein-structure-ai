import numpy as np

from protein_function_predictor.features import (
    load_embeddings,
    save_embeddings,
)


def test_embedding_round_trip(
    tmp_path,
):
    path = tmp_path / "embeddings.npz"

    accessions = [
        "P00001",
        "P00002",
    ]

    embeddings = np.array(
        [
            [1.0, 2.0, 3.0],
            [4.0, 5.0, 6.0],
        ],
        dtype=np.float32,
    )

    save_embeddings(
        path,
        accessions,
        embeddings,
    )

    loaded_accessions, loaded_embeddings = (
        load_embeddings(path)
    )

    assert loaded_accessions.tolist() == accessions

    np.testing.assert_array_equal(
        loaded_embeddings,
        embeddings,
    )


def test_save_embeddings_rejects_length_mismatch(
    tmp_path,
):
    path = tmp_path / "embeddings.npz"

    accessions = [
        "P00001",
    ]

    embeddings = np.zeros(
        (2, 320),
        dtype=np.float32,
    )

    try:
        save_embeddings(
            path,
            accessions,
            embeddings,
        )
    except ValueError as error:
        assert (
            "does not match"
            in str(error)
        )
    else:
        raise AssertionError(
            "Expected ValueError."
        )