#!/usr/bin/env bash
# Download MegaScale AlphaFold structures (Tsuboyama et al. 2023, Zenodo record 7992926)
set -euo pipefail

ZIP=data/raw/AlphaFold_model_PDBs.zip
OUT=data/raw/megascale_pdbs
URL="https://zenodo.org/api/records/7992926/files/AlphaFold_model_PDBs.zip/content"

mkdir -p "$OUT"
curl -L -o "$ZIP" "$URL"
unzip -q -o "$ZIP" -d "$OUT"

echo "pdb files:"; find "$OUT" -name "*.pdb" | wc -l
echo "examples:";  find "$OUT" -name "*.pdb" | head -3
rm -rf "$OUT/__MACOSX"          # macOS metadata files from the zip, not structures

