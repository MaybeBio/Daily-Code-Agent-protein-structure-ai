import argparse
from pathlib import Path

from protein_function_predictor.inference import (
    ProteinFunctionPredictor,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Predict GO Molecular Function terms "
            "from a protein sequence."
        )
    )

    parser.add_argument(
        "--sequence",
        required=True,
    )

    parser.add_argument(
        "--model",
        required=True,
        type=Path,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    predictor = ProteinFunctionPredictor(
        args.model
    )

    predictions = predictor.predict(
        args.sequence
    )

    print()
    print("Predicted molecular functions")
    print("-----------------------------")

    print(
        f"{'GO term':<12} "
        f"{'Score':>10} "
        f"{'Threshold':>10} "
        f"{'Predicted':>10}"
    )

    print("-" * 46)

    for prediction in predictions:
        print(
            f"{prediction.go_term:<12} "
            f"{prediction.probability:>10.3f} "
            f"{prediction.threshold:>10.3f} "
            f"{prediction.predicted!s:>10}"
        )


if __name__ == "__main__":
    main()