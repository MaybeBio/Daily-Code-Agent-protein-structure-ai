import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from protein_function_predictor.embedding import (
    MODEL_CHECKPOINT,
    ProteinEmbedder,
)
from protein_function_predictor.features import (
    save_embeddings,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate cached ESM2 embeddings "
            "for processed proteins."
        )
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--device",
        default=None,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    dataframe = pd.read_csv(
        args.input
    )

    required_columns = {
        "accession",
        "sequence",
    }

    missing = (
        required_columns
        - set(dataframe.columns)
    )

    if missing:
        raise ValueError(
            f"Missing required columns: "
            f"{sorted(missing)}"
        )

    if dataframe["accession"].duplicated().any():
        raise ValueError(
            "Duplicate accessions detected."
        )

    embedder = ProteinEmbedder(
        device=args.device
    )

    embedding_batches = []

    total = len(dataframe)

    for start in range(
        0,
        total,
        args.batch_size,
    ):
        stop = min(
            start + args.batch_size,
            total,
        )

        batch = dataframe.iloc[
            start:stop
        ]

        embeddings = (
            embedder
            .embed_batch(
                batch["sequence"].tolist()
            )
            .numpy()
        )

        embedding_batches.append(
            embeddings
        )

        print(
            f"Embedded {stop}/{total} proteins"
        )

    embedding_matrix = np.concatenate(
        embedding_batches,
        axis=0,
    )

    save_embeddings(
        args.output,
        dataframe["accession"].tolist(),
        embedding_matrix,
    )

    manifest = {
        "model_checkpoint": MODEL_CHECKPOINT,
        "pooling": "mean_residue_pooling",
        "number_of_proteins": len(dataframe),
        "embedding_dimension": int(
            embedding_matrix.shape[1]
        ),
        "dtype": str(
            embedding_matrix.dtype
        ),
        "batch_size": args.batch_size,
        "device": str(
            embedder.device
        ),
    }

    args.manifest.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    args.manifest.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print(
        f"Saved embeddings to "
        f"{args.output}"
    )

    print(
        f"Saved manifest to "
        f"{args.manifest}"
    )


if __name__ == "__main__":
    main()