# for saving and loading feature matrices, NOT for running ESM itself

from pathlib import Path

import numpy as np
import pandas as pd


def save_embeddings(
    path: str | Path,
    accessions: list[str],
    embeddings: np.ndarray,
) -> None:
    """Save protein embeddings with their accession IDs."""

    path = Path(path)

    if len(accessions) != len(embeddings):
        raise ValueError(
            "Number of accessions does not match "
            "number of embeddings."
        )

    if embeddings.ndim != 2:
        raise ValueError(
            "Embeddings must be a 2D matrix."
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    np.savez_compressed(
        path,
        accessions=np.asarray(
            accessions,
            dtype=str,
        ),
        embeddings=embeddings.astype(
            np.float32
        ),
    )


def load_embeddings(
    path: str | Path,
) -> tuple[np.ndarray, np.ndarray]:
    """Load accession IDs and protein embeddings."""

    with np.load(path) as data:
        accessions = data[
            "accessions"
        ].copy()

        embeddings = data[
            "embeddings"
        ].copy()

    return accessions, embeddings


def embeddings_to_dataframe(
    accessions: np.ndarray,
    embeddings: np.ndarray,
) -> pd.DataFrame:
    """Create an accession-indexed embedding table."""

    if len(accessions) != len(embeddings):
        raise ValueError(
            "Number of accessions does not match "
            "number of embeddings."
        )

    dataframe = pd.DataFrame(
        embeddings,
        index=accessions,
    )

    dataframe.index.name = "accession"

    return dataframe