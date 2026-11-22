# AllergenAI — Explainable 3D CNN for Protein Allergen Prediction

> **AI for Molecular Science Capstone Project | Computational Allergenicity Prediction | 3D Deep Learning**

An experimental AI-based system that uses three-dimensional protein structure representations and a 3D Convolutional Neural Network (3D CNN) to classify proteins as allergen or non-allergen.

[![Live App](https://img.shields.io/badge/Live%20App-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://allergenai.streamlit.app/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/Deep%20Learning-PyTorch-orange?logo=pytorch)](https://pytorch.org/)


---

## 1. Problem Statement

Food allergies are immune-mediated reactions triggered by exposure to particular food proteins. Certain proteins found in peanuts, milk, eggs, shellfish, soy and other foods can act as allergens in susceptible individuals.

Traditional computational allergen prediction approaches frequently rely on amino acid sequences and sequence-derived features. However, protein allergenicity is also associated with structural characteristics, including three-dimensional folding and the spatial arrangement of amino acids.

This project investigates a structure-based deep learning approach for protein allergen classification.

The proposed system represents protein structures as three-dimensional voxel grids and processes these representations using a 3D Convolutional Neural Network.

### Research Question

Can three-dimensional protein structural representations be used by a 3D CNN to distinguish known allergenic proteins from non-allergen reference proteins?

### Objectives

- Develop a structure-based protein classification pipeline.
- Convert PDB protein structures into numerical 3D voxel representations.
- Implement a 3D CNN for binary protein classification.
- Evaluate model performance using standard classification metrics.
- Develop an interactive Streamlit application for protein structure analysis.
- Investigate future explainability approaches for understanding model predictions.

---

## 2. Project Overview

AllergenAI follows a structure-based computational workflow.

Unlike a sequence-only prediction pipeline, the current implementation uses atomic coordinates obtained from protein structure files.

The application accepts a protein structure in PDB format and performs the following operations:

1. Reads the uploaded protein structure.
2. Extracts supported atomic coordinates.
3. Converts the coordinates into a fixed-size 3D voxel representation.
4. Passes the voxel representation through a trained 3D CNN.
5. Generates an allergen/non-allergen classification score.
6. Displays the prediction and an interactive 3D protein structure.

### System Architecture

```text
       Protein Structure Input
               |
               v
          Upload PDB
               |
               v
       Structure Processing
               |
               v
       Atomic Coordinate Extraction
               |
               v
         3D Voxelization
          (48 x 48 x 48)
               |
               v
          3D CNN Model
               |
               v
       Sigmoid Classification
               |
               v
       Allergen / Non-Allergen
               |
               v
       Streamlit Application
               |
               v
       Prediction & 3D Viewer
```

---

## 3. Dataset

The project uses protein structure data organised into positive and negative protein collections.

The classification task is formulated as binary classification.

| Class | Label | Description |
|---|---:|---|
| Allergen | 1 | Protein labelled as allergenic in the dataset |
| Non-Allergen | 0 | Protein included as a non-allergen reference |

### Dataset Components

The repository includes:

- Positive protein structure collections.
- Negative protein structure collections.
- Processed voxel representations.
- Structure validation reports.
- Voxelization reports.
- Model evaluation outputs.

### Protein Structure Format

The application accepts Protein Data Bank (PDB) files.

PDB files contain structural information, including atomic coordinates and associated molecular information.

The model processes the following supported atom types:

| Atom | Description |
|---|---|
| C | Carbon |
| N | Nitrogen |
| O | Oxygen |
| S | Sulfur |
| P | Phosphorus |

Each atom type is represented through a separate voxel channel.

### Structure Validation

Protein structures must be checked before model inference.

Important considerations include:

- Availability of atomic coordinates.
- Presence of supported atom types.
- Structural completeness.
- Missing residues and atoms.
- Whether the protein fits within the model's voxel grid.

The supplied structure-validation and voxelization reports each contain 473 entries marked as valid or voxelized.

**Note:** The available repository documentation does not establish the complete dataset provenance, the exact train/validation/test splitting procedure or independent external validation. These details should be documented before making claims about generalisation.

---

## 4. Methodology — Computational Workflow

The current implementation follows a structure-based deep learning pipeline.

| Stage | Description |
|---|---|
| 1. Problem Definition | Formulate protein allergen prediction as a binary classification task. |
| 2. Structure Data Preparation | Organise positive and negative protein structure collections. |
| 3. Structure Validation | Check PDB files and supported atomic coordinates. |
| 4. Atomic Feature Extraction | Extract carbon, nitrogen, oxygen, sulfur and phosphorus coordinates. |
| 5. 3D Voxelization | Convert atomic coordinates into a fixed-size voxel grid. |
| 6. Model Building | Use a 3D CNN to learn structural patterns. |
| 7. Model Evaluation | Assess classification performance using evaluation metrics. |
| 8. Prediction | Generate an allergen/non-allergen classification score. |
| 9. Application Development | Integrate model inference and structure visualisation into Streamlit. |
| 10. Documentation | Document the methodology, results and limitations. |

---

## 5. 3D Feature Representation and Voxelization

A central component of AllergenAI is the conversion of protein structures into numerical representations suitable for deep learning.

### What is Voxelization?

A voxel is the three-dimensional equivalent of a pixel.

While conventional images are represented using two-dimensional pixel grids, voxelization represents spatial information using a three-dimensional grid.

In this project, atomic coordinates are converted into a fixed-size grid.

### Voxelization Configuration

| Parameter | Configuration |
|---|---|
| Grid dimensions | 48 × 48 × 48 |
| Voxel size | 2.5 Å |
| Input channels | 5 |
| Atom types | C, N, O, S, P |
| Coordinate processing | Centering and grid mapping |

The resulting representation has the shape:

```python
(5, 48, 48, 48)
```

Each channel corresponds to one supported atom type.

Atoms are mapped to their corresponding spatial grid locations.

Coordinates falling outside the predefined grid are counted rather than represented. The application provides a warning when this occurs.

### Why Use 3D Voxelization?

Voxelization allows the model to process the spatial arrangement of atoms using three-dimensional convolution operations.

This provides a way to investigate structural patterns that cannot be directly represented by a simple protein sequence.

---

## 6. Deep Learning Model — 3D CNN

The project uses a three-dimensional Convolutional Neural Network implemented using PyTorch.

A 3D CNN applies convolution operations across three spatial dimensions to learn patterns from volumetric input data.

### Model Architecture

The implemented network contains three convolutional blocks.

| Layer | Input Channels | Output Channels |
|---|---:|---:|
| Convolution Block 1 | 5 | 16 |
| Convolution Block 2 | 16 | 32 |
| Convolution Block 3 | 32 | 64 |

Each convolution block applies:

- 3D Convolution.
- Batch Normalization.
- ReLU activation.
- Max Pooling.

The resulting feature representation is processed using adaptive average pooling and fully connected layers to produce a single classification score.

### Model Architecture Flow

```text
Input Voxel Grid
  (5 x 48 x 48 x 48)
          |
          v
    3D Convolution
       5 -> 16
          |
          v
    BatchNorm + ReLU
          |
          v
      Max Pooling
          |
          v
    3D Convolution
      16 -> 32
          |
          v
    BatchNorm + ReLU
          |
          v
      Max Pooling
          |
          v
    3D Convolution
      32 -> 64
          |
          v
    BatchNorm + ReLU
          |
          v
      Max Pooling
          |
          v
 Adaptive Average Pooling
          |
          v
   Fully Connected Layers
          |
          v
       Output Score
          |
          v
        Sigmoid
          |
          v
  Binary Classification
```

### Classification

The final model output is passed through a sigmoid function.

The resulting score is between 0 and 1.

The application applies the following threshold:

| Score | Predicted Class |
|---|---|
| ≥ 0.5 | Allergen |
| < 0.5 | Non-Allergen |

The displayed score is a model output and should not be interpreted as a clinically calibrated probability of an allergic reaction.

### Trained Model

The repository includes the trained model weights:

`allergen3d_cnn_final.pt`

The current repository contains the inference implementation and trained weights. A complete model-training script is not included in the documented application workflow.

---

## 7. Model Evaluation and Results

The supplied evaluation results indicate promising classification performance on the available test set.

### Evaluation Metrics

| Metric | Reported Value |
|---|---:|
| Accuracy | **91.7%** |
| Precision | **87.5%** |
| Recall | **100%** |
| F1-Score | **93.3%** |
| ROC-AUC | **0.998** |

### Confusion Matrix

The supplied test-prediction file contains 48 examples:

- 28 allergen examples.
- 20 non-allergen examples.
- 44 correctly classified predictions.

The reported metrics and test counts correspond to the following confusion matrix:

| Actual / Predicted | Allergen | Non-Allergen |
|---|---:|---:|
| Allergen | 28 | 0 |
| Non-Allergen | 4 | 16 |

### Key Observations

- The model achieved a reported test accuracy of 91.7%.
- Recall reached 100% on the supplied test set, meaning all 28 positive examples were identified.
- Precision was 87.5%, indicating that some negative reference proteins were incorrectly classified as allergens.
- The reported ROC-AUC of 0.998 indicates strong discrimination on the supplied evaluation data.

### Interpretation

The results demonstrate that the current prototype can perform binary classification on its supplied evaluation dataset.

However, the test set contains only 48 examples. The reported metrics should therefore be treated as preliminary rather than conclusive evidence of generalisation.

Further validation using larger, independent and sequence-similarity-aware test datasets is necessary.

---

## 8. Streamlit Application

AllergenAI includes a deployed Streamlit application for interactive protein structure analysis and model inference.

### Live Application

**[Launch AllergenAI — Live Streamlit Application](https://allergenai.streamlit.app/)**

### Application Features

| Feature | Description |
|---|---|
| PDB Upload | Upload a protein structure file. |
| Structure Processing | Extract supported atomic coordinates. |
| 3D CNN Prediction | Generate an allergen/non-allergen prediction. |
| Protein Information | Display available protein sequence and composition information. |
| 3D Visualisation | Explore protein structures interactively. |
| Evaluation Metrics | Display the supplied model evaluation results. |
| PDF Report | Generate and download a prediction report. |

### Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core programming language |
| PyTorch | 3D CNN model and inference |
| Biopython | PDB structure and sequence processing |
| NumPy | Numerical processing |
| Streamlit | Interactive web application |
| py3Dmol | Three-dimensional molecular visualisation |
| ReportLab | PDF report generation |
| Pandas | Evaluation metric handling |

### Access the Application

The application is publicly accessible through Streamlit Community Cloud.

**Live URL:** https://allergenai.streamlit.app/

**Important:** The sequence information displayed in the application is for inspection. The current classifier uses the 3D voxel representation, not the displayed amino acid sequence.



---

## 9. Project Structure

```text
AllergenAI/
│
├── allergen_capstone/
│   │
│   └── AllergenAI_3D_CNN/
│       │
│       ├── data/
│       │   ├── positive/
│       │   ├── negative/
│       │   └── voxel_data/
│       │
│       ├── models/
│       │   └── trained model files
│       │
│       ├── results/
│       │   ├── evaluation metrics
│       │   ├── test predictions
│       │   ├── structure validation
│       │   └── voxelization reports
│       │
│       └── streamlit_app/
│           ├── app.py
│           ├── allergen3d_cnn_final.pt
│           ├── 3d_cnn_evaluation_metrics.csv
│           └── requirements.txt
│
├── docs/
│   └── AllergenAI_Approach_Explained.pdf
│
├── .gitignore
├── README.md
└── requirements.txt
```

*Note: This is a logical overview of the documented repository components; individual dataset filenames and subfolder names should be updated to match the actual repository.*

---

## 10. Installation and Execution

### Prerequisites

- Python.
- Git.
- pip.
- A compatible PyTorch installation.

### Run on Windows

```powershell
# 1. Clone the repository
git clone <YOUR_REPOSITORY_URL>

# 2. Navigate to the application directory
cd AllergenAI/allergen_capstone/AllergenAI_3D_CNN/streamlit_app

# 3. Create a virtual environment
py -3 -m venv .venv

# 4. Activate the environment
.\.venv\Scripts\Activate.ps1

# 5. Install dependencies
python -m pip install -r requirements.txt

# 6. Launch the application
python -m streamlit run app.py
```

Open the local Streamlit URL:

```text
http://localhost:8501
```

### Required Application Files

Ensure the following files are available inside the `streamlit_app` directory:

| File | Purpose |
|---|---|
| `app.py` | Streamlit application |
| `allergen3d_cnn_final.pt` | Trained model weights |
| `3d_cnn_evaluation_metrics.csv` | Evaluation metrics |
| `requirements.txt` | Application dependencies |

---

## 11. Limitations

The current implementation has several limitations that must be considered when interpreting its predictions.

- The test dataset is relatively small, containing 48 examples.
- Independent external validation has not been established.
- The complete dataset provenance and splitting strategy require further documentation.
- Similar protein sequences across training and test datasets could influence reported performance if not properly controlled.
- Structure quality and missing atomic coordinates can affect voxel representations.
- Atoms outside the fixed voxel grid are not represented.
- The current implementation performs protein-level binary classification.
- It does not establish specific IgE-binding epitopes or experimentally confirmed allergenic hotspots.
- The prediction score is not a clinically validated probability.
- The supplied repository does not include the complete model-training workflow.

**Safety and Research Disclaimer**

AllergenAI is an experimental computational research prototype. It is not a medical diagnostic system and must not be used for clinical decisions, food labelling, dietary recommendations or food-safety assessments.

---

## 12. Future Research Directions

The following are proposed extensions rather than features claimed to be fully implemented in the current prototype.

| Proposed Extension | Research Motivation |
|---|---|
| Larger and more diverse datasets | Improve data coverage and evaluation reliability. |
| Sequence-similarity-aware splitting | Reduce potential data leakage. |
| Sequence-based CNN baseline | Establish a reference for structure-based prediction. |
| PointNet / PointNet++ | Investigate point-cloud representations of protein surfaces. |
| Surface feature extraction | Incorporate hydrophobicity, charge and geometric characteristics. |
| Sequence–structure fusion | Combine complementary protein representations. |
| Explainable AI | Investigate model-attributed regions using suitable attribution methods. |
| IEDB epitope comparison | Compare predicted regions with documented IgE-binding epitopes. |
| External validation | Evaluate performance on independent protein datasets. |
| Prediction calibration | Improve the interpretation of model scores. |

The broader research direction is to investigate whether incorporating protein structural information and model explainability can improve computational allergen prediction.

---

## 13. References and Resources

- [Protein Data Bank (PDB)](https://www.rcsb.org/) — Experimental protein structures.
- [AlphaFold Protein Structure Database](https://alphafold.ebi.ac.uk/) — Predicted protein structures.
- [AllergenOnline](https://www.allergenonline.org/) — Food allergen protein information.
- [SDAP](https://fermi.utmb.edu/SDAP/) — Structural Database of Allergenic Proteins.
- [COMPARE](https://comparedatabase.org/) — Allergen information and comparison resources.
- [Immune Epitope Database (IEDB)](https://www.iedb.org/) — Experimentally documented immune epitopes.
- [PyTorch](https://pytorch.org/) — Deep learning framework.
- [Biopython](https://biopython.org/) — Biological sequence and structure processing.
- [Streamlit](https://streamlit.io/) — Application development framework.
- [3Dmol.js](https://3dmol.csb.pitt.edu/) — Molecular structure visualisation.

---

## 14. Project Information

**Project Title:** AllergenAI — Explainable 3D CNN for Protein Allergen Prediction

**Course:** AI for Molecular Science — Capstone Project

**Domain:** Bioinformatics | Artificial Intelligence | Computational Biology | Deep Learning

### Authors

- **Aparna Sreenivasan**
- **Sreekutty Santhosh**

### Technical Overview

| Component | Details |
|---|---|
| Primary Approach | 3D Convolutional Neural Network |
| Input | Protein structure (PDB) |
| Representation | 3D voxel grid (48 × 48 × 48) |
| Output | Allergen / Non-Allergen classification |
| Framework | PyTorch |
| Application | Streamlit |

**Live Application:** [AllergenAI — Streamlit](https://allergenai.streamlit.app/)

**Development Status:** Deployed Experimental Research Prototype

---

*Developed as part of the AI for Molecular Science Capstone Project.*

**Development Status:** Experimental research prototype

---

> AllergenAI explores the intersection of structural bioinformatics and deep learning to investigate computational approaches for protein allergen prediction.
