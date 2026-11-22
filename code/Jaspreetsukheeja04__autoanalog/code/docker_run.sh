#!/bin/bash

DISEASE=${1:-"endometriosis"}
RECEPTOR=${2:-"P2Y12"}
PDB_ID=${3:-"4NTJ"}
INHIBITOR=${4:-"CC1=CC=C(C=C1)S(=O)(=O)NC2=NC=C(C=N2)C3=CC=CC=N3"}
REF_IC50=${5:-89}
REF_NAME=${6:-"AZD1283"}

mkdir -p $(pwd)/output

echo "======================================="
echo "AutoAnalog v2.0 — Docker Run"
echo "Disease:   ${DISEASE}"
echo "Receptor:  ${RECEPTOR}"
echo "PDB ID:    ${PDB_ID}"
echo "Reference: ${REF_NAME} IC50=${REF_IC50}nM"
echo "======================================="

sudo docker run --rm \
    -v $(pwd)/output:/pipeline/results \
    autoanalog:v2.0 \
    "${DISEASE}" \
    "${RECEPTOR}" \
    "${PDB_ID}" \
    "${INHIBITOR}" \
    "${REF_IC50}" \
    "${REF_NAME}"

echo "======================================="
echo "Done!"
echo "Report: $(pwd)/output/report/final_report.pdf"
echo "======================================="
