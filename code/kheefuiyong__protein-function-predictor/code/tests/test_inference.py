import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

from protein_function_predictor.inference import (
    ProteinFunctionPredictor,
)


class FakeEmbedder:
    def embed(
        self,
        sequence: str,
    ) -> torch.Tensor:
        if sequence == "AAAA":
            return torch.tensor(
                [1.0, 0.0],
                dtype=torch.float32,
            )

        return torch.tensor(
            [0.0, 1.0],
            dtype=torch.float32,
        )


def make_model_bundle(path):
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

    classifier = OneVsRestClassifier(
        LogisticRegression(
            solver="liblinear"
        )
    )

    classifier.fit(
        features,
        targets,
    )

    bundle = {
        "classifier": classifier,
        "vocabulary": [
            "GO:0000001",
            "GO:0000002",
        ],
        "thresholds": np.array(
            [0.5, 0.5],
            dtype=np.float32,
        ),
        "embedding_model": "fake-model",
        "pooling": "mean_residue_pooling",
        "embedding_dimension": 2,
    }

    joblib.dump(
        bundle,
        path,
    )


def test_predict_returns_one_result_per_label(
    tmp_path,
):
    path = tmp_path / "model.joblib"

    make_model_bundle(path)

    predictor = ProteinFunctionPredictor(
        path,
        embedder=FakeEmbedder(),
    )

    predictions = predictor.predict(
        "AAAA"
    )

    assert len(predictions) == 2

    assert {
        prediction.go_term
        for prediction in predictions
    } == {
        "GO:0000001",
        "GO:0000002",
    }

    assert all(
        0.0
        <= prediction.probability
        <= 1.0
        for prediction in predictions
    )

    assert all(
        isinstance(
            prediction.predicted,
            bool,
        )
        for prediction in predictions
    )


def test_predictions_are_sorted_by_probability(
    tmp_path,
):
    path = tmp_path / "model.joblib"

    make_model_bundle(path)

    predictor = ProteinFunctionPredictor(
        path,
        embedder=FakeEmbedder(),
    )

    predictions = predictor.predict(
        "AAAA"
    )

    probabilities = [
        prediction.probability
        for prediction in predictions
    ]

    assert probabilities == sorted(
        probabilities,
        reverse=True,
    )

def test_model_bundle_rejects_threshold_count_mismatch(
    tmp_path,
):
    path = tmp_path / "model.joblib"

    make_model_bundle(path)

    bundle = joblib.load(path)

    bundle["thresholds"] = np.array(
        [0.5],
        dtype=np.float32,
    )

    joblib.dump(
        bundle,
        path,
    )

    try:
        ProteinFunctionPredictor(
            path,
            embedder=FakeEmbedder(),
        )
    except ValueError as error:
        assert (
            "Vocabulary and threshold counts"
            in str(error)
        )
    else:
        raise AssertionError(
            "Expected ValueError."
        )