import numpy as np

from protein_function_predictor.evaluation import (
    apply_thresholds,
    probability_metrics,
    select_f1_thresholds,
    threshold_metrics,
)


def example_data():
    targets = np.array(
        [
            [1, 0],
            [1, 1],
            [0, 1],
            [0, 0],
        ]
    )

    probabilities = np.array(
        [
            [0.9, 0.1],
            [0.8, 0.9],
            [0.2, 0.8],
            [0.1, 0.2],
        ]
    )

    vocabulary = [
        "GO:0000001",
        "GO:0000002",
    ]

    return (
        targets,
        probabilities,
        vocabulary,
    )


def test_probability_metrics_are_perfect():
    targets, probabilities, vocabulary = (
        example_data()
    )

    metrics = probability_metrics(
        targets,
        probabilities,
        vocabulary,
    )

    assert metrics[
        "micro_average_precision"
    ] == 1.0

    assert metrics[
        "macro_average_precision"
    ] == 1.0


def test_threshold_selection_returns_one_per_label():
    targets, probabilities, _ = (
        example_data()
    )

    thresholds = select_f1_thresholds(
        targets,
        probabilities,
    )

    assert thresholds.shape == (2,)

    assert np.all(
        (thresholds >= 0.0)
        & (thresholds <= 1.0)
    )


def test_apply_thresholds():
    _, probabilities, _ = example_data()

    thresholds = np.array(
        [0.5, 0.5]
    )

    predictions = apply_thresholds(
        probabilities,
        thresholds,
    )

    expected = np.array(
        [
            [1, 0],
            [1, 1],
            [0, 1],
            [0, 0],
        ],
        dtype=np.int8,
    )

    np.testing.assert_array_equal(
        predictions,
        expected,
    )


def test_threshold_metrics_are_perfect():
    targets, probabilities, vocabulary = (
        example_data()
    )

    predictions = apply_thresholds(
        probabilities,
        np.array([0.5, 0.5]),
    )

    metrics = threshold_metrics(
        targets,
        predictions,
        vocabulary,
    )

    assert metrics["micro_f1"] == 1.0
    assert metrics["macro_f1"] == 1.0