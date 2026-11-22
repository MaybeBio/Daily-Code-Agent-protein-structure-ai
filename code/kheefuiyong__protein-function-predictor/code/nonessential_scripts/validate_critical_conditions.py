import json

path = "data/processed/dataset_summary.json"

with open(path, encoding="utf-8") as f:
    summary = json.load(f)

n_labels = summary["number_of_labels"]
duplicates = summary["duplicate_sequences"]
label_counts = summary["label_counts"]
minimum_positives = min(label_counts.values())

print("Dataset validation")
print("------------------")
print(f"Number of labels:       {n_labels}")
print(f"Duplicate sequences:    {duplicates}")
print(f"Minimum positives:      {minimum_positives}")
print()

assert n_labels == 10, (
    f"FAILED: expected 10 labels, found {n_labels}"
)

assert duplicates == 0, (
    f"FAILED: found {duplicates} duplicate sequences"
)

assert minimum_positives >= 100, (
    f"FAILED: minimum label count is {minimum_positives}"
)

print("Dataset validation PASSED")