import json

import pandas as pd

from protein_function_predictor.features import (
    load_embeddings,
)
from protein_function_predictor.modeling import (
    build_modeling_arrays,
)

with open(
    "data/processed/label_vocabulary.json",
    encoding="utf-8",
) as file:
    vocabulary = json.load(file)

embedding_accessions, embeddings = load_embeddings(
    "data/processed/esm2_embeddings.npz"
)

base = "data/processed/splits"

expected_shapes = {
    "train": ((1452, 320), (1452, 10)),
    "validation": ((294, 320), (294, 10)),
    "test": ((289, 320), (289, 10)),
}

for split_name, expected in expected_shapes.items():
    dataframe = pd.read_csv(
        f"{base}/{split_name}.csv"
    )

    features, targets = build_modeling_arrays(
        dataframe,
        vocabulary,
        embedding_accessions,
        embeddings,
    )

    print()
    print(split_name.upper())
    print(f"X shape: {features.shape}")
    print(f"y shape: {targets.shape}")
    print(
        "Positive labels:",
        int(targets.sum()),
    )

    assert features.shape == expected[0]
    assert targets.shape == expected[1]

print()
print("Modeling-array validation PASSED")