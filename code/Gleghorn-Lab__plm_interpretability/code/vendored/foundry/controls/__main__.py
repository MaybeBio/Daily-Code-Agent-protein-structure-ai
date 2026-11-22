"""`python -m foundry.controls --release DIR --result DIR [--store-revision SHA] [--controls ...]`."""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from pathlib import Path

from .features import CONTROLS
from .run import TIME_BUDGET_SECONDS, run_controls, summary_lines


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m foundry.controls", description=(
        "Run every control of the rubric (random features, one-hot sequence, random-weight backbone, metadata only) "
        "on one canonical release with CPU heads, and write one table."))
    parser.add_argument("--release", type=Path, required=True, help="directory holding dataset.json and the split parquet files")
    parser.add_argument("--result", type=Path, default=None,
                        help="directory for controls.json and the result record; default results/serving/production_suite/<date>_controls_<dataset_id>")
    parser.add_argument("--controls", nargs="+", default=list(CONTROLS), choices=list(CONTROLS), metavar="CONTROL",
                        help=f"which controls to run; default all of {', '.join(CONTROLS)}")
    parser.add_argument("--store-revision", default=None, help="commit of Synthyra/esmc_embeddings holding esmc_300_random/pooled")
    parser.add_argument("--replicates", type=int, default=None, help="bootstrap replicates; default 1000, 200 on a multilabel release")
    parser.add_argument("--time-budget", type=float, default=TIME_BUDGET_SECONDS, help="seconds after which remaining controls are dropped")
    parser.add_argument("--experiment", default=None, help="experiment id the result record answers to, when there is one")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    result_directory = arguments.result
    if result_directory is None:
        import json

        dataset_id = json.loads((arguments.release / "dataset.json").read_text(encoding="utf-8"))["dataset_id"]
        result_directory = Path("results/serving/production_suite") / f"{dt.date.today():%Y-%m-%d}_controls_{dataset_id}"
    command = "python -m foundry.controls " + " ".join(sys.argv[1:]) if argv is None else None
    run = run_controls(arguments.release, result_directory, controls=arguments.controls, store_revision=arguments.store_revision,
                       replicates=arguments.replicates, time_budget_seconds=arguments.time_budget, experiment=arguments.experiment,
                       command=command)
    for line in summary_lines(run):
        print(line)
    print(f"wrote {result_directory / 'controls.json'} and {result_directory / 'README.md'} in {run.elapsed:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
