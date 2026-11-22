import argparse
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

import sys
sys.path.append(str(Path(__file__).resolve().parents[1]))
from project_root import PROCESSED


def parse_int_list(s: str):
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def axis_name_from_feature(f: int) -> str:
    """
    Maps any feature index to x / y / z using modulo.
    Works for:
      - coords:     0,1,2
      - velocities: 414,415,416
      - forces:     828,829,830
    """
    return {0: "x", 1: "y", 2: "z"}[f % 3]


def axis_color_from_feature(f: int) -> str:
    return {0: "blue", 1: "green", 2: "red"}[f % 3]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, required=True)
    parser.add_argument("--out_name", type=str, required=True)
    parser.add_argument("--features", type=str, default="0,1,2")
    parser.add_argument("--max_points", type=int, default=300)
    parser.add_argument("--sort_by_time", type=int, default=0)
    args = parser.parse_args()

    reports_dir = PROCESSED / "reports"
    pred_path = reports_dir / f"{args.out_name}_w{args.window}_pred.npy"
    true_path = reports_dir / f"{args.out_name}_w{args.window}_true.npy"

    if not pred_path.exists() or not true_path.exists():
        raise FileNotFoundError(
            "Missing pred/true arrays.\n"
            "Run 07_evaluate_models.py with --save_arrays 1 first.\n"
            f"Expected:\n  {pred_path}\n  {true_path}"
        )

    pred = np.load(pred_path)
    true = np.load(true_path)

    if pred.shape != true.shape:
        raise ValueError(f"Shape mismatch: pred={pred.shape}, true={true.shape}")

    # Select samples
    idx = np.arange(true.shape[0])
    if bool(args.sort_by_time):
        idx = np.sort(idx)

    if args.max_points and len(idx) > args.max_points:
        idx = idx[: args.max_points]

    feats = parse_int_list(args.features)

    out_fig = reports_dir / (
        f"{args.out_name}_w{args.window}_gt_vs_pred_features_"
        f"{'-'.join(map(str, feats))}.jpg"
    )

    plt.figure(figsize=(12, 5))

    for f in feats:
        if f < 0 or f >= true.shape[1]:
            raise ValueError(f"Feature index out of range: {f}, y_dim={true.shape[1]}")

        axis_label = axis_name_from_feature(f)
        color = axis_color_from_feature(f)

        plt.plot(
            true[idx, f],
            color=color,
            linewidth=2,
            label=f"GT – {axis_label}",
        )
        plt.plot(
            pred[idx, f],
            color=color,
            linestyle="--",
            linewidth=2,
            label=f"Pred – {axis_label}",
        )

    plt.title(f"Ground Truth vs Prediction ({args.out_name}, window={args.window})")
    plt.xlabel("Time step (Δt)")
    plt.ylabel("Value")
    plt.legend()
    plt.grid(alpha=0.3)

    plt.savefig(out_fig, dpi=300, bbox_inches="tight")
    plt.close()

    print("Saved:", out_fig)


if __name__ == "__main__":
    print("RUNNING:", __file__)
    main()
