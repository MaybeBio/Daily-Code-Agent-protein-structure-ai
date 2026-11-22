# Train the CPI score models

For Kaggle T4 x2, use [the prepared notebook and upload instructions](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/README.md). It measures GPU runtime before full training and runs independent datasets on the two GPUs.

The training entrypoint is `scripts/train_cpi.py`. It uses the recovered original PerceiverCPI architecture, the prepared CSV splits and a fresh set of model weights. It trains **binding scores**, not protein shapes, docking poses or physical binding motion. PDBbind XYZ graphs are not inputs to this 2D model.

The existing supplied models already run the website. Retraining is optional. Original checkpoints are preserved; new runs are restricted to `training_runs/`.

## Start with a small check

From PowerShell:

```powershell
cd H:\gfihm
.\.venv\Scripts\python.exe scripts\train_cpi.py --dataset davis --smoke --device cpu
```

This uses 128 training, 32 validation and 32 test rows. A smoke test checks that the program works; its accuracy numbers are not a reliable scientific evaluation. Replace `davis` with `kiba` or `metz` for the other datasets. The three datasets keep their own label scales and models.

The environment is ready. On another installation, restore dependencies with:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-training.txt
```

A clean-machine installation has not been tested. Python 3.12 and the installed versions are recorded in the project reports. The missing training dependency, lifelines, was installed and tested here.

## Train on the full prepared splits

An epoch means one pass through the training examples. Start with a modest epoch count and judge validation results before deciding whether to run longer. A larger epoch count does not guarantee better accuracy.

```powershell
.\.venv\Scripts\python.exe scripts\train_cpi.py --dataset davis --epochs 30 --device cpu
.\.venv\Scripts\python.exe scripts\train_cpi.py --dataset kiba --epochs 30 --device cpu
.\.venv\Scripts\python.exe scripts\train_cpi.py --dataset metz --epochs 30 --device cpu
```

Run these sequentially. They use all rows in the corresponding prepared train/validation/test files, batch size 16, two CPU threads, one model, one split and the original 500-token sequence limit. The supplied historical run used 150 epochs and batch size 50. The new prepared splits and seed are different, so these commands are **not a reproduction of that experiment**.

| Dataset | Training pairs | Validation pairs | Test pairs |
|---|---:|---:|---:|
| Davis | 20,071 | 2,553 | 2,602 |
| KIBA | 93,688 | 11,758 | 11,923 |
| Metz | 28,223 | 3,487 | 3,549 |

Exact pairs do not cross these splits. Proteins and compounds may recur individually; similar sequences and chemical scaffolds were not clustered. These splits measure pair prediction, not strict unseen-target or unseen-compound performance. Scores have not been combined across datasets. Confirm Davis/Metz units before scientific interpretation.

## Resume after stopping

The last completed epoch is saved automatically. An unfinished epoch is repeated. To continue Davis up to a total of 150 epochs:

```powershell
.\.venv\Scripts\python.exe scripts\train_cpi.py --dataset davis --epochs 150 --device cpu --resume
```

Keep the same dataset, input files, batch size and output folder. The manifest rejects an accidental mismatch. To begin an independent experiment, choose a new output folder inside `training_runs/`, for example `--output training_runs/davis_experiment_2`. `--resume` must refer to that same folder on subsequent calls. Do not use smoke-test weights as a completed full-data model.

## How long will it take on this computer?

The machine has an RTX 3050 A Laptop GPU with 4 GB VRAM, but the installed Torch build is **CPU-only**. All timings below therefore describe CPU training with two threads and batch size 16.

Actual checks completed two small training epochs per dataset, including a Davis interrupted-run/resume check. Each small check included checkpoint writing and test evaluation; new checkpoints were also tested with the live inference code.

| Dataset | Estimated full epoch | Estimated 30 epochs | Estimated 150 epochs |
|---|---:|---:|---:|
| Davis | 8 minutes | 4 hours | 20 hours |
| KIBA | 54 minutes | 27 hours | 135 hours (5.6 days) |
| Metz | 19 minutes | 10 hours | 49 hours (2 days) |

These are **rough extrapolations from small measured batches, not full-run measurements**. Allow roughly half to twice these times. Larger molecules, graph caching, background work, sustained laptop temperature and checkpoint writes can change runtime. First-time data preparation and final testing add time. GPU runtime is unmeasured; these numbers must not be presented as GPU estimates.

Change batch size or hardware only in a new experiment and benchmark again. `--device cuda` deliberately reports a clear error with the current CPU-only installation. A separately installed, verified CUDA environment is needed before GPU timing can be measured.

Measurement evidence: `reports/training_benchmark.json` and `training_runs/<dataset>_smoke_check/timings.jsonl`. Repeated full smoke checks should use new output folders or explicitly resume; the program protects existing runs.

## Outputs and use in the website

For the default Davis run:

- `training_runs/davis/fold_0/model_0/model.pt`: checkpoint selected by validation MSE.
- `training_runs/davis/fold_0/model_0/resume.pt`: optimizer, RNG and last-epoch state for continuing training.
- `training_runs/davis/fold_0/test_scores.json` and `test_preds.csv`: final held-out evaluation and predictions.
- `training_runs/davis/run_manifest.json`: data fingerprints and run settings.
- `training_runs/davis/timings.jsonl` and `training_report.json`: measured runtime.

After training and evaluating all three default dataset runs, stop the currently running server and start it with the new model root:

```powershell
$env:CPI_MODEL_ROOT = 'H:\gfihm\training_runs'
.\.venv\Scripts\python.exe scripts\cpi_app.py
```

The root must contain `davis`, `kiba` and `metz` subfolders with their respective `fold_0/model_0/model.pt` files. If one is missing, that dataset's score reports the missing model; structure viewing still works. The app does not silently mix trained and supplied models. Custom experiment folders must be arranged under a separate model root with this same dataset layout.

To use the supplied models again, stop the server and run:

```powershell
Remove-Item Env:CPI_MODEL_ROOT -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe scripts\cpi_app.py
```

Checkpoint hashes separate score caches, and changed checkpoint bytes trigger a fresh model load. Original historical-comparison results are not attached to models selected from the new model root.

## Your new-input 3D error

Your saved query used a 62-residue protein sequence. No exact contacting chain/domain match was found after checking the protein-only index covering all 17,479 eligible structures. The site now returns a clear **unsupported structure** message instead of a generic failure.

Training the score model will not supply those missing coordinates. To show a supported 3D pose for that exact input, a matching receptor structure and justified pocket, or a separately configured and tested complex-prediction system, are still needed. The viewer can display all 19,035 processed PDBbind complexes independently, but it will not label an unrelated one as your query's result.
