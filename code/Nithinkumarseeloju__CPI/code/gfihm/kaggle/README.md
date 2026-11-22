# Run CPI score training on Kaggle T4 x2

1. Create a **private Kaggle Dataset** and upload `cpi_kaggle.zip` from this folder. The ZIP contains training code and the nine prepared CSV split files; it does not contain the virtual environment, old checkpoints or PDBbind structures.
2. Create a Kaggle notebook and import `CPI_T4x2.ipynb` using its notebook import/upload option.
3. Attach the dataset from step 1 through **Add Input**. Select **GPU T4 x2** under notebook Settings > Accelerator and enable Internet for dependency installation.
4. Full training is enabled by default (`RUN_FULL_TRAINING=True`, `TARGET_EPOCHS=30`). Run all cells in order. The notebook copies inputs into `/kaggle/working/cpi_project`, verifies both CUDA GPUs, installs dependencies and measures two full-data epochs for each dataset.
5. Read the printed estimates for 30 and 150 epochs. These use the epoch times actually measured on your Kaggle GPUs. Review the session time/quota shown by Kaggle.
6. The full-training cell automatically continues to 30 total epochs per dataset, including the first two. To choose another total, change `TARGET_EPOCHS` in the first code cell before running. The full-training cell no longer resets the configuration.
7. Download `/kaggle/working/cpi_training_checkpoints.zip` from notebook outputs, along with the environment, time estimate and logs under `/kaggle/working/cpi_project/`. Preserve outputs before ending the session.

The first run may take time to install packages, parse data and warm up CUDA. A two-epoch calibration checkpoint is not a fully trained model. The supplied models remain untouched on your Windows computer.

For the saved 30-epoch checkpoint archive, use [`CPI_T4x2_Davis60_Resume.ipynb`](https://github.com/Nithinkumarseeloju/CPI/blob/HEAD/gfihm/kaggle/CPI_T4x2_Davis60_Resume.ipynb) to extend Davis to 60 total epochs while leaving KIBA and Metz at 30. It verifies the archive, data hashes and batch size, keeps the original ZIP as input, and writes a separate continuation archive. The continuation is a validation-driven experiment, not a guarantee of improved test performance.

## How both GPUs are used

- GPU 0 trains KIBA.
- GPU 1 trains Davis, then Metz.

Each process uses one GPU via `CUDA_VISIBLE_DEVICES`. The current architecture is not configured for distributed training of one model across both GPUs. This schedule trains independent models in parallel; it does not combine GPU memory or guarantee a twofold speedup for any dataset.

## Training time

No T4 benchmark has been run from the local environment. The old CPU estimates and historical L4 logs do not establish the time on Kaggle T4 x2. The notebook calculates it from two full-data epochs per dataset:

`hours = seconds per epoch × epochs / 3600`

Illustrative examples for **one dataset**, not claims about this model's actual T4 speed:

| Measured epoch time | 30 epochs | 150 epochs |
|---|---:|---:|
| 1 minute | 0.5 hours | 2.5 hours |
| 3 minutes | 1.5 hours | 7.5 hours |
| 5 minutes | 2.5 hours | 12.5 hours |

With the two-GPU schedule, remaining wall time is approximately the larger of `KIBA remaining time` and `Davis remaining time + Metz remaining time`, plus overhead. The notebook prints that number. Session interruptions, graph preprocessing, evaluation, checkpoint saving and CPU sharing can change it.

## Continue in a new Kaggle session

Upload the saved `cpi_training_checkpoints.zip` as another private dataset and attach it. Set `RESTORE_ZIP` in the first code cell to the exact uploaded ZIP path under `/kaggle/input/`. Keep the same original data, batch size and run settings. Restore only when the working training folder is empty. Then run the setup/calibration cells and continue the full-training cell. Preserve `resume.pt`, `model.pt` and `run_manifest.json` together.

The notebook keeps Kaggle's GPU PyTorch. Do not install the Windows `model_source/requirements-gpu.txt` or the locally pinned `requirements-training.txt` there. GPU dependency compatibility still needs the notebook's real Kaggle checks; packaging validation on Windows does not prove a successful T4 run.

These commands train the **2D score model**. They do not generate the missing protein coordinates for a new sequence or train physical ligand motion.

Official setup references: [NVIDIA Kaggle setup](https://docs.nvidia.com/datascience/deployment/26.10/platforms/kaggle/index.html), [Kaggle notebooks](https://www.kaggle.com/docs/notebooks), [Kaggle GPU usage](https://www.kaggle.com/docs/efficient-gpu-usage).
