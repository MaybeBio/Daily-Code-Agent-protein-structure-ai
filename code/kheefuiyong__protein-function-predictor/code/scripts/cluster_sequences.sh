#!/usr/bin/env bash

set -euo pipefail

MMSEQS_BIN="${MMSEQS_BIN:-mmseqs}"

INPUT="data/processed/proteins.fasta"
OUTPUT="data/processed/mmseqs30"
TMP="data/tmp/mmseqs30"

mkdir -p "$TMP"

"$MMSEQS_BIN" easy-cluster \
    "$INPUT" \
    "$OUTPUT" \
    "$TMP" \
    --min-seq-id 0.30 \
    -c 0.80 \
    --cov-mode 0