"""Re-score finished validation results: recompute the structure columns from the saved predictions.

Usage:
    python -m modal run rescore_validation.py --config inputs/configs_pipeline/ifng_heterodimer_no_cold_run.yaml
    python -m modal run rescore_validation.py --config inputs/configs_pipeline/ifng_heterodimer_no_cold_run.yaml --dry-run

Use it after validation has finished when the structure checks change (for example, you add
selection.identical_segments, or Optimus gains a new column). It does NOT run any prediction: it reads the
predicted structures already on the Volume, so it costs a few CPU minutes and no GPU.

What it recomputes (with the current Optimus in optimus/): the RMSD columns (rmsd_fold, rmsd_pose_target_*,
rmsd_assignment), binder_plddt70_fraction, the interface-consistency columns, and the per-design summary.
Everything else (ipTM, ipSAE, pLDDT, contact check) is copied from the original results.

The originals are never overwritten. New files go next to them on the Volume and into results/ on your computer:
    validation_results_rescored.csv, validation_summary_rescored.csv, designs_rescored.csv
"""
import os

from config_loader import (load_config, local_results_dir, require_keys,
                           selection_settings, validation_volume_dir)
from modal_app import OPTIMUS_RUNS_DIR, RUNS_VOLUME_NAME, app, bridge_image, runs_volume

# Columns this step recomputes; they are dropped from the old results first.
RECOMPUTED = ("binder_plddt70_fraction", "chain_assignment",
              "paratope_recall", "paratope_jaccard", "epitope_recall", "epitope_jaccard")


# Runs remotely on a CPU. The Volume is mounted where Optimus saw it, so the structure paths stored in the
# results (/outputs/...) work as they are.
@app.function(image=bridge_image, volumes={OPTIMUS_RUNS_DIR: runs_volume}, cpu=4, memory=8192, timeout=3600)
def rescore(run_name: str, validate_dir: str, binder_chain: str, identical_segments: dict) -> dict:
    import io

    import pandas as pd

    import validation_core as vc
    from design_table import build_design_table

    runs_volume.reload()
    folder = f"{OPTIMUS_RUNS_DIR}/{validate_dir}"
    # keep_default_na=False keeps empty cells as "" (Optimus's own code expects text there, not NaN)
    tall = pd.read_csv(f"{folder}/validation_results.csv", keep_default_na=False)

    designs = build_design_table(run_name, None, binder_chain, identical_segments,
                                 read_mount=OPTIMUS_RUNS_DIR, ref_mount=OPTIMUS_RUNS_DIR)
    designs = designs[designs["design_name"].isin(tall["design_name"])]
    designs = vc.load_designs(designs)          # the same checks Optimus runs on its input
    missing = set(tall["design_name"]) - set(designs["design_name"])
    if missing:
        raise ValueError(f"{len(missing)} validated designs are not in the run's ranked table, e.g. {sorted(missing)[:3]}")

    old = [c for c in tall.columns if c.startswith("rmsd_") or c in RECOMPUTED]
    tall = tall.drop(columns=old)
    tall = vc.add_binder_plddt70_fraction(vc.add_structure_rmsd(tall, designs))
    tall = vc.add_interface_consistency(tall, designs)
    if "rmsd_fold" not in tall or tall["rmsd_fold"].isna().all():
        raise RuntimeError("no RMSD could be computed for any job; see the warnings above")
    summary = vc.summarize(tall, designs)

    texts = {"validation_results_rescored.csv": tall, "validation_summary_rescored.csv": summary,
             "designs_rescored.csv": designs}
    out = {}
    for name, frame in texts.items():
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        out[name] = buffer.getvalue()
        with open(f"{folder}/{name}", "w", newline="") as f:
            f.write(out[name])
    runs_volume.commit()
    print(f"Re-scored {len(tall)} jobs of {tall['design_name'].nunique()} designs; RMSD missing for {int(tall['rmsd_fold'].isna().sum())}.")
    return out


# Runs on your own computer.
@app.local_entrypoint()
def main(config: str, dry_run: bool = False):
    cfg = load_config(config)
    require_keys(cfg, ["run_name", "selection", "validate"], where=config)
    run_name = cfg["run_name"]
    _, binder_chain, identical_segments = selection_settings(cfg, where=config)
    validate_dir = validation_volume_dir(cfg)

    print(f"Run name   : {run_name}")
    print(f"Results    : {validate_dir}/validation_results.csv on Volume '{RUNS_VOLUME_NAME}'")
    print(f"Identical target segments: {identical_segments or 'none (set selection.identical_segments to use)'}")
    if dry_run:
        print("Dry run, nothing launched.")
        return

    files = rescore.remote(run_name, validate_dir, binder_chain, identical_segments)
    results_dir = local_results_dir(cfg)
    os.makedirs(results_dir, exist_ok=True)
    for name, text in files.items():
        with open(os.path.join(results_dir, name), "w", newline="") as f:
            f.write(text)
    print(f"Saved {', '.join(files)} to {results_dir} (and next to the originals on the Volume).")
