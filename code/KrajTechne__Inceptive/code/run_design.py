"""Step 1: run BindCraft2 on a Modal GPU.

Usage:
    python -m modal run run_design.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml
    python -m modal run run_design.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml --dry-run
    python -m modal run --detach run_design.py --config inputs/configs_pipeline/pdl1_denovo_test.yaml --spawn   # returns at once; safe to close the terminal

Results are saved on the `inceptive-runs` Volume under <run_name>/design/.
Re-running with the same run_name resumes where BindCraft2 left off.
"""
import json
import os
import subprocess

from config_loader import load_config, require_keys
from modal_app import (LOCAL_TARGETS_DIR, RUNS_DIR, TARGETS_DIR, WEIGHTS_DIR,
                       app, bindcraft_image, runs_volume, weights_volume)

COMMIT_EVERY_SECONDS = 300  # save progress to the Volume this often


# This function runs remotely, inside the container on a GPU.
# Its GPU and timeout are filled in later (see main) so they come from the config.
@app.function(
    image=bindcraft_image,
    volumes={RUNS_DIR: runs_volume, WEIGHTS_DIR: weights_volume},
)
def design(run_name: str, bindcraft_settings: dict):
    design_dir = f"{RUNS_DIR}/{run_name}/design"
    os.makedirs(design_dir, exist_ok=True)

    # BindCraft2 reads a JSON settings file, so write the config out as one.
    settings = {**bindcraft_settings, "project_folder": design_dir}
    settings_path = f"{RUNS_DIR}/{run_name}/design_settings.json"
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    # Download the AlphaFold weights the first time (skipped once they are on the Volume).
    subprocess.run(["bindcraft", "fetch-weights"], check=True)
    weights_volume.commit()

    # Run the design campaign. We commit the Volume every few minutes so results
    # are kept even if the run is stopped or times out.
    proc = subprocess.Popen(["bindcraft", "design", settings_path])
    while True:
        try:
            proc.wait(timeout=COMMIT_EVERY_SECONDS)
            break
        except subprocess.TimeoutExpired:
            runs_volume.commit()
    runs_volume.commit()

    if proc.returncode != 0:
        raise RuntimeError(f"bindcraft exited with code {proc.returncode}")
    return design_dir


def build_bindcraft_settings(design_cfg):
    """Settings for BindCraft2 = the optional JSON file, then the `bindcraft:` section on top.

    Target structures are found by FILE NAME in inputs/targets/, so the paths written
    inside a JSON (for example from Colab) do not matter. project_folder is always set
    by run_design, whatever the JSON says.
    """
    settings = {}
    if "bindcraft_json" in design_cfg:
        with open(design_cfg["bindcraft_json"]) as f:
            settings = json.load(f)
    settings.update(design_cfg.get("bindcraft", {}))  # the run YAML wins over the JSON

    for target in settings.get("targets", []):
        if "target_path" not in target:
            continue
        file_name = os.path.basename(str(target["target_path"]).replace("\\", "/"))
        if not os.path.exists(os.path.join(LOCAL_TARGETS_DIR, file_name)):
            raise FileNotFoundError(f"Target structure '{file_name}' (target '{target.get('name')}') "
                                    f"is not in {LOCAL_TARGETS_DIR}/. Put the file there.")
        target["target_path"] = f"{TARGETS_DIR}/{file_name}"
        print(f"Target structure: {file_name} -> {target['target_path']}")
    settings.pop("project_folder", None)  # set automatically in the container
    return settings


# This runs on your own computer and launches the remote function.
@app.local_entrypoint()
def main(config: str, dry_run: bool = False, spawn: bool = False):
    cfg = load_config(config)
    require_keys(cfg, ["run_name", "design"], where=config)
    run_name, design_cfg = cfg["run_name"], cfg["design"]
    require_keys(design_cfg, ["gpu", "timeout_hours"], where="design section")
    if "bindcraft" not in design_cfg and "bindcraft_json" not in design_cfg:
        raise KeyError("design section needs `bindcraft_json:` (a BindCraft2 settings file) and/or `bindcraft:`")
    bindcraft_settings = build_bindcraft_settings(design_cfg)

    print(f"Run name : {run_name}")
    print(f"GPU      : {design_cfg['gpu']}   timeout: {design_cfg['timeout_hours']} h")

    # with_options sets compute from the config instead of the code. cpu and memory_gb are
    # optional; set them for multi-GPU runs (see inputs/configs_pipeline/il4_apo_run.yaml).
    options = {"gpu": design_cfg["gpu"], "timeout": int(design_cfg["timeout_hours"] * 3600)}
    if "cpu" in design_cfg:
        options["cpu"] = design_cfg["cpu"]
    if "memory_gb" in design_cfg:
        options["memory"] = int(design_cfg["memory_gb"] * 1024)  # Modal wants MiB
    print(f"Modal options: {options}")
    print(f"BindCraft2 settings:\n{json.dumps(bindcraft_settings, indent=2)}")
    if dry_run:
        print("Dry run, nothing launched.")
        return

    remote_design = design.with_options(**options)
    if spawn:
        # .spawn() starts the job and returns at once, so this terminal can be closed.
        # Launch with `modal run --detach` so Modal keeps the job running after we exit.
        call = remote_design.spawn(run_name, bindcraft_settings)
        print(f"Spawned design run '{run_name}' (function call {call.object_id}). It keeps running without this terminal.")
        print(f"Results will appear on Volume 'inceptive-runs' at {run_name}/design/")
        print(f"Check with: python -m modal volume ls inceptive-runs {run_name}/design")
        return
    out = remote_design.remote(run_name, bindcraft_settings)
    print(f"Done. Results on Volume 'inceptive-runs' at {out}")
    print(f"Download with: python -m modal volume get inceptive-runs {run_name} ./results")
