import numpy as np
import pandas as pd
import pytest

from protein_function_predictor.modeling import (
    build_baseline_classifier,
    build_feature_matrix,
    build_modeling_arrays,
    encode_labels,
)


def test_encode_labels_respects_vocabulary_order():
    dataframe = pd.DataFrame(
        {
            "labels": [
                "GO:0000002",
                "GO:0000001;GO:0000002",
            ]
        }
    )

    vocabulary = [
        "GO:0000001",
        "GO:0000002",
    ]

    targets = encode_labels(
        dataframe,
        vocabulary,
    )

    expected = np.array(
        [
            [0, 1],
            [1, 1],
        ],
        dtype=np.int8,
    )

    np.testing.assert_array_equal(
        targets,
        expected,
    )


def test_build_feature_matrix_preserves_split_order():
    dataframe = pd.DataFrame(
        {
            "accession": [
                "P3",
                "P1",
            ]
        }
    )

    embedding_accessions = np.array(
        [
            "P1",
            "P2",
            "P3",
        ]
    )

    embeddings = np.array(
        [
            [1.0, 1.0],
            [2.0, 2.0],
            [3.0, 3.0],
        ],
        dtype=np.float32,
    )

    features = build_feature_matrix(
        dataframe,
        embedding_accessions,
        embeddings,
    )

    expected = np.array(
        [
            [3.0, 3.0],
            [1.0, 1.0],
        ],
        dtype=np.float32,
    )

    np.testing.assert_array_equal(
        features,
        expected,
    )


def test_build_feature_matrix_rejects_missing_embedding():
    dataframe = pd.DataFrame(
        {
            "accession": ["P9"]
        }
    )

    embedding_accessions = np.array(
        ["P1"]
    )

    embeddings = np.zeros(
        (1, 2),
        dtype=np.float32,
    )

    with pytest.raises(
        ValueError,
        match="no cached embedding",
    ):
        build_feature_matrix(
            dataframe,
            embedding_accessions,
            embeddings,
        )


def test_build_modeling_arrays():
    dataframe = pd.DataFrame(
        {
            "accession": [
                "P1",
                "P2",
            ],
            "labels": [
                "GO:0000001",
                "GO:0000002",
            ],
        }
    )

    vocabulary = [
        "GO:0000001",
        "GO:0000002",
    ]

    embedding_accessions = np.array(
        [
            "P1",
            "P2",
        ]
    )

    embeddings = np.zeros(
        (2, 320),
        dtype=np.float32,
    )

    features, targets = build_modeling_arrays(
        dataframe,
        vocabulary,
        embedding_accessions,
        embeddings,
    )

    assert features.shape == (2, 320)
    assert targets.shape == (2, 2)


def test_baseline_classifier_produces_multilabel_probabilities():
    features = np.array(
        [
            [0.0, 0.0],
            [0.0, 1.0],
            [1.0, 0.0],
            [1.0, 1.0],
            [2.0, 0.0],
            [2.0, 1.0],
        ]
    )

    targets = np.array(
        [
            [0, 0],
            [0, 1],
            [1, 0],
            [1, 1],
            [1, 0],
            [1, 1],
        ]
    )

    classifier = build_baseline_classifier()

    classifier.fit(
        features,
        targets,
    )

    probabilities = classifier.predict_proba(
        features
    )

    assert probabilities.shape == (6, 2)
    assert np.all(
        (probabilities >= 0.0)
        & (probabilities <= 1.0)
    )