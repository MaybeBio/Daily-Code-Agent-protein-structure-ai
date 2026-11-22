"""Compare fixed test predictions using absolute and length-relative accuracy.

Percentile intervals resample test rows within each length, keeping all three
predictions on a row together. They are pointwise, conditional on the trained
models and the reference medians from the original training split.
"""

import argparse
import hashlib
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / "results" / "test_predictions_all_models.csv"
# Git blob for Sequential_Peptides/train_seqs.csv at upstream commit 695f95f7.
TRAIN_BLOB = "8847ae84519bdc83209d6a9a732025223bd05852"
MODELS = ("Transformer", "LSTM", "MLP")
LENGTHS = tuple(range(5, 11))
SEED = 20261118
RESAMPLES = 10_000


def load_inputs(training_csv):
    data = training_csv.read_bytes().replace(b"\r\n", b"\n")
    blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    if hashlib.sha1(blob).hexdigest() != TRAIN_BLOB:
        raise ValueError("training CSV does not match the pinned upstream regression split")
    train = pd.read_csv(BytesIO(data), usecols=["Feature", "Label"])
    medians = train.groupby(train["Feature"].str.len())["Label"].median()

    test = pd.read_csv(PREDICTIONS)
    if len(test) != 3997 or test["Feature"].nunique() != len(test):
        raise ValueError("expected 3,997 unique test sequences")
    if set(test["Feature"]).intersection(train["Feature"]):
        raise ValueError("the training and test sets share sequences")
    if not test["length"].eq(test["Feature"].str.len()).all() or set(test["length"]) != set(LENGTHS):
        raise ValueError("unexpected peptide lengths in the test predictions")
    columns = ["Label"] + [f"{model}_prediction" for model in MODELS]
    if not np.isfinite(test[columns].to_numpy()).all():
        raise ValueError("test labels and predictions must be finite")
    return medians, test


def score(labels, errors, baseline_errors):
    """Return MAE, within-length R² and MAE skill, with optional leading draw axis."""
    mae = np.abs(errors).mean(axis=-2)
    variance = labels.var(axis=-1, keepdims=True)
    r2 = 1 - np.square(errors).mean(axis=-2) / variance
    skill = 1 - mae / baseline_errors.mean(axis=-1, keepdims=True)
    return np.stack([mae, r2, skill], axis=-1)


def score_resamples(labels, errors, baseline_errors, rng):
    # Batching bounds memory use without changing the paired sampling unit.
    samples = np.empty((RESAMPLES, len(MODELS), 3))
    batch_size = 100
    for start in range(0, RESAMPLES, batch_size):
        stop = min(start + batch_size, RESAMPLES)
        indices = rng.integers(len(labels), size=(stop - start, len(labels)))
        samples[start:stop] = score(labels[indices], errors[indices], baseline_errors[indices])
    return samples


def interval(samples):
    lower, upper = np.quantile(samples, [0.025, 0.975])
    return {"ci95_lower": lower, "ci95_upper": upper}


def evaluate(medians, test):
    rows = []
    counts = []
    estimates = []
    draws = []
    rng = np.random.default_rng(SEED)
    for length in LENGTHS:
        group = test.loc[test["length"] == length]
        labels = group["Label"].to_numpy()
        predictions = group[[f"{model}_prediction" for model in MODELS]].to_numpy()
        errors = predictions - labels[:, None]
        baseline_errors = np.abs(labels - medians[length])
        points = score(labels, errors, baseline_errors)
        counts.append(len(group))
        estimates.append(points)
        draws.append(score_resamples(labels, errors, baseline_errors, rng))
        for model, (mae, r2, skill) in zip(MODELS, points):
            rows.append({
                "length": length, "n": len(group), "model": model,
                "target_sd": labels.std(ddof=1), "training_median_ap": medians[length],
                "baseline_mae": baseline_errors.mean(), "mae": mae, "r2": r2, "mae_skill": skill,
            })

    # Axes are length, [resample], model and metric.
    estimates = np.stack(estimates)
    draws = np.stack(draws)
    paired = []
    for weighting, weights in [("observed_length_mix", counts), ("equal_length", np.ones(len(counts)))]:
        mean_mae = np.average(estimates[:, :, 0], axis=0, weights=weights)
        sampled_mae = np.average(draws[:, :, :, 0], axis=0, weights=weights)
        for a, b in [(0, 1), (0, 2), (1, 2)]:
            paired.append({
                "weighting": weighting, "n": len(test), "model_a": MODELS[a], "model_b": MODELS[b],
                "mae_a_minus_b": mean_mae[a] - mean_mae[b],
                **interval(sampled_mae[:, a] - sampled_mae[:, b]),
            })

    endpoints = []
    transformer = MODELS.index("Transformer")
    for index, metric in enumerate(["mae", "r2", "mae_skill"]):
        five = estimates[0, transformer, index]
        ten = estimates[-1, transformer, index]
        difference = draws[0, :, transformer, index] - draws[-1, :, transformer, index]
        endpoints.append({
            "model": "Transformer", "metric": metric, "value_length_5": five,
            "value_length_10": ten, "length_5_minus_10": five - ten, **interval(difference),
        })
    return {
        "by_length.csv": pd.DataFrame(rows),
        "paired_mae_contrasts.csv": pd.DataFrame(paired),
        "endpoint_contrasts.csv": pd.DataFrame(endpoints),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training-csv", type=Path, required=True, help="upstream regression train_seqs.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results" / "length_evaluation")
    args = parser.parse_args()
    try:
        tables = evaluate(*load_inputs(args.training_csv))
    except (OSError, ValueError) as error:
        parser.exit(2, f"input error: {error}\n")
    args.output_dir.mkdir(exist_ok=True, parents=True)
    for filename, table in tables.items():
        table.to_csv(args.output_dir / filename, index=False, float_format="%.9f", lineterminator="\n")


if __name__ == "__main__":
    main()
