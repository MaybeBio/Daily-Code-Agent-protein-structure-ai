import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from protein_function_predictor.embedding import (
    MODEL_CHECKPOINT,
)
from protein_function_predictor.evaluation import (
    apply_thresholds,
    probability_metrics,
    select_f1_thresholds,
    threshold_metrics,
)
from protein_function_predictor.features import (
    load_embeddings,
)
from protein_function_predictor.modeling import (
    build_baseline_classifier,
    build_modeling_arrays,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Train the baseline protein-function classifier."
        )
    )

    parser.add_argument(
        "--train",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--validation",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--embeddings",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--labels",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--model-output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--metrics-output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )

    parser.add_argument(
        "--c",
        type=float,
        default=1.0,
    )

    parser.add_argument(
        "--class-weight",
        choices=[
            "none",
            "balanced",
        ],
        default="none",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    class_weight = (
        None
        if args.class_weight == "none"
        else args.class_weight
    )

    train = pd.read_csv(
        args.train
    )

    validation = pd.read_csv(
        args.validation
    )

    with args.labels.open(
        encoding="utf-8"
    ) as file:
        vocabulary = json.load(file)

    embedding_accessions, embeddings = (
        load_embeddings(
            args.embeddings
        )
    )

    x_train, y_train = build_modeling_arrays(
        train,
        vocabulary,
        embedding_accessions,
        embeddings,
    )

    x_validation, y_validation = (
        build_modeling_arrays(
            validation,
            vocabulary,
            embedding_accessions,
            embeddings,
        )
    )

    print("Training matrices")
    print("-----------------")
    print(f"X_train:      {x_train.shape}")
    print(f"y_train:      {y_train.shape}")
    print(
        f"X_validation: {x_validation.shape}"
    )
    print(
        f"y_validation: {y_validation.shape}"
    )
    print()
    print("Model configuration")
    print("-------------------")
    print(f"C:            {args.c}")
    print(
        "Class weight: "
        f"{class_weight}"
    )
    print()

    classifier = build_baseline_classifier(
        random_state=args.seed,
        c=args.c,
        class_weight=class_weight,
    )

    classifier.fit(
        x_train,
        y_train,
    )

    validation_probabilities = (
        classifier.predict_proba(
            x_validation
        )
    )

    thresholds = select_f1_thresholds(
        y_validation,
        validation_probabilities,
    )

    validation_predictions = (
        apply_thresholds(
            validation_probabilities,
            thresholds,
        )
    )

    probability_results = (
        probability_metrics(
            y_validation,
            validation_probabilities,
            vocabulary,
        )
    )

    threshold_results = (
        threshold_metrics(
            y_validation,
            validation_predictions,
            vocabulary,
        )
    )

    model_bundle = {
        "classifier": classifier,
        "vocabulary": vocabulary,
        "thresholds": thresholds,
        "seed": args.seed,
        "c": args.c,
        "class_weight": class_weight,
        "embedding_model": MODEL_CHECKPOINT,
        "pooling": "mean_residue_pooling",
        "embedding_dimension": int(
            x_train.shape[1]
        ),
    }

    args.model_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        model_bundle,
        args.model_output,
    )

    results = {
        "seed": args.seed,
        "c": args.c,
        "class_weight": class_weight,
        "embedding_model": MODEL_CHECKPOINT,
        "pooling": "mean_residue_pooling",
        "training_proteins": len(train),
        "validation_proteins": len(validation),
        "embedding_dimension": int(
            x_train.shape[1]
        ),
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

    args.metrics_output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.metrics_output.write_text(
        json.dumps(
            results,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Validation results")
    print("------------------")
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
        f"Saved model to {args.model_output}"
    )
    print(
        f"Saved metrics to {args.metrics_output}"
    )


if __name__ == "__main__":
    main()