import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export processed protein sequences to FASTA."
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

    return parser.parse_args()


def export_fasta(
    dataframe: pd.DataFrame,
    output_path: Path,
) -> None:
    """Write protein sequences as an LF-terminated FASTA file."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as fasta_file:
        for row in dataframe.itertuples(index=False):
            fasta_file.write(
                f">{row.accession}\n"
                f"{row.sequence}\n"
            )


def main() -> None:
    args = parse_args()

    dataframe = pd.read_csv(args.input)

    required_columns = {
        "accession",
        "sequence",
    }

    missing = required_columns - set(dataframe.columns)

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    export_fasta(
        dataframe,
        args.output,
    )

    print(
        f"Wrote {len(dataframe)} sequences "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()