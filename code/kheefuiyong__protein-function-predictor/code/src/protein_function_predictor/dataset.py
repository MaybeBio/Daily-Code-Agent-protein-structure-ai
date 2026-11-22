import re
from collections import Counter
from pathlib import Path

import pandas as pd

VALID_AMINO_ACIDS = set("ACDEFGHIKLMNPQRSTVWY")
MAX_SEQUENCE_LENGTH = 1024

GO_PATTERN = re.compile(r"GO:\d{7}")


def load_uniprot_tsv(path: str | Path) -> pd.DataFrame:
    """Load a UniProt TSV and standardize required column names."""

    dataframe = pd.read_csv(path, sep="\t", dtype=str)

    column_aliases = {
        "accession": ["accession", "Entry"],
        "sequence": ["sequence", "Sequence"],
        "go_mf": [
            "go_mf",
            "Gene Ontology (molecular function)",
        ],
    }

    rename_map = {}

    for target, candidates in column_aliases.items():
        source = next(
            (name for name in candidates if name in dataframe.columns),
            None,
        )

        if source is None:
            raise ValueError(
                f"Could not find a column for '{target}'. "
                f"Expected one of: {candidates}"
            )

        rename_map[source] = target

    return dataframe.rename(columns=rename_map)[
        ["accession", "sequence", "go_mf"]
    ]


def normalize_sequence(sequence: object) -> str:
    """Remove whitespace and convert a sequence to uppercase."""

    if pd.isna(sequence):
        return ""

    return "".join(str(sequence).split()).upper()


def parse_go_terms(value: object) -> list[str]:
    """Extract unique GO identifiers from a UniProt annotation field."""

    if pd.isna(value):
        return []

    return sorted(set(GO_PATTERN.findall(str(value))))


def remove_invalid_records(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Remove missing, invalid, or overlength protein sequences."""

    dataframe = dataframe.copy()

    dataframe["sequence"] = dataframe["sequence"].apply(
        normalize_sequence
    )

    valid_sequence = dataframe["sequence"].apply(
        lambda sequence: (
            0 < len(sequence) <= MAX_SEQUENCE_LENGTH
            and set(sequence).issubset(VALID_AMINO_ACIDS)
        )
    )

    valid_accession = dataframe["accession"].notna()

    return dataframe.loc[
        valid_sequence & valid_accession
    ].reset_index(drop=True)


def remove_duplicate_sequences(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    """Keep only the first occurrence of each exact protein sequence."""

    return (
        dataframe
        .drop_duplicates(subset="sequence", keep="first")
        .reset_index(drop=True)
    )


def select_frequent_labels(
    dataframe: pd.DataFrame,
    top_k: int,
    min_positives: int,
) -> list[str]:
    """Select frequent GO labels with deterministic ordering."""

    counts = Counter(
        term
        for terms in dataframe["go_terms"]
        for term in terms
    )

    eligible = [
        (term, count)
        for term, count in counts.items()
        if count >= min_positives
    ]

    eligible.sort(
        key=lambda item: (-item[1], item[0])
    )

    return [
        term
        for term, _ in eligible[:top_k]
    ]