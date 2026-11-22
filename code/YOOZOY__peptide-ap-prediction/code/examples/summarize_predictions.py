"""Recompute test-set metrics from the saved peptide AP predictions."""

import csv
import math
from pathlib import Path
from statistics import mean


PREDICTIONS = (
    Path(__file__).resolve().parents[1] / "results" / "test_predictions_all_models.csv"
)


def main():
    with PREDICTIONS.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))

    labels = [float(row["Label"]) for row in rows]
    mean_label = mean(labels)
    total_sum_squares = sum((label - mean_label) ** 2 for label in labels)

    print(f"Test peptides: {len(rows):,}")
    print(f"{'Model':<12} {'MAE':>7} {'RMSE':>7} {'R2':>7}")
    for model in ("MLP", "LSTM", "Transformer"):
        errors = [
            float(row[f"{model}_prediction"]) - label
            for row, label in zip(rows, labels)
        ]
        sum_squared_error = sum(error ** 2 for error in errors)
        mae = mean(abs(error) for error in errors)
        rmse = math.sqrt(sum_squared_error / len(rows))
        r2 = 1 - sum_squared_error / total_sum_squares
        print(f"{model:<12} {mae:>7.4f} {rmse:>7.4f} {r2:>7.4f}")


if __name__ == "__main__":
    main()
