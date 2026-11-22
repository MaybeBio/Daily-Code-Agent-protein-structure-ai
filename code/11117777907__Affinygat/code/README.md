# AffinyGAT

**An Edge-Conditioned Heterogeneous Graph Attention Network for Protein–Ligand Binding Affinity Prediction**

## 1. Overview

AffinyGAT is a structure-based deep learning model for protein–ligand binding affinity prediction. It integrates heterogeneous graph attention mechanisms with physicochemical interaction priors and multi-scale interaction representations.

This repository provides the inference and external validation code of AffinyGAT, including pretrained model parameters and graph data processing modules.

**Main functionalities:**

- External validation on CASF-2013 and CASF-2016.
- Binding affinity prediction for new protein–ligand complexes.
- Protein–ligand structure preprocessing and heterogeneous graph construction.

The model training implementation (`train.py`) is not included in this release.

## 2. Repository Structure

```text
AffinyGAT/
│
├── README.md
├── LICENSE
├── requirements.txt
├── environment.yml
│
├──data/
    ├── CASF2013/
    ├── CASF2016/
│
├── test.py
├── predict.py
├── dataset.py
│── model.py
│
├── attention/
│
├── model/
│   └── trained_model.pt
│
├── predict/
    └── predict_results.csv
```

| File/Directory | Function                                                      |
| -------------- | ------------------------------------------------------------- |
| `test.py`      | External benchmark evaluation and performance calculation.    |
| `predict.py`   | Binding affinity prediction for new protein–ligand complexes. |
| `dataset.py`   | Protein–ligand structure processing and graph construction.   |
| `model/`       | Model architecture and pretrained parameters.                 |
| `attention/`   | Attention-related modules.                                    |
| `predict/`     | Supporting prediction modules.                                |
| `data/`        | Processed protein–ligand graph data.                          |

## 3. Installation

### 3.1 Clone the repository

```bash
git clone https://github.com/<11117777907>/AffinyGAT.git
cd AffinyGAT
```

### 3.2 Create the environment

**Option 1: Conda**

```bash
conda env create -f environment.yml
conda activate <affinygat>
```

**Option 2: pip**

```bash
pip install -r requirements.txt
```

Use either Conda or pip to install the dependencies.

## 4. Pretrained Models and Data

### 4.1 Pretrained Model Parameters

Pretrained AffinyGAT parameters are provided in the `model/` directory.

The inference scripts directly load the corresponding `.pt` checkpoint files. No additional model training is required.

### 4.2 Dataset Sources

The datasets used in this study were obtained from the following official sources:

- **PDBbind v2019:** https://www.pdbbind-plus.org.cn/download
- **CASF-2013 and CASF-2016:** https://www.pdbbind-plus.org.cn/casf

The `data/` directory contains the corresponding processed graph representations generated using the AffinyGAT preprocessing pipeline.

The original PDB and SDF database files are not redistributed in this repository.

## 5. Usage

### 5.1 External Validation

The `test.py` script evaluates AffinyGAT on the CASF-2013 and CASF-2016 benchmark datasets.

The script loads the processed graph data and pretrained model parameters, performs inference, and calculates the following evaluation metrics:

- Pearson correlation coefficient (Rp)
- Root Mean Square Error (RMSE)

Run:

```bash
python test.py
```

Ensure that the data and checkpoint paths are configured correctly before execution.



### 5.2 Prediction of New Protein–Ligand Complexes

The `predict.py` script supports binding affinity prediction for new protein–ligand complexes.

**Input:**

- Protein structure: PDB format (`.pdb`)
- Ligand structure: SDF format (`.sdf`)

Run:

```bash
python predict.py
```

Configure the protein, ligand, and pretrained model paths according to the script implementation.

**Output:**

Predicted protein–ligand binding affinity expressed as pKd.

Higher pKd values indicate stronger predicted binding affinity.

## 6. Data Availability and License

The source code is released under the MIT License. The source code license does not automatically apply to the original datasets or separately licensed data files.

## 7. Contact

For questions regarding the implementation or use of AffinyGAT, please contact:

**Author:** [Yuhuan Meng]

**Institution:** Guangxi Normal University

**Email:** [mengyh371@163.com]
