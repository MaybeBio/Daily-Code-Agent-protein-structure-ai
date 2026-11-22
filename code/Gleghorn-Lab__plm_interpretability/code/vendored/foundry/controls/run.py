"""Run every control of the rubric on one release and write the one table every model on that revision links.

The controls run in the rubric's order on the release's cached rows and CPU heads, each timed. A control whose
features cannot be made (the backbone store unreachable, say) is recorded as not measured with the reason, and a
control that would start after the time budget is spent is recorded as dropped, so the table always names every
control. The label prior is scored beside them.
"""

from __future__ import annotations

import time

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import metrics
from .features import (
    CONTROLS, METADATA_ONLY, RANDOM_BACKBONE, BackboneReader, Features, backbone_features, metadata_features,
    synthetic_features,
)
from .heads import Fit, fit_head, prior_fit
from .release import Release, read_release
from .table import ControlRow, write_table


TIME_BUDGET_SECONDS = 30 * 60
MULTILABEL_REPLICATES = 200  # a micro replicate passes every observed entry; the rubric's budget is 30 minutes


@dataclass
class Run:
    """What one invocation did: the release, the controls' rows, and the timings."""

    release: Release
    rows: list[ControlRow] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> float:
        return time.time() - self.started


def control_features(control: str, release: Release, *, store_revision: str | None, reader: BackboneReader | None) -> Features:
    if control == METADATA_ONLY:
        return metadata_features(release)
    if control == RANDOM_BACKBONE:
        assert store_revision is not None, "run_controls checks the store revision before any control runs"
        return backbone_features(release, revision=store_revision, reader=reader)
    return synthetic_features(control, release)


def score_fit(fit: Fit, release: Release, *, replicates: int) -> tuple[dict[str, dict[str, float | None]], dict[str, Any]]:
    """Validation and test scores of a fit, and the cluster-bootstrap interval of the test headline."""
    validation, test = release.splits["validation"], release.splits["test"]
    validation_scores = metrics.task_scores(release.task_type, validation.labels, validation.observed, fit.predictions["validation"],
                                            release.width, None)
    threshold = metrics.carried_threshold(release.task_type, validation_scores)
    test_scores = metrics.task_scores(release.task_type, test.labels, test.observed, fit.predictions["test"], release.width, threshold)
    headline = metrics.HEADLINE[release.task_type]
    statistic = metrics.headline_statistic(release.task_type, test.labels, test.observed, fit.predictions["test"], release.width)
    low, high = metrics.cluster_bootstrap(statistic, test.cluster, replicates=replicates, seed=metrics.SEED)
    interval = {"metric": headline, "split": "test", "low": low, "high": high, "replicates": replicates, "seed": metrics.SEED,
                "unit": "finest cluster"}
    return {"validation": validation_scores, "test": test_scores}, interval


def run_controls(release_directory: Path, result_directory: Path, *, controls: Sequence[str] = CONTROLS,
                 store_revision: str | None = None, replicates: int | None = None,
                 time_budget_seconds: float = TIME_BUDGET_SECONDS, reader: BackboneReader | None = None,
                 experiment: str | None = None, command: str | None = None) -> Run:
    """Run `controls` on the release at `release_directory` and write `controls.json` and the result record.

    `reader` replaces the Hub for the backbone rows, as a test with a local store does. `replicates` defaults to
    `metrics.REPLICATES`, or MULTILABEL_REPLICATES on a multilabel release.
    """
    unknown = sorted(set(controls) - set(CONTROLS))
    if unknown:
        raise ValueError(f"unknown controls {unknown}; the rubric's are {list(CONTROLS)}")
    if RANDOM_BACKBONE in controls and store_revision is None:
        raise ValueError("the random backbone needs --store-revision, the commit of Synthyra/esmc_embeddings to read")
    run = Run(read_release(release_directory))
    release = run.release
    draws = replicates if replicates is not None else (MULTILABEL_REPLICATES if release.task_type == "multilabel" else metrics.REPLICATES)
    prior_started = time.time()
    scores, interval = score_fit(prior_fit(release), release, replicates=draws)
    run.rows.append(ControlRow("label_prior", "measured", None, "label_prior", {}, {"source": "training split labels"}, 0,
                               scores, interval, time.time() - prior_started))
    for control in controls:
        started = time.time()
        if run.elapsed > time_budget_seconds:
            run.rows.append(ControlRow(control, "dropped", f"the time budget of {time_budget_seconds:.0f} s was spent after "
                                       f"{run.elapsed:.0f} s", None, {}, {}, 0, {}, None, 0.0))
            continue
        try:
            features = control_features(control, release, store_revision=store_revision, reader=reader)
        except (OSError, KeyError, ValueError, RuntimeError) as error:
            run.rows.append(ControlRow(control, "not measured", f"{type(error).__name__}: {error}", None, {}, {}, 0, {}, None,
                                       time.time() - started))
            continue
        fit = fit_head(features, release)
        scores, interval = score_fit(fit, release, replicates=draws)
        run.rows.append(ControlRow(control, "measured", None, fit.head, fit.hyperparameter, features.identity, features.width,
                                   scores, interval, time.time() - started))
    write_table(result_directory, release=release, rows=run.rows, store_revision=store_revision, seconds=run.elapsed,
                experiment=experiment, command=command, controls=list(controls))
    return run


def summary_lines(run: Run) -> list[str]:
    """One line per control for the terminal: status, the test headline and its interval, and the seconds it took."""
    headline = metrics.HEADLINE[run.release.task_type]
    lines = []
    for row in run.rows:
        if row.status != "measured":
            lines.append(f"{row.control:<18} {row.status}: {row.reason}")
            continue
        value = row.scores["test"].get(headline)
        shown = "nan" if value is None else f"{value:.4f}"
        low, high = (row.interval or {}).get("low"), (row.interval or {}).get("high")
        band = "" if low is None or high is None else f" [{low:.4f}, {high:.4f}]"
        lines.append(f"{row.control:<18} {headline} {shown}{band}  {row.seconds:.1f} s")
    return lines
