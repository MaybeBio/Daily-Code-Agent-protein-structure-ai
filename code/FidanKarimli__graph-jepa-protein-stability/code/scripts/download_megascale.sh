#!/usr/bin/env bash
# Download ThermoMPNN's MegaScale labels and splits into data/raw/thermompnn/
set -euo pipefail

OUT=data/raw/thermompnn
B=https://raw.githubusercontent.com/Kuhlman-Lab/ThermoMPNN/main

mkdir -p "$OUT"
curl -L -o "$OUT/mega_train.csv" "$B/data_all/training/mega_train.csv"
curl -L -o "$OUT/mega_val.csv"   "$B/data_all/training/mega_val.csv"
curl -L -o "$OUT/mega_test.csv"  "$B/data_all/testing/mega_test.csv"

ls -lh "$OUT"
