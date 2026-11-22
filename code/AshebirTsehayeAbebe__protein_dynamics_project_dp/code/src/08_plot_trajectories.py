import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf

# allow importing project_root + helper loaders
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED

# Import from your existing evaluator to reuse model + loaders
from src._evaluate_utils import (
    TransformerBlock,
    denorm_if_needed,
    load_arrays,
    predict_one_step,
    resolve_model_path,
)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--window", type=int, default=25)
    p.add_argument("--model_path", type=str, required=True)
    p.add_argument("--horizon", type=int, default=500)
    p.add_argument("--start_test_row", type=int, default=0, help="Which test sample index to start from (0-based in test_idx list)")
    p.add_argument("--feature_index", type=int, default=0, help="Which feature to plot (0..1241)")
    p.add_argument("--use_denorm", type=int, default=1)
    p.add_argument("--out_name", type=str, default="trajectory")
    return p.parse_args()

def main():
    args = parse_args()

    window = args.window
    horizon = args.horizon
    feature_index = args.feature_index
    use_denorm = bool(args.use_denorm)

    # Load prepared arrays (same as your evaluation)
    x, y, test_idx, stats = load_arrays(window, use_denorm)

    # pick a starting sample from test indices
    start_i = test_idx[args.start_test_row]

    # Resolve + load model
    model_path = resolve_model_path(args.model_path)
    model = tf.keras.models.load_model(
        model_path,
        compile=False,
        custom_objects={"TransformerBlock": TransformerBlock},
    )

    # We will do an autoregressive rollout:
    # start with X window from sample start_i, then predict next-step repeatedly
    # x[start_i] is shape (window, dx)
    xw = np.array(x[start_i], dtype=np.float32)  # (W, dx)

    # Ground truth "next step" target for the first step is y[start_i]
    # For rollout truth, we can use y[start_i + k] as the next-step target sequence
    # (this assumes your dataset windows are built sequentially from the aligned trajectory)
    y_true_series = []
    y_pred_series = []

    for k in range(horizon):
        # 1-step prediction from current window
        yhat = predict_one_step(model, xw)  # (dy,)

        # get corresponding ground truth (next step)
        true_row = start_i + k
        if true_row >= len(y):
            break

        yt = y[true_row].astype(np.float32)

        # denorm (if enabled)
        yhat_eval = denorm_if_needed(yhat[None, :], stats)[0]
        yt_eval = denorm_if_needed(yt[None, :], stats)[0]

        y_pred_series.append(yhat_eval[feature_index])
        y_true_series.append(yt_eval[feature_index])

        # update window: shift left and append the predicted state as the newest timestep
        # IMPORTANT: your X contains coords+vels(+forces) depending on how you built windows.
        # In your pipeline, X is built from the same concatenation as y (coords+vels+forces) when include_forces_in_input=True.
        # So we append the model prediction yhat (dy=1242) as the next input row.
        xw = np.roll(xw, shift=-1, axis=0)
        xw[-1, :] = yhat.astype(np.float32)

    y_true_series = np.array(y_true_series)
    y_pred_series = np.array(y_pred_series)
    t = np.arange(len(y_true_series))

    # Plot: Actual vs Predicted (like your example slide)
    plt.figure(figsize=(10, 4))
    plt.plot(t, y_true_series, label="Ground truth", linewidth=2)
    plt.plot(t, y_pred_series, label="Prediction", linestyle="--")
    plt.xlabel("Future time step")
    plt.ylabel(f"Feature {feature_index}")
    plt.title("Temporal evolution of model outputs vs ground-truth (test / out-of-sample)")
    plt.legend()
    plt.grid(True)

    out_dir = PROCESSED / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.out_name}_w{window}_feat{feature_index}_H{len(t)}.jpg"
    plt.tight_layout()
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()

    # Optional: bias plot over horizon (mean error)
    err = y_pred_series - y_true_series
    plt.figure(figsize=(6, 4))
    plt.plot(t, err, linewidth=2)
    plt.axhline(0, linewidth=1)
    plt.xlabel("Future time step")
    plt.ylabel("Prediction error (pred - true)")
    plt.title(f"Bias over forecast horizon (feature {feature_index})")
    bias_path = out_dir / f"{args.out_name}_bias_w{window}_feat{feature_index}_H{len(t)}.jpg"
    plt.tight_layout()
    plt.savefig(bias_path, dpi=300, bbox_inches="tight")
    plt.close()

    print("Saved:", out_path)
    print("Saved:", bias_path)

if __name__ == "__main__":
    main()
