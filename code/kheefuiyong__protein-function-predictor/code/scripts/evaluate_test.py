import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from protein_function_predictor.evaluation import (
    apply_thresholds,
    probability_metrics,
    threshold_metrics,
)
from protein_function_predictor.features import (
    load_embeddings,
)
from protein_function_predictor.modeling import (
    build_modeling_arrays,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the frozen baseline classifier "
            "on the held-out test set."
        )
    )

    parser.add_argument(
        "--test",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--embeddings",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--model",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    test = pd.read_csv(
        args.test
    )

    embedding_accessions, embeddings = (
        load_embeddings(
            args.embeddings
        )
    )

    bundle = joblib.load(
        args.model
    )

    classifier = bundle[
        "classifier"
    ]

    vocabulary = bundle[
        "vocabulary"
    ]

    thresholds = np.asarray(
        bundle["thresholds"],
        dtype=np.float32,
    )

    x_test, y_test = build_modeling_arrays(
        test,
        vocabulary,
        embedding_accessions,
        embeddings,
    )

    if x_test.shape[1] != bundle[
        "embedding_dimension"
    ]:
        raise ValueError(
            "Test embedding dimension does not match "
            "the trained model."
        )

    print("Held-out test matrices")
    print("----------------------")
    print(f"X_test: {x_test.shape}")
    print(f"y_test: {y_test.shape}")
    print()

    probabilities = classifier.predict_proba(
        x_test
    )

    predictions = apply_thresholds(
        probabilities,
        thresholds,
    )

    probability_results = probability_metrics(
        y_test,
        probabilities,
        vocabulary,
    )

    threshold_results = threshold_metrics(
        y_test,
        predictions,
        vocabulary,
    )

    results = {
        "test_proteins": len(test),
        "model_configuration": {
            "c": bundle["c"],
            "class_weight": bundle[
                "class_weight"
            ],
            "embedding_model": bundle[
                "embedding_model"
            ],
            "pooling": bundle[
                "pooling"
            ],
            "embedding_dimension": bundle[
                "embedding_dimension"
            ],
        },
        "probability_metrics": (
            probability_results
        ),
        "threshold_metrics": (
            threshold_results
        ),
        "thresholds": {
            label: float(threshold)
            for label, threshold in zip(
                vocabulary,
                thresholds,
                strict=True,
            )
        },
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            results,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Held-out test results")
    print("---------------------")
    print(
        "Micro AP: "
        f"{probability_results['micro_average_precision']:.4f}"
    )
    print(
        "Macro AP: "
        f"{probability_results['macro_average_precision']:.4f}"
    )
    print(
        "Micro F1: "
        f"{threshold_results['micro_f1']:.4f}"
    )
    print(
        "Macro F1: "
        f"{threshold_results['macro_f1']:.4f}"
    )

    print()
    print(
        f"Saved test metrics to {args.output}"
    )


if __name__ == "__main__":
    main()