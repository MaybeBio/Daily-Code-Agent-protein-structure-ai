"""Every control of the rubric on one release, one command, one table.

`python -m foundry.controls --release DIR` runs the random-features, one-hot-sequence, random-weight-backbone and
metadata-only controls on a canonical property release with CPU heads, scores them beside the label prior with the
task's metrics and a cluster-bootstrap interval on the headline, and writes `controls.json` and a draft result record.
NumPy is imported here; pyarrow, scikit-learn, scipy and torch load inside the functions that need them.
"""

from .features import CONTROLS, METADATA_ONLY, ONE_HOT_SEQUENCE, RANDOM_BACKBONE, RANDOM_FEATURES, Features
from .heads import Fit, fit_head, prior_fit
from .metrics import HEADLINE, REPLICATES, SEED, cluster_bootstrap, task_scores
from .release import Release, Split, decode_labels, read_release
from .run import Run, run_controls
from .table import TABLE_SCHEMA, ControlRow, read_table, write_table


__all__ = [
    "CONTROLS",
    "ControlRow",
    "Features",
    "Fit",
    "HEADLINE",
    "METADATA_ONLY",
    "ONE_HOT_SEQUENCE",
    "RANDOM_BACKBONE",
    "RANDOM_FEATURES",
    "REPLICATES",
    "Release",
    "Run",
    "SEED",
    "Split",
    "TABLE_SCHEMA",
    "cluster_bootstrap",
    "decode_labels",
    "fit_head",
    "prior_fit",
    "read_release",
    "read_table",
    "run_controls",
    "task_scores",
    "write_table",
]
