"""Read BoltzGen results CSVs without assuming what is in them.

Every other script in analysis/ builds on this one. The point is that the column
names in BoltzGen's `all_designs_metrics.csv` have to be *read off a real file*
before anything can be computed from them, and that every column in there is a
structural confidence metric, not an affinity.

Usage:

    python analysis/scores.py --columns results/noise_a_n20.csv
    python analysis/scores.py --noise results/noise_a_n20.csv results/noise_b_n20.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

# Filled in once a real results file has been inspected. Until then, nothing in
# this repository may hard-code a column name.
SCORE_COLUMN: str | None = None


def load(path: str | Path) -> pd.DataFrame:
    """Load one BoltzGen metrics CSV.

    `path` may be the CSV itself, or a run directory containing
    final_ranked_designs/all_designs_metrics.csv.
    """
    p = Path(path)
    if p.is_dir():
        p = p / "final_ranked_designs" / "all_designs_metrics.csv"
    if not p.exists():
        raise FileNotFoundError(p)
    return pd.read_csv(p)


def describe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """What columns exist, and which of them are numeric enough to compare."""
    return pd.DataFrame(
        {"dtype": df.dtypes.astype(str), "n_unique": df.nunique(), "n_null": df.isna().sum()}
    )


def noise_floor(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    """Run-to-run spread of the pipeline, from two batches on the SAME target.

    `gap` is the difference between the two batch means. `sd_a` is the
    within-batch spread. A metric whose `gap` is comparable to its `sd_a` is not
    stable at this sample size, and a BNP-vs-ANP difference of that size means
    nothing.
    """
    cols = [c for c in a.select_dtypes("number").columns if c in b.columns]
    out = pd.DataFrame(
        {
            "mean_a": a[cols].mean(),
            "mean_b": b[cols].mean(),
            "sd_a": a[cols].std(),
            "sd_b": b[cols].std(),
            "n_a": len(a),
            "n_b": len(b),
        }
    )
    out["gap"] = (out["mean_a"] - out["mean_b"]).abs()
    out["gap_over_sd"] = out["gap"] / out["sd_a"]
    return out.sort_values("gap_over_sd", ascending=False).round(4)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--columns", metavar="CSV", help="print the columns of one results file")
    ap.add_argument(
        "--noise", nargs=2, metavar=("CSV_A", "CSV_B"), help="two batches on the same target"
    )
    args = ap.parse_args()

    if args.columns:
        df = load(args.columns)
        print(f"{len(df)} designs\n")
        print(describe_columns(df).to_string())
        print(
            "\nAll of these are confidence/geometry metrics. None of them is a "
            "predicted affinity."
        )
    elif args.noise:
        print(noise_floor(load(args.noise[0]), load(args.noise[1])).to_string())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
