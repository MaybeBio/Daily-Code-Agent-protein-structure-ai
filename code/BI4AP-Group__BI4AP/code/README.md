# BI4AP: A Multimodal Knowledge Distillation Framework for Ultra-Large-Scale Binding Affinity Prediction

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-ee4c2c.svg)](https://pytorch.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## Overview

**BI4AP** is an asymmetric multimodal knowledge distillation framework designed to bridge the gap between high-precision structural interaction modeling and ultra-large-scale virtual screening.

Traditional molecular docking and 3D/2D structure-based deep learning methods achieve strong predictive accuracy but suffer from prohibitive computational overhead when screening millions of compounds. To overcome this bottleneck, BI4AP adopts a three-stage **Teacher–Student** pipeline:

1. **Automated Interaction Extraction (YOLOv8):** Detects and extracts key residue-level interaction regions from 2D protein–ligand interaction diagrams.
2. **Multimodal Teacher Model:** Integrates 2D interaction graphs (via a dual-stream ResNet-152 visual backbone with cross-attention), 1D molecular representations (SMILES / Morgan fingerprints), and physicochemical residue descriptors. Ablation studies confirm that the 2D interaction graph branch serves as the dominant feature contributor.
3. **Lightweight 1D Student Distillation:** Transfers spatial interaction "dark knowledge" from the multimodal teacher to a sequence-only 1D student model (e.g., MolFormer / ChemBERTa). At inference time, the student requires **only 1D SMILES strings**, eliminating 3D docking and 2D rendering overhead while delivering a $>10{,}000\times$ speedup over traditional molecular docking on multi-million-scale compound libraries (e.g., ZINC).

<!-- Optional: Place your Graphical Abstract or Framework Diagram in an assets/ folder and uncomment below -->

<!-- ![BI4AP Framework](https://github.com/BI4AP-Group/BI4AP/raw/HEAD/assets/framework_overview.png) -->

---

## Repository Structure

```text
BI4AP/
├── 01_yolo_extraction/             # Stage 1: YOLOv8 detection & feature extraction
│   ├── datasets/
│   │   └── amino_yolo/             # Annotated 2D interaction dataset (YOLO format)
│   │       ├── data.yaml           # Dataset configuration file
│   │       ├── images/             # Training and validation images
│   │       └── labels/             # Bounding box annotations (.txt)
│   ├── train.py                    # Train YOLOv8 interaction detector
│   └── predict.py                  # Batch inference & interaction feature extraction
├── 02_teacher_training/            # Stage 2: Multimodal Teacher training & inference
│   ├── acid.xlsx                   # Amino acid physicochemical descriptor table
│   ├── mode.py                     # Multimodal Teacher model training & ablation
│   └── mode_prediction.py          # Teacher inference & soft-label generation
├── 03_student_distillation/        # Stage 3: 1D Student distillation & screening
│   ├── student_train.py            # Knowledge distillation training for 1D Student
│   └── predict.py                  # High-throughput virtual screening via Student model
├── demo_data/                      # Minimal toy datasets for quick testing & format reference
├── requirements.txt                # Core Python dependencies
├── .gitignore                      # Excluded cache, logs, and large weight files
├── LICENSE                         # MIT License
└── README.md                       # Project documentation
```

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/BI4AP-Group/BI4AP.git
cd BI4AP
```

### 2. Create a Conda Environment

We recommend Python 3.9+ with a CUDA-enabled GPU:

```bash
conda create -n bi4ap python=3.9 -y
conda activate bi4ap
```

### 3. Install Dependencies

First, install PyTorch matching your local CUDA version (refer to [PyTorch Official Guide](https://pytorch.org/get-started/locally/)), then install the remaining packages:

```bash
# Example for CUDA 11.8
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Install core dependencies
pip install -r requirements.txt
```

### 4. Pre-trained Molecular Backbone

Stage 3 utilizes a pre-trained chemical language model (e.g., `ibm/MoLFormer-XL-both-10pct` or ChemBERTa) from HuggingFace. Ensure internet access for automatic download, or place the downloaded checkpoint locally and update the model path in `03_student_distillation/student_train.py` and `predict.py`.

---

## Step-by-Step Usage

### Stage 1: YOLOv8 Interaction Feature Extraction

Before training, verify that the dataset path inside `01_yolo_extraction/datasets/amino_yolo/data.yaml` uses the relative path (`path: ./datasets/amino_yolo`).

```bash
cd 01_yolo_extraction

# 1. Train the YOLOv8 detector on 2D interaction diagrams
python train.py

# 2. Run inference to extract residue interaction features
python predict.py
```

### Stage 2: Multimodal Teacher Model Training

The Teacher model fuses 2D interaction graphs, 1D SMILES fingerprints, and the residue physicochemical descriptors stored in `acid.xlsx`.

```bash
cd ../02_teacher_training

# 1. Train the multimodal Teacher model (and run modality ablation variants)
python mode.py

# 2. Generate teacher predictions / soft targets for downstream distillation
python mode_prediction.py
```

### Stage 3: Student Knowledge Distillation & Virtual Screening

Using the soft targets generated by the Teacher model, train the lightweight 1D Student model and perform rapid SMILES-only affinity prediction.

```bash
cd ../03_student_distillation

# 1. Distill spatial knowledge into the 1D Student model
python student_train.py

# 2. Perform high-throughput affinity prediction on target SMILES CSV files
python predict.py
```

> **Note:** Please review the configurable input/output file paths at the top of each script before execution to match your local dataset location.
>
> **Note on `demo_data/`:** The files in `demo_data/` serve solely as minimal placeholder datasets for input format reference and end-to-end pipeline verification. While filenames and ID indices are strictly aligned for code execution, the 2D interaction images and binding affinity values (`merger_aff`) are chemically decoupled dummy pairings. Therefore, numerical predictions generated on `demo_data/` carry no chemical significance and do not reflect the model performance reported in the manuscript.

## License

This project is licensed under the **MIT License** — see the [LICENSE](https://github.com/BI4AP-Group/BI4AP/blob/HEAD/LICENSE) file for details.

## Contact

For questions, bug reports, or collaboration inquiries, please open an issue in this repository or contact `<zhangjz623@163.com>`.
