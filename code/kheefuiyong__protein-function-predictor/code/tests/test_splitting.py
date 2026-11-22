import pandas as pd
import pytest

from protein_function_predictor.splitting import (
    attach_clusters,
    load_cluster_assignments,
    split_dataset,
    validate_no_overlap,
)


def make_example_data():
    proteins = pd.DataFrame(
        {
            "accession": [
                f"P{i:02d}"
                for i in range(12)
            ],
            "sequence": [
                f"SEQ{i:02d}"
                for i in range(12)
            ],
            "labels": [
                "GO:0000001"
            ] * 12,
        }
    )

    clusters = pd.DataFrame(
        {
            "cluster_id": [
                "C1",
                "C1",
                "C2",
                "C2",
                "C3",
                "C3",
                "C4",
                "C4",
                "C5",
                "C5",
                "C6",
                "C6",
            ],
            "accession": [
                f"P{i:02d}"
                for i in range(12)
            ],
        }
    )

    return proteins, clusters


def test_cluster_attachment():
    proteins, clusters = make_example_data()

    result = attach_clusters(
        proteins,
        clusters,
    )

    assert result["cluster_id"].notna().all()


def test_clusters_do_not_cross_splits():
    proteins, clusters = make_example_data()

    dataframe = attach_clusters(
        proteins,
        clusters,
    )

    train, validation, test = split_dataset(
        dataframe,
        seed=42,
    )

    validate_no_overlap(
        train,
        validation,
        test,
    )

    assert not (
        set(train["cluster_id"])
        & set(validation["cluster_id"])
    )

    assert not (
        set(train["cluster_id"])
        & set(test["cluster_id"])
    )

    assert not (
        set(validation["cluster_id"])
        & set(test["cluster_id"])
    )

def test_cluster_loader_rejects_missing_accession(
    tmp_path,
):
    path = tmp_path / "clusters.tsv"

    path.write_text(
        "C1\tP1\n"
        "C2\t\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ValueError,
        match="Malformed MMseqs cluster file",
    ):
        load_cluster_assignments(path)


def test_cluster_loader_rejects_multiple_clusters(
    tmp_path,
):
    path = tmp_path / "clusters.tsv"

    path.write_text(
        "C1\tP1\n"
        "C2\tP1\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(
        ValueError,
        match="more than one cluster",
    ):
        load_cluster_assignments(path)