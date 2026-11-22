# PhaseFlow: A Unified Multi-Modal Generative Model for Phase-Separating Proteins

<div align="center">
  <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/PhaseFlow.png" alt="PhaseFlow" width="900">
</div>

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Models](https://img.shields.io/badge/Models-Hugging%20Face-blue)
![Datasets](https://img.shields.io/badge/Datasets-Hugging%20Face-blue)
![Online Demo](https://img.shields.io/badge/Online%20Demo-phaseflow.bio-7C3AED)
![License](https://img.shields.io/badge/License-Apache--2.0-blue)

</div>

<div align="center"><i>A unified multi-modal generative model that connects amino-acid sequences, phase diagrams, residue context, structure-derived features, protein graphs, LLPS propensity, DPR localization, and mutation-effect scoring.</i></div>

<br>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Get%20Started-Quick%20Start-0A66C2?style=for-the-badge" alt="Get Started: Quick Start"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/Install-PhaseFlow-16A5A8?style=for-the-badge" alt="Install PhaseFlow"></a>
  <a href="http://phaseflow.bio/"><img src="https://img.shields.io/badge/Try%20Online-PhaseFlow-7C3AED?style=for-the-badge" alt="Try PhaseFlow online"></a>
</p>

<br>

## Model Overview

PhaseFlow is organized around one modeling goal: learn how sequence-level,
phase-diagram, and protein-context signals map into phase-separation behavior,
then use those learned mappings for prediction, localization, and design.

| Signal family | Role in PhaseFlow |
| --- | --- |
| Peptide sequence tokens | Sequence-to-phase prediction and phase-conditioned sequence generation |
| 4x4 PSSI phase diagrams | Compact representation of phase-separation score landscapes |
| Flow Matching and causal language modeling | Fast phase-diagram regression and target-conditioned peptide design |
| Protein residue context | Protein-level LLPS prediction and residue-level DPR scanning |
| ESM2, physicochemical, disorder, structure, graph, and local-context features | Multi-modal protein representations for protein tasks |
| Ordered bridge tokens | Transfer short-peptide sequence-phase knowledge into protein modeling |

## Application

<p align="center">
  <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/application.svg" alt="PhaseFlow application overview" width="980">
</p>

PhaseFlow supports a connected set of phase-separation applications: designing
peptide sequences from target phase diagrams, predicting phase diagrams from
candidate sequences, scanning proteins for LLPS-driving regions,
and estimating mutation effects on phase-separation behavior. These workflows
share the same sequence-phase modeling foundation while exposing outputs that
map naturally to peptide design, protein annotation, and mutagenesis analysis.

## Unified Model Architecture

### Short-Peptide Sequence-Phase Generator

<p align="center">
  <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/architecture-peptide-complete.svg" alt="Short-peptide PhaseFlow architecture" width="900">
</p>

The short-peptide module is the bidirectional sequence-phase model. For
sequence-to-phase prediction, peptide tokens and phase-grid tokens pass through
shared Transformer blocks and a Flow Matching velocity head to predict a 4x4
PSSI diagram. For phase-to-sequence design, the same architecture conditions on
the target phase diagram and uses causal language modeling to generate peptide
sequences.

### Protein LLPS And DPR Model

<p align="center">
  <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/architecture.svg" alt="Protein PhaseFlow architecture" width="960">
</p>

The protein module handles protein-scale context separately from the
short-peptide task. It combines residue-level ESM2, physicochemical, disorder,
structure-derived, graph, and local-context features, then bridges peptide
sequence-phase knowledge through ordered bridge tokens and residue-query
cross-attention. The outputs are protein-level LLPS probability and DPR scanner
profiles that are post-processed into droplet-promoting region calls.

<br>

## Why Use PhaseFlow?

You should consider PhaseFlow when your phase-separation workflow needs:

<table>
  <tr>
    <td align="center">🧬</td>
    <td><b>Unified multi-modal generative model</b></td>
    <td>Brings sequence, phase-diagram, residue-context, structure-derived, graph, LLPS, DPR, and mutation-effect signals into one PhaseFlow workflow.</td>
  </tr>
  <tr>
    <td align="center">🧪</td>
    <td><b>Multi-scale LLPS modeling</b></td>
    <td>Covers short-peptide phase diagrams, protein LLPS, DPR localization, and mutation-effect scoring.</td>
  </tr>
  <tr>
    <td align="center">🔁</td>
    <td><b>Bidirectional peptide model</b></td>
    <td>Learns mappings between amino-acid sequences and 4x4 phase-separation score index (PSSI) diagrams.</td>
  </tr>
  <tr>
    <td align="center">⚡</td>
    <td><b>Flow Matching for phase diagrams</b></td>
    <td>Supports faster phase-conditioned peptide design loops than diffusion-style sampling.</td>
  </tr>
  <tr>
    <td align="center">🔎</td>
    <td><b>Protein LLPS and DPR scanning</b></td>
    <td>Predicts protein-level LLPS propensity and localizes droplet-promoting regions from residue context.</td>
  </tr>
  <tr>
    <td align="center">🌉</td>
    <td><b>Staged transfer bridge</b></td>
    <td>Transfers short-peptide sequence-phase knowledge to proteins through 32 ordered bridge tokens.</td>
  </tr>
  <tr>
    <td align="center">🧫</td>
    <td><b>Mutation-effect scoring</b></td>
    <td>Amino-acid perturbations can be scored for predicted shifts in phase-separation behavior.</td>
  </tr>
  <tr>
    <td align="center">🧠</td>
    <td><b>Rich protein features</b></td>
    <td>Combines ESM2, physicochemical, disorder, Protenix-derived, graph, and residue-context signals.</td>
  </tr>
  <tr>
    <td align="center">📦</td>
    <td><b>Artifact-ready layout</b></td>
    <td>Code, configs, docs, figures, local datasets, and local model downloads are separated so GitHub stays lightweight while Hugging Face artifacts can be added cleanly.</td>
  </tr>
</table>

<br>

## Key Results

The values below are summarized from the tracked configs, audit reports, and
figure artifacts in this repository. They are included to make the README
useful as a project entry point; detailed provenance remains in
`configs/protein/` and `docs/protein/`.

| Task | Evaluation setting | PhaseFlow result |
| --- | --- | --- |
| Protein LLPS | PPMC full panel | AUPRC 0.752, AUROC 0.874 |
| Protein LLPS | threshold 0.5 | MCC 0.549, F1 0.676 |
| Peptide phase prediction | complete held-out peptide diagrams | Spearman 0.4168, Pearson 0.4219, MSE 0.5652 |
| Flow Matching vs DDPM | matched peptide phase-grid comparison | mean Spearman 0.559 vs 0.277; MSE 0.570 vs 1.315 |
| DPR localization | PhasePro, p257 readout | residue AUPRC 0.712, top-5 enrichment 1.813 |
| DPR region calling | IoU 0.25 region matching | recall 0.580, precision 0.638, segment F1 0.608 |
| Mutation effects | TDP-43 point-mutation panels | strongest average ranking/classification metrics among compared methods in the included benchmark summary |

<br>

## Key Modules

| Module | Path | Description |
| --- | --- | --- |
| Peptide core package | `phaseflow/` | Tokenizer, peptide Transformer, Flow Matching/DDPM model, utilities |
| Protein package | `phaseflow/protein/` | Protein model structure, data contracts, reusable feature/structure functions, objectives, metrics, and post-processing |
| Peptide configs | `configs/peptide/` | Lightweight peptide training defaults |
| Protein configs | `configs/protein/` | LLPS and DPR training configurations |
| Peptide scripts | `scripts/peptide/` | Training, inference, resume, and experiment launchers |
| Protein scripts | `scripts/protein/` | Reproduction workflows for data construction, training, evaluation, release validation, and benchmark utilities |
| Examples | `examples/` | Small peptide demo inputs and phase-to-sequence example |
| Tests | `tests/` | Peptide smoke tests and focused protein tests |
| Figures | `figures/` | Curated README and paper-result figures |
| Research workflows | `research/` | Short-peptide experiments and analysis scripts |
| Local artifacts | `artifacts/` | Placeholder for local datasets, model downloads, and curated result artifacts |

<br>

<details>
<summary><kbd>Table of Contents</kbd></summary>

<br>

- [Model Overview](#model-overview)
- [Application](#application)
- [Unified Model Architecture](#unified-model-architecture)
- [Why Use PhaseFlow?](#why-use-phaseflow)
- [Key Results](#key-results)
- [Key Modules](#key-modules)
- [Public Resources](#public-resources)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [System Requirements and Verified Environment](#system-requirements-and-verified-environment)
- [Demo and Expected Output](#demo-and-expected-output)
- [Repository Layout](#repository-layout)
- [Models And Datasets](#models-and-datasets)
- [Short-Peptide Usage](#short-peptide-usage)
- [Protein Usage](#protein-usage)
- [Evaluation And Checks](#evaluation-and-checks)
- [Input And Output Formats](#input-and-output-formats)
- [Artifact Policy](#artifact-policy)
- [Figures](#figures)
- [Citation](#citation)
- [License](#license)

<br>

</details>

<br>

## Public Resources

| Resource | Link | Purpose |
| --- | --- | --- |
| Source code | [GitHub: GENTEL-lab/PhaseFlow](https://github.com/GENTEL-lab/PhaseFlow) | Installation, workflows, configurations, and documentation |
| Unified checkpoint | [Hugging Face: GENTEL-Lab/PhaseFlow](https://huggingface.co/GENTEL-Lab/PhaseFlow) | Combined peptide, full-protein, and DPR runtime weights |
| Training data | [Hugging Face: GENTEL-Lab/OpenPhase](https://huggingface.co/datasets/GENTEL-Lab/OpenPhase) | Public peptide, LLPS, and DPR research-data packages |
| Online demo | [phaseflow.bio](http://phaseflow.bio/) | Interactive PhaseFlow usage |

## Quick Start

Install the source package:

```bash
git clone https://github.com/GENTEL-lab/PhaseFlow.git
cd PhaseFlow
conda env create -f environment.yml
conda activate phaseflow
python -m pip install -e .
python -c "import phaseflow; print(phaseflow.__version__)"
```

Check the installation without downloading data or pretrained weights:

```bash
OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" python -m unittest discover \
  -s tests/peptide -p test_phaseflow_smoke.py -v
```

Expected result: three tests pass with `OK`, with no skipped tests. This checks
tokenization and small-model initialization, not pretrained prediction accuracy.

Download the training data and combined runtime checkpoint (repository access
is required):

```bash
python -m pip install huggingface_hub
hf download GENTEL-Lab/OpenPhase \
  --repo-type dataset \
  --local-dir artifacts/data/peptide

hf download GENTEL-Lab/PhaseFlow PhaseFlow.pt \
  --local-dir artifacts/models
```

Use the downloaded `artifacts/models/PhaseFlow.pt` directly in the peptide
inference commands below; a separate peptide checkpoint download is not needed.

Run peptide sequence-to-phase inference:

```bash
bash scripts/peptide/infer.sh \
  artifacts/models/PhaseFlow.pt \
  examples/sequences.txt \
  artifacts/results/peptide/predicted_phases.csv \
  0
```

The training data are hosted at
[`GENTEL-Lab/OpenPhase`](https://huggingface.co/datasets/GENTEL-Lab/OpenPhase).
The [PhaseFlow checkpoint](https://huggingface.co/GENTEL-Lab/PhaseFlow)
is downloaded as `artifacts/models/PhaseFlow.pt`, the path used consistently
throughout the examples below.

## Installation

### Local source install

```bash
conda env create -f environment.yml
conda activate phaseflow
python -m pip install -e .
```

Install optional protein and test dependencies:

```bash
python -m pip install -e ".[protein,test]"
```

Install optional feature-generation dependencies:

```bash
python -m pip install -e ".[plm,starling]"
```

The default source install is intended for code reuse, peptide workflows, and
lightweight checks. Protein reproduction requires external data, feature
stores, and model checkpoints that are not committed to Git.

## System Requirements and Verified Environment

Dependency requirements are declared in [pyproject.toml](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/pyproject.toml) and
[environment.yml](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/environment.yml). Minimum version constraints describe the
installation requirements; they are not a record of versions actually tested.

The following existing environment was inspected on 16 September 2026 and used
to build/install the package and run the three CPU smoke tests for source
revision `58bb0b7fe54fb32ea06de445d42530b40756cfa9`:

| Component | Verified version or configuration |
| --- | --- |
| Operating system | Ubuntu 22.04.4 LTS, x86_64; Linux 5.15.0-105-generic |
| CPU | Intel Xeon Platinum 8352V, 2.10 GHz |
| Python | 3.10.19 |
| PyTorch | 2.10.0; CUDA build 12.8 |
| NumPy / pandas / SciPy | 2.2.6 / 2.3.3 / 1.15.3 |
| PyYAML / tqdm | 6.0.3 / 4.67.3 |
| einops / rotary-embedding-torch | 0.8.2 / 0.8.9 |
| torchdiffeq / POT | 0.2.5 / 0.9.6.post1 |
| Matplotlib | 3.10.8 |
| setuptools / wheel / pip | 80.10.2 / 0.46.3 / 26.0.1 |

This is a package-installation and CPU smoke-test environment, not a claim that
all manuscript experiments or optional protein workflows were validated in it.
The server has NVIDIA A100-SXM4-80GB GPUs and driver 580.95.05, but GPUs were
disabled for this check. No specialized hardware is needed for the CPU smoke
test. GPU inference uses a CUDA-capable NVIDIA GPU; minimum GPU memory
has not been measured here. The peptide prediction demo was
also tested on CPU, as described below.
Training hardware requirements depend on the selected configuration; the
multi-GPU training examples are not minimum requirements for inference.
Windows and macOS have not been validated in this check.

The CUDA 11.8 setting in `environment.yml` is a configurable installation
recipe, not the CUDA 12.8 build used in this verification. To reproduce the
verified environment, use the matching PyTorch build and a compatible driver
rather than assuming the default environment file reproduces these versions.
Optional protein, PLM, and STARLING dependencies are listed separately in
`pyproject.toml` and require their own workflow-specific validation.

### Installation time

Building and installing PhaseFlow into an isolated target directory in the
existing environment took **1.83 seconds** using
`python -m pip install --no-deps --no-build-isolation --target <target-directory> .`.
This excludes environment creation, dependency installation, repository and
checkpoint downloads. A clean-install time on a standard desktop has not yet
been measured; the 1.83-second measurement must not be interpreted as that time.

## Demo and Expected Output

### Verified installation smoke test

The CPU command in Quick Start took **4.16 seconds wall-clock time**, including
Python startup and imports, on the environment above with `OMP_NUM_THREADS=1`.
All three tests passed without skips. Its final output is:

```text
Ran 3 tests in ...s

OK
```

This lightweight check uses built-in test sequences and initializes a small
untrained model. It does not replace a pretrained scientific demo.

### Pretrained peptide prediction

After downloading `PhaseFlow.pt`, use the Quick Start inference command with
[examples/sequences.txt](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/examples/sequences.txt).
The output is `artifacts/results/peptide/predicted_phases.csv`, with one row per
non-empty input sequence and 17 columns: `AminoAcidSequence`, followed by
`group_11` through `group_44` in row-major order. Successful execution prints
`Saved N predictions to ...`, where `N` is the number of input sequences.
The numerical values shown under Input And Output Formats illustrate the
schema; they are not verified reference predictions.

On 16 September 2026, this prediction path was verified on the CPU
environment above using the existing `output_set_flow32_lm0_missing15` peptide
checkpoint (approximately 82 MB; SHA256
`d646bf89f834035125e0ae173b76f09a603888db221296d5ce40a57fbfb93f90`).
All state-dictionary keys matched under an additional strict loading check.
The two sequences in `examples/sequences.txt` produced two rows and 16 phase
values per row in **3.94 seconds wall-clock time**, including startup, imports,
checkpoint loading, inference, and CSV writing. This is a single server-CPU
measurement with `OMP_NUM_THREADS=1`, not a standard-desktop timing or a GPU
benchmark. No GPU was used. The command was:

```bash
OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES="" python scripts/peptide/workflows/predict_seq2phase.py \
  --checkpoint artifacts/models/PhaseFlow.pt \
  --input_file examples/sequences.txt \
  --output artifacts/results/peptide/predicted_phases.csv \
  --device cpu --method euler --batch_size 32
```

The authors confirm that the Hugging Face checkpoint is the same checkpoint
as the server copy used for this test. Timing was measured with that existing
server copy and excludes downloading from Hugging Face. The observed output is
provided in [examples/observed_seq2phase_cpu.csv](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/examples/observed_seq2phase_cpu.csv).
It is a one-run example, not a deterministic numerical regression target: the
prediction command does not fix a random seed. This checkpoint uses normalized
phase targets, so these values should not be presented as calibrated raw-scale
measurements. Its language-model loss weight is zero; this test validates
sequence-to-phase prediction, not phase-conditioned sequence generation.

Only load checkpoints from trusted sources: the current loader uses PyTorch
deserialization with `weights_only=False`.

### Using your own data and reproducing results

Replace `examples/sequences.txt` with a text file containing one amino-acid
sequence per line, or a CSV with an `AminoAcidSequence` column. The underlying
`scripts/peptide/workflows/predict_seq2phase.py` also accepts `--sequence_col`,
`--batch_size`, and `--device cpu` or `--device cuda`. Use sequences within the
checkpoint's supported length; do not infer longer-sequence support from the
input format alone.

For protein dataset construction, training, evaluation, and figure generation,
see the [Protein Reproduction Guide](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/docs/protein/reproduction.md). Those
workflows require the specified data, features, configurations, and checkpoints;
a successful installation smoke test is not evidence that the paper benchmarks
have been reproduced.

## Repository Layout

```text
phaseflow/                 Peptide and protein packages
phaseflow/protein/         Protein model structure and reusable core components
configs/peptide/           Short-peptide configs
configs/protein/       Protein LLPS and DPR configs
docs/peptide/              Short-peptide documentation
docs/protein/          Protein documentation and audit reports
scripts/peptide/           Short-peptide training and inference launchers
scripts/protein/       Protein reproduction workflows and command adapters
scripts/protein/analysis/      Protein benchmark and threshold analyses
scripts/protein/inference/     Standalone protein DPR inference
tests/peptide/             Short-peptide smoke tests
tests/protein/         Protein focused tests
examples/                  Short-peptide demo inputs
scripts/peptide/workflows/     Short-peptide training, inference, and evaluation entry points
scripts/peptide/analysis/      Short-peptide analysis scripts
artifacts/results/peptide/     Curated short-peptide analysis outputs
artifacts/results/protein/     Protein publication results and renderers
figures/peptide/           Short-peptide figures
figures/protein/       Protein LLPS/DPR figures
artifacts/data/            Local datasets and generated feature stores
artifacts/models/          Local model checkpoints downloaded from Hugging Face
artifacts/results/         Lightweight curated result artifacts
```

## Models And Datasets

Large artifacts are intentionally separated from the source repository.

Suggested local layout:

```text
artifacts/data/
  peptide/                 Phase-diagram CSV/NPZ data and split files
  protein/                 Manifests, feature stores, benchmark inputs
artifacts/models/
  PhaseFlow.pt             Combined peptide, full-protein, and DPR checkpoint
```

Public peptide training-data download:

```bash
huggingface-cli download GENTEL-Lab/OpenPhase \
  --repo-type dataset \
  --local-dir artifacts/data/peptide

hf download GENTEL-Lab/PhaseFlow PhaseFlow.pt \
  --local-dir artifacts/models
```

| Resource | Local target | Status |
| --- | --- | --- |
| OpenPhase training data | `artifacts/data/peptide/` | [Available on Hugging Face](https://huggingface.co/datasets/GENTEL-Lab/OpenPhase) |
| Protein feature/data bundle | `artifacts/data/protein/` | Not yet released |
| Combined peptide, full-protein, and DPR checkpoint | `artifacts/models/PhaseFlow.pt` | [Available on Hugging Face](https://huggingface.co/GENTEL-Lab/PhaseFlow) |

## Short-Peptide Usage

### Train

```bash
bash scripts/peptide/train.sh \
  --config configs/peptide/peptide.yaml \
  --data artifacts/data/peptide/phase_diagram_original_scale.csv \
  --output-dir outputs/peptide \
  --gpu 0 \
  --foreground
```

### Predict phase diagrams from sequences

```bash
bash scripts/peptide/infer.sh \
  artifacts/models/PhaseFlow.pt \
  examples/sequences.txt \
  artifacts/results/peptide/predicted_phases.csv \
  0
```

### Generate sequences from target phase diagrams

```bash
python examples/phase2seq_demo.py \
  --checkpoint artifacts/models/PhaseFlow.pt \
  --input_csv artifacts/data/peptide/test_set.csv \
  --num_samples 5
```

### Evaluate peptide models

```bash
python scripts/peptide/workflows/evaluate_seq2phase.py \
  --test_path artifacts/data/peptide/test_set.csv \
  --models_dir outputs/peptide
```

## Protein Usage

The protein code is packaged under `phaseflow.protein`. It expects
downloaded model checkpoints and feature/data bundles under `artifacts/models/protein/`
and `artifacts/data/protein/`.

Protein training configurations:

- `configs/protein/llps.yaml`
- `configs/protein/dpr.yaml`

### IDR sliding-window peptide PhaseFlow helper

```bash
python scripts/protein/inference/predict_protein_dpr.py \
  --input artifacts/data/protein/idr_sequences.xlsx \
  --checkpoint artifacts/models/PhaseFlow.pt \
  --output runs/protein/idr_phaseflow_profiles.jsonl \
  --csv runs/protein/idr_phaseflow_profiles.csv
```

### DPR training entry point

```bash
torchrun --nproc_per_node=8 scripts/protein/run.py train-dpr \
  --config configs/protein/dpr.yaml \
  --arm dpr \
  --updates 50 \
  --output-root runs/dpr
```

This command requires the protein data package, reconstructed feature
stores, and checkpoints referenced by the config.

### Protein figures

```bash
python artifacts/results/protein/scripts/figures/plot_llps_benchmark.py --help
python artifacts/results/protein/scripts/figures/plot_dpr_benchmark.py --help
python artifacts/results/protein/scripts/figures/plot_model_architecture.py \
  --output-dir runs/figures/protein
```

## Evaluation And Checks

Short-peptide checks:

```bash
python -m compileall phaseflow scripts/peptide examples tests/peptide
python -m unittest discover tests/peptide
```

Protein checks:

```bash
python -m compileall phaseflow/protein scripts/protein tests/protein
python -m pytest tests/protein/test_imports.py tests/protein/test_phaseflow_fusion.py
```

Install test dependencies if `pytest` is unavailable:

```bash
python -m pip install -e ".[test]"
```

## Input And Output Formats

### Peptide sequence input

`scripts/peptide/infer.sh` accepts a text file with one amino-acid sequence per
line, or the underlying Python script can read a CSV column named
`AminoAcidSequence`.

```text
ACDEFGHIKLMNPQRSTVWY
GGGGGSSSSSQQQQQNNNNN
```

### Peptide phase output

Sequence-to-phase inference writes a CSV with the sequence and 16 PSSI columns:

```text
AminoAcidSequence,group_11,group_12,...,group_44
ACDEFGHIKLMNPQRSTVWY,0.12,-0.08,...,0.31
```

### Protein IDR helper output

The IDR helper writes JSONL profiles and an optional compact CSV:

```json
{"id":"IDR_000","length":120,"window_sizes":[20],"pssi_mean":0.14}
```

## Artifact Policy

Git tracks code, configs, docs, tests, and curated lightweight figures/results.
It does not track raw datasets, generated feature stores, model checkpoints,
training logs, or large runtime outputs.

Local artifact paths:

- `artifacts/data/peptide/` and `artifacts/data/protein/` for datasets and feature stores.
- `artifacts/models/peptide/` and `artifacts/models/protein/` for Hugging Face model downloads.
- `outputs/` and `logs/` for regenerated training or inference outputs.

The repository `.gitignore` excludes common checkpoint formats such as `.pt`,
`.pth`, `.ckpt`, and `.safetensors`, and also ignores local model files under
`artifacts/models/`.

## Figures

### Protein LLPS

<table>
  <tr>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/llps_benchmark.png" alt="Protein LLPS benchmark" width="100%">
      <br><i>Protein-level LLPS benchmark.</i>
    </td>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/llps_ablation.png" alt="Protein LLPS ablation" width="100%">
      <br><i>Input-stream and weak-supervision ablations.</i>
    </td>
  </tr>
</table>

### DPR Localization

<table>
  <tr>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/dpr_benchmark.png" alt="DPR benchmark" width="100%">
      <br><i>Residue- and region-level DPR benchmark.</i>
    </td>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/dpr_ablation.png" alt="DPR ablation" width="100%">
      <br><i>DPR scanner input and bridge ablations.</i>
    </td>
  </tr>
</table>

<p align="center">
  <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/protein/phasepro_dpr_12exp.png" alt="PhaSePro DPR examples" width="860">
  <br><i>Representative DPR profiles on PhasePro proteins.</i>
</p>

### Peptide Phase Prediction And Design

<table>
  <tr>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/model_comparison.svg" alt="Peptide model comparison" width="100%">
      <br><i>Flow Matching and DDPM phase-diagram comparison.</i>
    </td>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/inference-time-optimization.svg" alt="Inference-time optimization" width="100%">
      <br><i>Phase-conditioned generation and rescoring loop.</i>
    </td>
  </tr>
  <tr>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/denovo_analysis_top5.svg" alt="Top tendency de novo peptide analysis" width="100%">
      <br><i>Generated high-tendency peptide candidates.</i>
    </td>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/denovo_analysis_bottom5.svg" alt="Low tendency de novo peptide analysis" width="100%">
      <br><i>Generated low-tendency peptide candidates.</i>
    </td>
  </tr>
</table>

### Mutation Effects

<table>
  <tr>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/mutation_metrics.png" alt="Mutation benchmark metrics" width="100%">
      <br><i>TDP-43 point-mutation benchmark summary.</i>
    </td>
    <td align="center" width="50%">
      <img src="https://github.com/GENTEL-lab/PhaseFlow/raw/HEAD/figures/peptide/multi_mutation_dose.png" alt="Multi-mutation dose response" width="100%">
      <br><i>Within-panel W-to-G multi-mutant trend.</i>
    </td>
  </tr>
</table>

## Citation

Citation information will be added after the public manuscript and artifact
release are finalized.

## License

This project is licensed under the Apache License, Version 2.0. See
[`LICENSE`](https://github.com/GENTEL-lab/PhaseFlow/blob/HEAD/LICENSE) for details.
