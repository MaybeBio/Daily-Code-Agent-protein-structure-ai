import argparse
import json
from pathlib import Path

import pandas as pd

from protein_function_predictor.evaluation import (
    probability_metrics,
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
            "Compare baseline logistic-regression "
            "configurations on the validation set."
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
        "--output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

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

    configurations = [
        {
            "name": "default",
            "c": 1.0,
            "class_weight": None,
        },
        {
            "name": "balanced",
            "c": 1.0,
            "class_weight": "balanced",
        },
        {
            "name": "stronger_regularization",
            "c": 0.1,
            "class_weight": None,
        },
        {
            "name": "weaker_regularization",
            "c": 10.0,
            "class_weight": None,
        },
    ]

    results = []

    print("Baseline comparison")
    print("-------------------")
    print(
        f"Training proteins:   {len(train)}"
    )
    print(
        f"Validation proteins: {len(validation)}"
    )
    print()

    for configuration in configurations:
        print(
            f"Training: {configuration['name']}"
        )

        classifier = build_baseline_classifier(
            random_state=args.seed,
            c=configuration["c"],
            class_weight=configuration[
                "class_weight"
            ],
        )

        classifier.fit(
            x_train,
            y_train,
        )

        probabilities = (
            classifier.predict_proba(
                x_validation
            )
        )

        metrics = probability_metrics(
            y_validation,
            probabilities,
            vocabulary,
        )

        result = {
            **configuration,
            "micro_average_precision": metrics[
                "micro_average_precision"
            ],
            "macro_average_precision": metrics[
                "macro_average_precision"
            ],
            "per_label": metrics[
                "per_label"
            ],
        }

        results.append(result)

        print(
            "  Micro AP: "
            f"{result['micro_average_precision']:.4f}"
        )
        print(
            "  Macro AP: "
            f"{result['macro_average_precision']:.4f}"
        )
        print()

    ranked = sorted(
        results,
        key=lambda result: (
            result["macro_average_precision"],
            result["micro_average_precision"],
        ),
        reverse=True,
    )

    output = {
        "seed": args.seed,
        "selection_metric": (
            "macro_average_precision"
        ),
        "secondary_metric": (
            "micro_average_precision"
        ),
        "training_proteins": len(train),
        "validation_proteins": len(validation),
        "results": ranked,
        "best_configuration": {
            "name": ranked[0]["name"],
            "c": ranked[0]["c"],
            "class_weight": ranked[0][
                "class_weight"
            ],
            "micro_average_precision": ranked[0][
                "micro_average_precision"
            ],
            "macro_average_precision": ranked[0][
                "macro_average_precision"
            ],
        },
    }

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.output.write_text(
        json.dumps(
            output,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Ranking")
    print("-------")

    for index, result in enumerate(
        ranked,
        start=1,
    ):
        print(
            f"{index}. {result['name']}: "
            f"Macro AP="
            f"{result['macro_average_precision']:.4f}, "
            f"Micro AP="
            f"{result['micro_average_precision']:.4f}"
        )

    print()
    print(
        "Best configuration: "
        f"{ranked[0]['name']}"
    )

    print(
        f"Saved comparison to {args.output}"
    )


if __name__ == "__main__":
    main()