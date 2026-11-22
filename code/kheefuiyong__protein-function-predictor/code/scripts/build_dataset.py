import argparse
import json
from collections import Counter
from pathlib import Path

from protein_function_predictor.dataset import (
    load_uniprot_tsv,
    parse_go_terms,
    remove_duplicate_sequences,
    remove_invalid_records,
    select_frequent_labels,
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Build the protein-function prediction dataset."
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to the raw UniProt TSV file.",
    )

    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for processed dataset files.",
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of GO Molecular Function labels to retain.",
    )

    parser.add_argument(
        "--min-positives",
        type=int,
        default=100,
        help="Minimum number of positive proteins required per label.",
    )

    return parser.parse_args()


def main() -> None:
    """Build and save the processed protein-function dataset."""

    args = parse_args()

    # 1. Load raw UniProt data.
    dataframe = load_uniprot_tsv(args.input)
    raw_count = len(dataframe)

    # 2. Normalize sequences and remove invalid records.
    dataframe = remove_invalid_records(dataframe)
    valid_count = len(dataframe)

    # 3. Remove exact duplicate protein sequences.
    dataframe = remove_duplicate_sequences(dataframe)
    deduplicated_count = len(dataframe)

    # 4. Parse GO Molecular Function identifiers.
    dataframe["go_terms"] = dataframe["go_mf"].apply(parse_go_terms)

    # 5. Select the most frequent eligible GO labels.
    labels = select_frequent_labels(
        dataframe,
        top_k=args.top_k,
        min_positives=args.min_positives,
    )

    if len(labels) != args.top_k:
        raise ValueError(
            f"Only {len(labels)} labels satisfy "
            f"min_positives={args.min_positives}; "
            f"expected {args.top_k}."
        )

    # 6. Keep only selected labels for each protein.
    dataframe["selected_labels"] = dataframe["go_terms"].apply(
        lambda terms: [
            label
            for label in labels
            if label in terms
        ]
    )

    # 7. Remove proteins with none of the selected labels.
    dataframe = dataframe.loc[
        dataframe["selected_labels"].map(bool)
    ].copy()

    # 8. Convert labels to semicolon-separated strings.
    dataframe["labels"] = dataframe["selected_labels"].apply(";".join)

    output_dataframe = dataframe[
        ["accession", "sequence", "labels"]
    ].copy()

    # 9. Create the output directory.
    args.output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    proteins_path = args.output_dir / "proteins.csv"
    vocabulary_path = args.output_dir / "label_vocabulary.json"
    summary_path = args.output_dir / "dataset_summary.json"

    # 10. Save processed proteins.
    output_dataframe.to_csv(
        proteins_path,
        index=False,
    )

    # 11. Save label vocabulary.
    vocabulary_path.write_text(
        json.dumps(labels, indent=2) + "\n",
        encoding="utf-8",
    )

    # 12. Count positive proteins for each selected label.
    label_counts = Counter(
        label
        for terms in dataframe["selected_labels"]
        for label in terms
    )

    # 13. Create dataset summary.
    summary = {
        "raw_records": raw_count,
        "valid_records": valid_count,
        "deduplicated_records": deduplicated_count,
        "final_proteins": len(output_dataframe),
        "number_of_labels": len(labels),
        "minimum_positives_required": args.min_positives,
        "duplicate_sequences": int(
            output_dataframe["sequence"].duplicated().sum()
        ),
        "maximum_sequence_length": int(
            output_dataframe["sequence"].str.len().max()
        ),
        "label_counts": {
            label: label_counts[label]
            for label in labels
        },
    }

    # 14. Save dataset summary.
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )

    # Also print the summary to the terminal.
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()