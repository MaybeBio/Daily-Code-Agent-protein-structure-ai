import argparse
import json
from pathlib import Path

import pandas as pd

from protein_function_predictor.splitting import (
    attach_clusters,
    count_labels,
    load_cluster_assignments,
    split_dataset,
    validate_no_overlap,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create sequence-cluster-aware "
            "train/validation/test splits."
        )
    )

    parser.add_argument(
        "--proteins",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--clusters",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--labels",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--output-dir",
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

    proteins = pd.read_csv(args.proteins)

    clusters = load_cluster_assignments(
        args.clusters
    )

    with args.labels.open(
        encoding="utf-8"
    ) as file:
        vocabulary = json.load(file)

    dataframe = attach_clusters(
        proteins,
        clusters,
    )

    train, validation, test = split_dataset(
        dataframe,
        seed=args.seed,
    )

    validate_no_overlap(
        train,
        validation,
        test,
    )

    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    splits = {
        "train": train,
        "validation": validation,
        "test": test,
    }

    for name, split in splits.items():
        split.to_csv(
            args.output_dir / f"{name}.csv",
            index=False,
        )

    summary = {
        "seed": args.seed,
        "total_proteins": len(dataframe),
        "total_clusters": int(
            dataframe["cluster_id"].nunique()
        ),
        "splits": {},
    }

    for name, split in splits.items():
        summary["splits"][name] = {
            "proteins": len(split),
            "fraction": (
                len(split) / len(dataframe)
            ),
            "clusters": int(
                split["cluster_id"].nunique()
            ),
            "label_counts": count_labels(
                split,
                vocabulary,
            ),
        }

    summary_path = (
        args.output_dir / "split_summary.json"
    )

    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()