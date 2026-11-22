#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", required=True, help="Path to *_history.json")
    ap.add_argument("--out", default=None, help="Output image path (optional)")
    ap.add_argument("--title", default=None, help="Optional title")
    args = ap.parse_args()

    p = Path(args.history)
    h = json.loads(p.read_text())

    teacher = h.get("teacher", [])
    masked = h.get("masked", [])
    scheduled = h.get("scheduled", [])
    val = h.get("val_mse", [])

    train = list(teacher) + list(masked) + list(scheduled)

    if not train or not val:
        raise ValueError("History JSON missing expected keys: teacher/masked/scheduled and val_mse")

    if len(train) != len(val):
        print(f"[WARN] train length={len(train)} != val length={len(val)} (will plot both anyway)")

    # Phase boundaries
    b1 = len(teacher)          # end of teacher forcing
    b2 = len(teacher) + len(masked)  # end of masked modeling

    plt.figure()
    plt.plot(train, label="train_mse")
    plt.plot(val, label="val_mse")

    # vertical separators between phases
    plt.axvline(b1 - 0.5, linestyle="--")
    plt.axvline(b2 - 0.5, linestyle="--")

    plt.xlabel("epoch (TF → MASK → SS)")
    plt.ylabel("MSE (normalized)")
    plt.title(args.title or p.stem.replace("_history", ""))
    plt.legend()
    plt.tight_layout()

    out = Path(args.out) if args.out else p.with_name(p.stem + "_learning_curve.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out, dpi=200)
    print(f"Saved learning curve to: {out}")


if __name__ == "__main__":
    main()
