#!/bin/bash

MODE=${1:-"pipeline"}

if [ "$MODE" = "app" ]; then
    echo "Starting AutoAnalog Web App..."
    sudo docker run --rm \
        -p 8501:8501 \
        -v $(pwd)/results:/pipeline/results \
        autoanalog:v2.0 app
    echo "Open: http://localhost:8501"
    exit 0
fi

DISEASE=${2:-"endometriosis"}
RECEPTOR=${3:-"P2Y12"}
PDB_ID=${4:-"4NTJ"}
INHIBITOR=${5:-"CC1=CC=C(C=C1)S(=O)(=O)NC2=NC=C(C=N2)C3=CC=CC=N3"}
REF_IC50=${6:-89}
REF_NAME=${7:-"AZD1283"}

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
