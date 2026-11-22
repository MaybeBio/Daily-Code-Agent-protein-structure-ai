"""The one table a controls run writes: `controls.json` for programs and a draft result record for readers.

Every control has a row whether it was measured, not measured (with the reason) or dropped for the time budget. The
record's `metrics` block carries each measured control's test headline, so `index/metrics.md` lists them beside the
models trained on the same release revision.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .metrics import HEADLINE
from .release import Release


TABLE_SCHEMA = "controls_table_v1"
TABLE_FILE = "controls.json"
RECORD_FILE = "README.md"
NOT_SNAKE = re.compile(r"[^a-z0-9]+")
METRIC_ORDER = {
    "regression": ("spearman", "pearson", "rmse", "mae"),
    "binary": ("pr_auc", "pr_auc_trapezoidal", "roc_auc", "balanced_mcc", "balanced_mcc_std", "threshold"),
    "multiclass": ("macro_f1", "accuracy", "mcc"),
    "multilabel": ("micro_pr_auc", "micro_roc_auc", "macro_pr_auc", "columns_scored", "micro_balanced_mcc",
                   "micro_balanced_mcc_std", "threshold"),
}


@dataclass
class ControlRow:
    """One control's row: its status, the head and features that made it, its scores and the headline's interval."""

    control: str
    status: str  # measured, not measured, dropped
    reason: str | None
    head: str | None
    hyperparameter: dict[str, float]
    identity: dict[str, Any]
    width: int
    scores: dict[str, dict[str, float | None]]  # split -> metric -> value
    interval: dict[str, Any] | None
    seconds: float


def snake(text: str) -> str:
    return NOT_SNAKE.sub("_", text.lower()).strip("_")


def shown(value: float | None, places: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{places}f}" if abs(value) < 1e6 else f"{value:.3g}"


def headline_sentence(release: Release, rows: Sequence[ControlRow]) -> str:
    """The record's headline, under 25 words: the best control's test headline against the label prior."""
    headline = HEADLINE[release.task_type]
    measured = [row for row in rows if row.status == "measured" and row.control != "label_prior"
                and row.scores["test"].get(headline) is not None]
    prior = next((row for row in rows if row.control == "label_prior"), None)
    prior_value = None if prior is None else prior.scores["test"].get(headline)
    controls_total = sum(1 for row in rows if row.control != "label_prior")
    if not measured:
        return f"No control measured on {release.dataset_id}: {controls_total} of {controls_total} controls not measured or dropped."
    best = max(measured, key=lambda row: row.scores["test"][headline] or float("-inf"))
    return (f"{shown(best.scores['test'][headline])} test {headline} for the best control ({best.control}) against "
            f"{shown(prior_value)} for the label prior on {release.dataset_id}; {len(measured)} of {controls_total} controls measured.")


def metrics_block(release: Release, rows: Sequence[ControlRow]) -> list[dict[str, Any]]:
    headline = HEADLINE[release.task_type]
    block = []
    for row in rows:
        if row.status != "measured":
            continue
        value = row.scores["test"].get(headline)
        if value is not None:
            block.append({"benchmark": snake(release.dataset_id), "metric": headline, "value": round(value, 6),
                          "model": f"control_{row.control}", "split": "test"})
    return block


def markdown_table(release: Release, rows: Sequence[ControlRow]) -> list[str]:
    """The result table: one line per control, the headline's interval beside it, every metric of the task after."""
    headline = HEADLINE[release.task_type]
    columns = METRIC_ORDER[release.task_type]
    lines = [f"| Control | Status | Head | Validation {headline} | Test {headline} (95% CI) | "
             + " | ".join(name for name in columns if name != headline) + " | Seconds |",
             "|---|---|---|---|---|" + "---|" * len([name for name in columns if name != headline]) + "---|"]
    for row in rows:
        if row.status != "measured":
            lines.append(f"| {row.control} | {row.status}: {row.reason} | | | | " + " | " * len([c for c in columns if c != headline])
                         + f"{row.seconds:.0f} |")
            continue
        head = row.head or ""
        if row.hyperparameter:
            head += " (" + ", ".join(f"{name}={value:g}" for name, value in row.hyperparameter.items()) + ")"
        test = row.scores["test"]
        band = ""
        if row.interval and row.interval.get("low") is not None:
            band = f" [{shown(row.interval['low'])}, {shown(row.interval['high'])}]"
        others = " | ".join(shown(test.get(name)) for name in columns if name != headline)
        lines.append(f"| {row.control} | measured | {head} | {shown(row.scores['validation'].get(headline))} | "
                     f"{shown(test.get(headline))}{band} | {others} | {row.seconds:.0f} |")
    return lines


