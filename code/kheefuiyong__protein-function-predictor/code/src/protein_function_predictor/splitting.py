from pathlib import Path

import pandas as pd
from sklearn.model_selection import GroupShuffleSplit


def load_cluster_assignments(
    path: str | Path,
) -> pd.DataFrame:
    """Load and validate MMseqs cluster assignments."""

    clusters = pd.read_csv(
        path,
        sep="\t",
        names=["cluster_id", "accession"],
        dtype=str,
    )

    missing_cluster_ids = int(
        clusters["cluster_id"].isna().sum()
    )

    missing_accessions = int(
        clusters["accession"].isna().sum()
    )

    if missing_cluster_ids or missing_accessions:
        raise ValueError(
            "Malformed MMseqs cluster file: "
            f"{missing_cluster_ids} rows have missing "
            "cluster IDs and "
            f"{missing_accessions} rows have missing "
            "accessions."
        )

    clusters_per_accession = (
        clusters
        .groupby("accession")["cluster_id"]
        .nunique()
    )

    conflicting = clusters_per_accession[
        clusters_per_accession > 1
    ]

    if not conflicting.empty:
        raise ValueError(
            f"{len(conflicting)} accessions occur "
            "in more than one cluster."
        )

    return clusters


def attach_clusters(
    proteins: pd.DataFrame,
    clusters: pd.DataFrame,
) -> pd.DataFrame:
    """Attach one sequence-similarity cluster to every protein."""

    merged = proteins.merge(
        clusters,
        on="accession",
        how="left",
        validate="one_to_one",
    )

    missing = int(merged["cluster_id"].isna().sum())

    if missing:
        raise ValueError(
            f"{missing} proteins have no cluster assignment."
        )

    return merged


def split_dataset(
    dataframe: pd.DataFrame,
    seed: int = 42,
    train_fraction: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split proteins while keeping entire clusters together."""

    first_splitter = GroupShuffleSplit(
        n_splits=1,
        train_size=train_fraction,
        random_state=seed,
    )

    train_indices, remainder_indices = next(
        first_splitter.split(
            dataframe,
            groups=dataframe["cluster_id"],
        )
    )

    train = dataframe.iloc[train_indices].copy()
    remainder = dataframe.iloc[remainder_indices].copy()

    second_splitter = GroupShuffleSplit(
        n_splits=1,
        train_size=0.5,
        random_state=seed + 1,
    )

    validation_indices, test_indices = next(
        second_splitter.split(
            remainder,
            groups=remainder["cluster_id"],
        )
    )

    validation = remainder.iloc[validation_indices].copy()
    test = remainder.iloc[test_indices].copy()

    return (
        train.reset_index(drop=True),
        validation.reset_index(drop=True),
        test.reset_index(drop=True),
    )


def count_labels(
    dataframe: pd.DataFrame,
    vocabulary: list[str],
) -> dict[str, int]:
    """Count positives for every GO term."""

    label_sets = dataframe["labels"].apply(
        lambda value: set(value.split(";"))
    )

    return {
        label: sum(
            label in protein_labels
            for protein_labels in label_sets
        )
        for label in vocabulary
    }


def validate_no_overlap(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> None:
    """Check accession, sequence and cluster isolation."""

    splits = {
        "train": train,
        "validation": validation,
        "test": test,
    }

    pairs = [
        ("train", "validation"),
        ("train", "test"),
        ("validation", "test"),
    ]

    for left_name, right_name in pairs:
        left = splits[left_name]
        right = splits[right_name]

        for column in (
            "accession",
            "sequence",
            "cluster_id",
        ):
            overlap = (
                set(left[column])
                & set(right[column])
            )

            if overlap:
                raise ValueError(
                    f"{column} overlap between "
                    f"{left_name} and {right_name}: "
                    f"{len(overlap)}"
                )