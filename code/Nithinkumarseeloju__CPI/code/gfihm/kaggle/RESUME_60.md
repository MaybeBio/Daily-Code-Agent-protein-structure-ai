# Safe continuation to 60 total epochs

Import [CPI_T4x2_resume_60.ipynb](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/CPI_T4x2_resume_60.ipynb) into Kaggle. This separate notebook continues all three score models; it does not change the existing notebook or original weights.

## Inputs and running

1. Attach `cpi_kaggle.zip` from this project and the downloaded `cpi_training_checkpoints.zip` as private Kaggle datasets. These are TWO inputs containing THREE affinity datasets (Davis, KIBA, Metz). No PDBbind structures are needed for this score-model continuation.
2. Select GPU T4 x2 and enable Internet. Run all cells in order. The notebook accepts ZIPs or Kaggle-extracted folders.
3. Defaults: total target 60, batch size 16, all three datasets. This adds 30 epochs to the supplied 30-epoch checkpoints. To continue only Davis, select `('davis',)` in the first cell.
4. Download `cpi_training_checkpoints_baseline.zip`, `cpi_training_checkpoints_resume_60.zip`, `cpi_validation_comparison.json/csv` and `cpi_validation_curves.png`. Preserve the original input checkpoint ZIP separately.

If several candidate archives are attached, set TRAINING_PACKAGE and RESTORE_ZIP to their exact `/kaggle/input/...` paths. A separate `/kaggle/working/cpi_resume60` folder protects existing experiments. Setup reuses it on rerun rather than restoring old files over new progress.

For local checks, see [RESUME_60_CHECKS.md](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/RESUME_60_CHECKS.md) and [the baseline validation plot](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/validation_before_resume.png).

## Verified original results

| Dataset | Completed epochs | Best validation MSE | Best epoch |
|---|---:|---:|---:|
| Davis | 30 | 0.3290978256 | 30 |
| KIBA | 30 | 0.2696711634 | 28 |
| Metz | 30 | 0.4586010292 | 25 |

Lower MSE means a smaller average squared prediction error on validation examples. These are not accuracy percentages. Davis has the clearest recent improvement; a few non-improving KIBA/Metz epochs do not prove that they cannot improve later. Best validation weights are retained even when later epochs worsen. This does not guarantee better results on unseen data.

The last ten saved training/validation epochs suggest about **3.5 hours plus overhead** for all three to reach 60 using the same two-GPU schedule. This is an estimate from the previous run, not a completion guarantee. The notebook recomputes remaining time from restored logs. Hardware, dependencies and session conditions can change it.

## Learning-rate and validation qualifications

The supplied trainer never calls scheduler.step(); its saved optimizer learning rates remain approximately 0.0001. Continuation preserves the original optimizer/scheduler/random/sampler states. It does not silently replace this with a fresh 60-epoch schedule. A scheduler correction or new learning rate belongs in a separately measured experiment.

The trainer evaluates test metrics at the end of a training stage. Do not use those metrics to select epochs. Notebook plots and comparisons use validation only. Consider 150 total epochs only after reviewing validation at 60; this notebook does not implement automatic early stopping or promise improved accuracy.

## Checkpoints and interruptions, in simple terms

- `model.pt`: the best model so far, chosen using validation.
- `resume.pt`: the latest completed epoch plus what training needs to continue.
- A safe resume file is written after every completed epoch. An incomplete epoch must run again.
- Recovery ZIPs are written before training, every ten minutes, and after normal completion/interruption. They are replaced atomically. ZIP best-model weights are reconstructed from the matching saved resume state.
- A forced shutdown can prevent the final ZIP. Download/preserve outputs before ending a session; do not assume Kaggle always keeps temporary working files. An existing ZIP can lag behind the latest epoch.
- In a new session attach the latest recovery ZIP with the original data, set RESTORE_ZIP if needed, and run all cells. Finished datasets are skipped. Original validation baseline metadata travels with the recovery ZIP.
- Intermediate reports/test predictions may describe an earlier stage; read their `epochs_requested` value. Snapshot metadata and resume.pt give current completed epochs.

## Clear error explanations

| Message | Meaning and action |
|---|---|
| Enable GPU / Select GPU T4 x2 | The notebook has no suitable pair of GPUs. Change Kaggle accelerator settings. |
| Multiple ZIPs / attach input | The notebook cannot choose the right file. Set its exact path in the first cell. |
| Missing checkpoint | A required saved-training file is absent. Upload the complete checkpoint archive. |
| Data/settings differ | These weights belong to different data or settings. Use the same original splits and batch size 16. |
| Invalid numbers or architecture | The checkpoint has broken numbers or incompatible weights. Restore a known good complete checkpoint. |
| Dependency check failed | A required software package cannot load. Read the printed package error before spending GPU time. |
| Training failed | The error includes the end of that dataset's log. The notebook attempts a recovery ZIP; fix that error and resume. |
| Existing recovery ZIP contains newer progress | Restore that newer ZIP, or choose a different output folder. Newer saved training will not be overwritten. |
| Recovery ZIP failed | Keep/download the training_runs folder and existing ZIP. Check output disk space. The original training error is preserved. |

Only load your own trusted checkpoint archives. The model and training code have local checks, but a new full Kaggle T4 run has not been performed here.

## Separate 3D issue

More affinity-score training does not create protein coordinates. Existing ESMFold logs include both a model-download timeout and a separate inference IndexError. Those need a separate structure-prediction investigation; this notebook does not fix or retrain ESMFold.

## Known original model limitation

The original model averages padded neighbor slots, so batch composition can slightly change a score. A verified Davis example changed from 5.933935642 to 5.936890125 when companion molecules changed padding. The site already uses deterministic single-pair inference. Keep the same training batch size and validation settings for continuation; changing aggregation requires a separate retraining and validation experiment.
