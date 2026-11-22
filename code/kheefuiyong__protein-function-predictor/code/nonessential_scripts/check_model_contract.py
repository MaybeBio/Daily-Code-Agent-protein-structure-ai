import joblib
import numpy as np

bundle = joblib.load(
    "models/baseline_logistic.joblib"
)

print("Model bundle")
print("------------")

for key in bundle:
    print(key)

print()
print("C:", bundle["c"])
print("Class weight:", bundle["class_weight"])
print("Embedding model:", bundle["embedding_model"])
print("Pooling:", bundle["pooling"])
print("Embedding dimension:", bundle["embedding_dimension"])
print("Labels:", len(bundle["vocabulary"]))
print("Thresholds:", len(bundle["thresholds"]))

assert bundle["c"] == 0.1
assert bundle["class_weight"] is None

assert (
    bundle["embedding_model"]
    == "facebook/esm2_t6_8M_UR50D"
)

assert (
    bundle["pooling"]
    == "mean_residue_pooling"
)

assert bundle["embedding_dimension"] == 320
assert len(bundle["vocabulary"]) == 10
assert len(bundle["thresholds"]) == 10

thresholds = np.asarray(
    bundle["thresholds"]
)

assert np.isfinite(thresholds).all()
assert np.all(
    (thresholds >= 0.0)
    & (thresholds <= 1.0)
)

pipeline = bundle["classifier"]

ovr = pipeline.named_steps[
    "classifier"
]

assert len(ovr.estimators_) == 10

assert all(
    estimator.C == 0.1
    for estimator in ovr.estimators_
)

print()
print("Locked model bundle PASSED")