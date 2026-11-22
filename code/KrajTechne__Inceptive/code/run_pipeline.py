"""Run the whole pipeline: design -> validation -> report.

Usage:
    python run_pipeline.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml
    python run_pipeline.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml --dry-run
    python run_pipeline.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml --skip-design   # reuse finished design results

This is a plain Python script (not a Modal app). It just runs the same commands
you would type by hand, one after the other, and waits for validation to finish
(Optimus runs in the background on Modal, so we watch its result files).
"""
import argparse
import os
import subprocess
import sys
import time

import pandas as pd

from config_loader import (load_config, local_results_dir, require_keys,
                           validation_volume_dir)
from volume_utils import volume_get


def run_step(title, command):
    """Run one pipeline step, showing its output, and stop everything if it fails."""
    print(f"\n=== {title} ===\n$ {' '.join(command)}", flush=True)
    env = {**os.environ, "PYTHONUTF8": "1"}  # stops Modal crashing on Windows consoles
    result = subprocess.run(command, env=env)
    if result.returncode != 0:
        raise SystemExit(f"Step failed: {title} (exit code {result.returncode}). Fix it, then re-run; "
                         f"use --skip-design / --skip-validation to avoid repeating finished steps.")


def count_finished_jobs(cfg):
    """How many validation jobs have finished (succeeded or failed), read from the Volume."""
    finished = 0
    for name in ("validation_results.csv", "failures.csv"):
        local = os.path.join(local_results_dir(cfg), name)
        if os.path.exists(local):
            os.remove(local)  # never count a stale copy from an earlier run
        if volume_get(f"{validation_volume_dir(cfg)}/{name}", local):
            finished += len(pd.read_csv(local))
    return finished


def wait_for_validation(cfg, expected_jobs, timeout_hours, poll_seconds):
    """Optimus runs in the background, so poll its result files until every job is accounted for."""
    print(f"\nWaiting for {expected_jobs} validation jobs (checking every {poll_seconds}s)...", flush=True)
    deadline = time.time() + timeout_hours * 3600
    while time.time() < deadline:
        finished = count_finished_jobs(cfg)
        print(f"  {finished} of {expected_jobs} jobs finished", flush=True)
        if finished >= expected_jobs:
            return
        time.sleep(poll_seconds)
    raise SystemExit(f"Timed out after {timeout_hours} h. Jobs may still be running on Modal; "
                     f"run `python report.py --config ...` later to build the report.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    parser.add_argument("--skip-design", action="store_true", help="reuse existing design results")
    parser.add_argument("--skip-validation", action="store_true", help="reuse existing validation results")
    parser.add_argument("--timeout-hours", type=float, default=4, help="how long to wait for validation")
    parser.add_argument("--poll-seconds", type=int, default=60)
    args = parser.parse_args()

    cfg = load_config(args.config)
    # the design section is only needed when this run also does the design step
    require_keys(cfg, ["run_name", "selection", "validate", "report"] + ([] if args.skip_design else ["design"]),
                 where=args.config)
    run_name = cfg["run_name"]

    modal_run = [sys.executable, "-m", "modal", "run"]
    design_cmd = modal_run + ["--detach", "run_design.py", "--config", args.config]
    validate_cmd = modal_run + ["run_validation.py", "--config", args.config]
    report_cmd = [sys.executable, "report.py", "--config", args.config]

    steps = [
        ("1. Design with BindCraft2", design_cmd, not args.skip_design),
        ("2. Validate with Optimus", validate_cmd, not args.skip_validation),
        ("3. Wait for validation to finish", None, not args.skip_validation),
        ("4. Build final report", report_cmd, True),
    ]
    print(f"Pipeline for run '{run_name}'")
    for title, command, enabled in steps:
        print(f"  [{'x' if enabled else ' '}] {title}")
    if args.dry_run:
        print("Dry run, nothing launched.")
        return

    if not args.skip_design:
        run_step(*steps[0][:2])
    if not args.skip_validation:
        run_step(*steps[1][:2])
        # How many jobs to expect: designs picked x models x seeds (capped by Optimus's max_jobs).
        designs = pd.read_csv(os.path.join(local_results_dir(cfg), "designs_for_validation.csv"))
        validate_cfg = cfg["validate"]
        expected = len(designs) * len(validate_cfg["models"]) * len(validate_cfg["seeds"])
        expected = min(expected, validate_cfg.get("max_jobs", 200))
        wait_for_validation(cfg, expected, args.timeout_hours, args.poll_seconds)
    run_step(*steps[3][:2])


if __name__ == "__main__":
    main()
