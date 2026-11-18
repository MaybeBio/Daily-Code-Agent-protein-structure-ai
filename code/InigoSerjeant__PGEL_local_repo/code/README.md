# PGEL: Protein Generation with Embedding Learning

[![arxiv](https://img.shields.io/badge/arxiv-2510.18790-b31b1b.svg)](https://arxiv.org/abs/2510.18790) ![Maturity level-0](https://img.shields.io/badge/Maturity%20Level-ML--0-red)

> A general framework for embedding-based control of frozen protein diffusion models, introduced here through motif diversification.

<p align="center">
  <img src="https://github.com/InigoSerjeant/PGEL_local_repo/raw/HEAD/img_pgel/pgel_examples.png" alt="Overview of PGEL learning and generation" width="920"/>
</p>

## Overview

PGEL (**P**rotein **G**eneration with **E**mbedding **L**earning) is a general framework for embedding-based control of protein diffusion models. The central idea is to learn high-dimensional embeddings that capture the sequence and structural features of a target region, such as a functional motif, directly in the internal conditioning space of a frozen protein denoiser.

This repository implements PGEL in RFdiffusion's representation space, however, the method is not specific to RFdiffusion. The framework is applicable to other protein diffusion models with accessible internal conditioning representations, allowing them to leverage the representational capacity of pre-trained diffusion models without expensive retraining or fine-tuning.

We also formalize *motif diversification* as a design task: given a protein structure with a functional motif embedded in a larger scaffold, generate alternative motif conformations and poses while keeping the rest of the protein approximately fixed in real space. This provides a controlled route to local functional exploration under a fixed global structural context.

PGEL shifts the control mechanism from coordinate-space perturbation to embedding-space perturbation. Instead of changing backbone coordinates alone, PGEL learns a motif-specific representation and uses that representation as the control variable during generation. Diversity is further induced by masking embeddings, which relaxes evolutionary and structural constraints while preserving the learned motif signal.

## Requirements and Setup

The supplied [`environment.yml`](https://github.com/InigoSerjeant/PGEL_local_repo/blob/HEAD/environment.yml) is the tested, pinned environment for **Linux x86_64 with an NVIDIA GPU and a driver compatible with CUDA 12.4**. These instructions assume an Ubuntu/Debian server, a working internet connection, and permission to install packages for your user. The NVIDIA driver must be installed and configured by the server administrator; Conda installs user-space CUDA libraries, not the kernel driver.

### 1. Install system tools

Open a terminal on the server. Install the tools needed to download Miniforge, clone the repository, and fetch model weights:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git wget bzip2
```

On a different Linux distribution, use its package manager to install the equivalent tools. If you do not have `sudo`, ask the server administrator to install them.

Check that the server exposes the NVIDIA GPU and driver:

```bash
nvidia-smi
```

If this command is missing or reports no driver/device, contact the administrator before proceeding with GPU inference.

### 2. Install Miniforge (Conda)

The following installs Miniforge for the current user without requiring an existing Conda installation:

```bash
curl -L -o "$HOME/Miniforge3.sh" \
  https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash "$HOME/Miniforge3.sh" -b -p "$HOME/miniforge3"
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash
```

Reload your Bash configuration so `conda` is available in future terminals:

```bash
source "$HOME/.bashrc"
conda --version
```

These installer commands target Linux x86_64. For Linux ARM64, download the corresponding `Miniforge3-Linux-aarch64.sh` installer; the supplied PGEL environment is only tested on x86_64.

### 3. Clone PGEL and create its environment

```bash
git clone https://github.com/InigoSerjeant/PGEL_local_repo.git
cd PGEL_local_repo
conda env create --file environment.yml
conda activate PGEL
```

### 4. Install the Python packages

Install the bundled SE(3)-Transformer and this checkout in editable mode:

```bash
python -m pip install --no-cache-dir -r env/SE3Transformer/requirements.txt
python -m pip install -e ./env/SE3Transformer
python -m pip install -e .
```

Editable installation is important: it makes Python use this checkout's RFdiffusion code, which resolves model weights from this checkout's `models/` directory.

### 5. Download model weights

The script downloads all supported checkpoints and requires `wget`:

```bash
bash scripts/download_models.sh models
```

The checkpoints require about 3.4 GB of disk space. Verify the Python dependencies and that the editable install points into the clone:

```bash
python -m pip check
python -c "import rfdiffusion; print(rfdiffusion.__file__)"
```

The printed `rfdiffusion` path should be inside the cloned repository. In a new terminal, run `source "$HOME/miniforge3/etc/profile.d/conda.sh"` if Conda is not initialized there, then activate the environment with `conda activate PGEL` before running scripts.

If Python reports `No module named 'hydra'`, confirm that `PGEL` is active and that `python -m pip show hydra-core` finds the package. The project needs **`hydra-core`**; do not install the unrelated package named `hydra`. If the RFdiffusion import points into `site-packages` instead of the clone, rerun `python -m pip install -e .` from the repository root.

> **Note:** `environment.yml` is a Linux/NVIDIA environment specification, not a platform-independent requirements file. For a different operating system or CUDA setup, the PyTorch, DGL, and CUDA package versions need to be adapted together.

## Quick Start

The main PGEL script for motif diversification is `scripts/run_new_inversion.py`. It implements a two-stage workflow:

1. Embedding learning with `inference.inversion_train=True`, which optimizes the motif embedding while keeping the denoiser frozen.
2. Diversification sampling with `inference.inversion_train=False`, which reloads the learned embedding and generates diversified structures by perturbing scaffold conditioning during reverse diffusion.

For a first run using the included 5UDC example and its precomputed embeddings, run from the `examples` directory:

```bash
cd examples
mkdir -p learnt_embeddings outputs
python ../scripts/run_new_inversion.py --config-name 5UDC_H_only
```

Hydra's option is `--config-name` (not `--config`). To learn an embedding for a different input, run the training stage from `examples`:

```bash
python ../scripts/run_new_inversion.py \
  inference.input_pdb=input_pdbs/1bcf_chainA.pdb \
  inference.output_prefix=outputs/pgel_train \
  'contigmap.contigs=[17-17/A18-25/21-21/A47-54/37-37/A92-99/23-23/A123-130/28-28]' \
  inference.num_designs=1 \
  inference.inversion_train=True
```

Then generate diversified motifs from the learned embedding, using the same input and contig:

```bash
python ../scripts/run_new_inversion.py \
  inference.input_pdb=input_pdbs/1bcf_chainA.pdb \
  'contigmap.contigs=[17-17/A18-25/21-21/A47-54/37-37/A92-99/23-23/A123-130/28-28]' \
  inference.output_prefix=outputs/pgel_sample \
  inference.num_designs=1 \
  inference.inversion_train=False
```

# Method Summary

<p align="center">
  <img src="https://github.com/InigoSerjeant/PGEL_local_repo/raw/HEAD/img_pgel/fig1_overview.jpg" alt="PGEL evaluation pipeline" width="920"/>
</p>

PGEL has two stages:

1. *Embedding learning*. A target structure is partitioned into a motif and scaffold. The RFdiffusion denoiser remains frozen while a motif embedding is optimized to reconstruct the target motif.
2. *Generation under masked scaffold conditioning*. The learned motif embedding is injected into RFdiffusion representation tracks, and scaffold MSA conditioning is perturbed by random masking during reverse diffusion to promote structurally compatible motif variation.

Only the motif embedding is trained, and model parameters are unchanged.

## Applications

### Motif diversification

This work formally introduces *motif diversification* as a protein design task: starting from an experimentally characterized structure, generate alternative conformations and poses of a functional motif while maintaining the surrounding scaffold. The task is defined at the  level, with downstream sequence design and structure prediction used to assess whether diversified backbones remain realizable.

PGEL is evaluated on 10 systems spanning monomers, binders, antibody-antigen complexes, heme-binding sites, and an enzyme. Across these benchmarks, PGEL improves designability substantially in most cases and yields substantially greater structural diversity than RFdiffusion's partial diffusion.

## Evaluation

PGEL is evaluated for motif diversification rather than unconditional generation. Generated backbones are filtered for:

- designability, using motif pLDDT, scaffold RMSD, and motif RMSD criteria
- diversity, using clustering over pairwise motif TM-scores
- self-consistency, using ProteinMPNN inverse folding followed by AlphaFold3 refolding

This evaluation emphasizes structurally distinct motifs that remain designable and recoverable after sequence design.

## Results

Across 10 benchmark systems, PGEL improves designability in most cases and yields more diverse self-consistent solutions than RFdiffusion partial diffusion.

| PDB | Partial diffusion designability | PGEL designability | Partial diffusion diversity | PGEL diversity |
|---|---:|---:|---:|---:|
| 1BCF | 983 | 1000 | 0 | 1 |
| 1PRW | 411 | 1000 | 0 | 2 |
| 1YCR | 252 | 802 | 1 | 6 |
| 3IXT | 393 | 502 | 1 | 3 |
| 5IUS | 434 | 711 | 0 | 2 |
| 6E6R | 523 | 523 | 0 | 13 |
| 6EXZ | 983 | 887 | 1 | 5 |
| 6HAM | 798 | 823 | 8 | 15 |
| 7MRX | 331 | 990 | 6 | 10 |
| 7OW1 | 948 | 950 | 2 | 4 |

Here, *designability* counts backbones passing motif/scaffold RMSD and pLDDT thresholds, and *diversity* counts self-consistent TM-score clusters.

##  Repository Structure 

Our code is built around the [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) ([BSD License](https://github.com/RosettaCommons/RFdiffusion/blob/main/LICENSE)) codebase. The source code files we have modified or adapted are enumerated below:

```
./rfdiffusion/inference/model_runners.py
./rfdiffusion/inference/utils.py
./rfdiffusion/diffusion.py
./rfdiffusion/Embeddings.py
./rfdiffusion/kinematics.py
./rfdiffusion/RoseTTAFoldModel.py
./rfdiffusion/util.py
./scripts/run_inference_with_masking.py
```

## Citation

If you use PGEL or build on this repository in academic work, please cite our arXiv paper:

Kevin Michalewicz, Chen Jin, Philip Alexander Teare, Tom Diethe, Mauricio Barahona, Barbara Bravi, and Asher Mullokandov. "Protein generation with embedding learning for motif diversification." arXiv:2510.18790, 2025. https://arxiv.org/abs/2510.18790

```bibtex
@article{michalewicz2025pgel,
  title={Protein generation with embedding learning for motif diversification},
  author={Michalewicz, Kevin and Jin, Chen and Teare, Philip Alexander and Diethe, Tom and Barahona, Mauricio and Bravi, Barbara and Mullokandov, Asher},
  journal={arXiv preprint arXiv:2510.18790},
  year={2025},
  doi={10.48550/arXiv.2510.18790},
  url={https://arxiv.org/abs/2510.18790}
}
```