def record_text(result_id: str, release: Release, rows: Sequence[ControlRow], *, store_revision: str | None,
                seconds: float, experiment: str | None, command: str | None, written: str) -> str:
    """The draft result record, frontmatter and body."""
    headline = headline_sentence(release, rows)
    front = ["---", f"id: {result_id}", "kind: result", "status: draft", "aliases:", f"- {result_id}"]
    if experiment:
        front.append(f"experiment: experiment:{experiment}")
    front.append(f"headline: {json.dumps(headline)}")
    front.append(f"keywords: [controls, {snake(release.dataset_id)}, label_prior, random_features, one_hot_sequence, "
                 "random_backbone, metadata_only]")
    block = metrics_block(release, rows)
    if block:
        front.append("metrics:")
        for entry in block:
            front.append("- {" + ", ".join(f"{key}: {json.dumps(value)}" for key, value in entry.items()) + "}")
    front.append("---")
    replicates = next((row.interval["replicates"] for row in rows if row.interval), None)
    not_measured = [row for row in rows if row.status != "measured"]
    body = [
        "", f"# Controls on {release.dataset_id}", "", "## Headline", "", headline, "",
        f"Written by `python -m foundry.controls` on {written}, in {seconds:.0f} s, on the release at `{release.directory.name}` "
        f"(dataset.json SHA-256 `{release.manifest_sha256}`, task `{release.task_type}`, {release.width} label column(s)). "
        "The heads are chosen on the validation split by the headline metric and reported on test. The interval resamples "
        f"whole finest clusters of the test split, {replicates} replicates under seed 42.", "",
        "## Table", "", *markdown_table(release, rows), "",
    ]
    if not_measured:
        body += ["## Not measured", ""]
        body += [f"- `{row.control}`: {row.status}, {row.reason}." for row in not_measured]
        body += [""]
    body += ["## How each control was made", ""]
    for row in rows:
        if row.status == "measured":
            body.append(f"- `{row.control}` ({row.width} columns): " + ", ".join(
                f"{key} {json.dumps(value)}" for key, value in row.identity.items()) + ".")
    body += ["", "The training split sets the feature standardization and the categorical levels; nothing of the validation or "
             "test split touches a head before it is scored. A ridge head is solved from the normal equations at alphas 0.1 to "
             "1000, a logistic head at inverse regularizations 0.01 to 10 (scikit-learn, lbfgs). Unobserved multilabel entries "
             "count as negatives in training and are left out of every score. `controls.json` beside this file holds the same "
             "rows with every number.", ""]
    if store_revision:
        body += [f"The random backbone's rows come from `Synthyra/esmc_embeddings` at revision `{store_revision}`.", ""]
    if command:
        body += ["## Reproduce", "", "```bash", command, "```", ""]
    return "\n".join(front + body)


def write_table(result_directory: Path, *, release: Release, rows: Sequence[ControlRow], store_revision: str | None,
                seconds: float, experiment: str | None = None, command: str | None = None,
                controls: Sequence[str] = ()) -> tuple[Path, Path]:
    """Write `controls.json` and the result record into `result_directory`; returns their paths."""
    result_directory.mkdir(parents=True, exist_ok=True)
    written = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    table: dict[str, Any] = {
        "schema": TABLE_SCHEMA, "dataset_id": release.dataset_id, "release_directory": release.directory.name,
        "dataset_json_sha256": release.manifest_sha256, "task_type": release.task_type, "label_columns": release.width,
        "store_revision": store_revision, "controls_requested": list(controls), "headline": HEADLINE[release.task_type],
        "written": written, "seconds": round(seconds, 1), "rows": [asdict(row) for row in rows],
    }
    table_path = result_directory / TABLE_FILE
    table_path.write_text(json.dumps(table, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    record_path = result_directory / RECORD_FILE
    record_path.write_text(record_text(result_directory.name, release, rows, store_revision=store_revision, seconds=seconds,
                                       experiment=experiment, command=command, written=written), encoding="utf-8", newline="\n")
    return table_path, record_path


def read_table(path: Path) -> Mapping[str, Any]:
    """A written `controls.json`, checked to be this schema."""
    table = json.loads(path.read_text(encoding="utf-8"))
    if table.get("schema") != TABLE_SCHEMA:
        raise ValueError(f"{path} has schema {table.get('schema')!r}; expected {TABLE_SCHEMA}.")
    return table
