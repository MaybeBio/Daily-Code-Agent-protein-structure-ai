import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def encode_labels(
    dataframe: pd.DataFrame,
    vocabulary: list[str],
) -> np.ndarray:
    """Encode semicolon-separated GO labels as a binary matrix."""

    vocabulary_index = {
        label: index
        for index, label in enumerate(vocabulary)
    }

    targets = np.zeros(
        (len(dataframe), len(vocabulary)),
        dtype=np.int8,
    )

    for row_index, value in enumerate(dataframe["labels"]):
        labels = set(str(value).split(";"))

        unknown = labels - set(vocabulary)

        if unknown:
            raise ValueError(
                "Unknown labels encountered: "
                f"{sorted(unknown)}"
            )

        for label in labels:
            targets[
                row_index,
                vocabulary_index[label],
            ] = 1

    return targets


def build_feature_matrix(
    dataframe: pd.DataFrame,
    embedding_accessions: np.ndarray,
    embeddings: np.ndarray,
) -> np.ndarray:
    """Align cached embeddings to dataframe accession order."""

    if embeddings.ndim != 2:
        raise ValueError(
            "Embeddings must be a 2D matrix."
        )

    if len(embedding_accessions) != len(embeddings):
        raise ValueError(
            "Embedding accessions and matrix rows do not match."
        )

    if len(set(embedding_accessions)) != len(
        embedding_accessions
    ):
        raise ValueError(
            "Duplicate accessions exist in the embedding artifact."
        )

    accession_to_index = {
        accession: index
        for index, accession in enumerate(
            embedding_accessions
        )
    }

    missing = [
        accession
        for accession in dataframe["accession"]
        if accession not in accession_to_index
    ]

    if missing:
        raise ValueError(
            f"{len(missing)} proteins have no cached embedding."
        )

    indices = [
        accession_to_index[accession]
        for accession in dataframe["accession"]
    ]

    return embeddings[indices].copy()


def build_modeling_arrays(
    dataframe: pd.DataFrame,
    vocabulary: list[str],
    embedding_accessions: np.ndarray,
    embeddings: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Create aligned feature and multilabel target matrices."""

    features = build_feature_matrix(
        dataframe,
        embedding_accessions,
        embeddings,
    )

    targets = encode_labels(
        dataframe,
        vocabulary,
    )

    return features, targets


def build_baseline_classifier(
    random_state: int = 42,
    c: float = 1.0,
    class_weight: str | None = None,
) -> Pipeline:
    """Create the frozen-embedding logistic-regression baseline."""

    return Pipeline(
        [
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "classifier",
                OneVsRestClassifier(
                    LogisticRegression(
                        solver="liblinear",
                        max_iter=2000,
                        random_state=random_state,
                        C=c,
                        class_weight=class_weight,
                    )
                ),
            ),
        ]
    )