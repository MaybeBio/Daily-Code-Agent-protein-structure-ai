#!/usr/bin/env bash
# SCOPe domains for pretraining: ASTRAL SCOPe 2.08, redundancy-filtered at 40% identity.
# About 1 GB, so allow ten minutes or so. Set SUBSET=20 for the smaller 7,943 domain set.
set -euo pipefail

SUBSET=${SUBSET:-40}
OUT=data/raw/scope
BASE=https://scop.berkeley.edu/downloads

mkdir -p "$OUT"
curl -L -o "$OUT/pdbstyle-${SUBSET}.tgz" \
    "$BASE/pdbstyle/pdbstyle-sel-gs-bib-${SUBSET}-2.08.tgz"
curl -L -o "$OUT/astral-${SUBSET}.fa" \
    "$BASE/scopeseq-2.08/astral-scopedom-seqres-gd-sel-gs-bib-${SUBSET}-2.08.fa"

tar -xzf "$OUT/pdbstyle-${SUBSET}.tgz" -C "$OUT"

echo "domain files: $(find "$OUT" -name '*.ent' | wc -l)"
echo "sequences:    $(grep -c '^>' "$OUT/astral-${SUBSET}.fa")"
