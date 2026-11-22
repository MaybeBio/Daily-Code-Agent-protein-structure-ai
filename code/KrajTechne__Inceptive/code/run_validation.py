"""Step 2: validate the best BindCraft2 designs with Optimus.

Usage:
    python -m modal run run_validation.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml
    python -m modal run run_validation.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml --dry-run

What it does:
  1. A small CPU function on Modal reads the top N designs (or all, if selection.top_n is left out)
     from the design step and builds the CSV that Optimus expects.
  2. The CSV and an Optimus config are saved on your machine in results/<run_name>/.
  3. Optimus (the optimus/ submodule) is launched, with its outputs sent to the
     same `inceptive-runs` Volume, in <run_name>/validation/ (or <run_name>/<validate.output_name>/).
"""
import io
import os
import subprocess
import sys

import yaml

from config_loader import (load_config, local_results_dir, require_keys,
                           selection_settings, validation_volume_dir)
from modal_app import (OPTIMUS_RUNS_DIR, RUNS_DIR, RUNS_VOLUME_NAME, app,
                       bridge_image, runs_volume)


# Runs remotely on a CPU. It reads the design results straight from the Volume.
@app.function(image=bridge_image, volumes={RUNS_DIR: runs_volume})
def build_designs_csv(run_name: str, top_n, binder_chain: str, identical_segments: dict) -> str:  # top_n: a number, or None for all designs
    from design_table import build_design_table

    runs_volume.reload()  # make sure we see the latest saved design results
    designs = build_design_table(run_name, top_n, binder_chain, identical_segments,
                                 read_mount=RUNS_DIR, ref_mount=OPTIMUS_RUNS_DIR)
    out = io.StringIO()
    designs.to_csv(out, index=False)
    return out.getvalue()


# Runs on your own computer.
@app.local_entrypoint()
def main(config: str, dry_run: bool = False):
    cfg = load_config(config)
    require_keys(cfg, ["run_name", "selection", "validate"], where=config)
    run_name = cfg["run_name"]
    top_n, binder_chain, identical_segments = selection_settings(cfg, where=config)

    # Optimus reads this as its --config file. input and output_dir are filled in for you.
    results_dir = local_results_dir(cfg)
    csv_path = os.path.abspath(os.path.join(results_dir, "designs_for_validation.csv"))
    optimus_cfg = {
        **{k: v for k, v in cfg["validate"].items() if k != "output_name"},  # output_name is ours, not Optimus's
        "input": csv_path,
        "output_dir": validation_volume_dir(cfg),
    }
    print(f"Run name  : {run_name}")
    print(f"Selection : {'all designs' if top_n is None else f'top {top_n} designs'}, binder chain {binder_chain}")
    if identical_segments:
        print(f"Identical target segments: {identical_segments}")
    print(f"Optimus config:\n{yaml.safe_dump(optimus_cfg, sort_keys=False)}")
    if dry_run:
        print("Dry run, nothing launched.")
        return

    # 1. Build the CSV on Modal and save it locally.
    csv_text = build_designs_csv.remote(run_name, top_n, binder_chain, identical_segments)
    os.makedirs(results_dir, exist_ok=True)
    with open(csv_path, "w", newline="") as f:
        f.write(csv_text)
    optimus_cfg_path = os.path.abspath(os.path.join(results_dir, "optimus_config.yaml"))
    with open(optimus_cfg_path, "w") as f:
        yaml.safe_dump(optimus_cfg, f, sort_keys=False)
    print(f"Saved {csv_path}")

    # 2. Launch Optimus. OPTIMUS_OUTPUTS_VOLUME tells it which Volume to write to;
    #    PYTHONUTF8 stops Modal's CLI crashing on Windows consoles.
    env = {**os.environ, "OPTIMUS_OUTPUTS_VOLUME": RUNS_VOLUME_NAME, "PYTHONUTF8": "1"}
    subprocess.run(
        [sys.executable, "-m", "modal", "run", "--detach",
         "modal_run_validation.py", "--config", optimus_cfg_path],
        cwd="optimus", env=env, check=True,
    )
    print(f"Validation running. Results will appear at {validation_volume_dir(cfg)}/ on Volume '{RUNS_VOLUME_NAME}'.")
    print(f"Check with: python -m modal volume ls {RUNS_VOLUME_NAME} {validation_volume_dir(cfg)}")
