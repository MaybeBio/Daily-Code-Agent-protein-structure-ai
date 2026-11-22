# Predicting peptide aggregation propensity from sequence

How accurately can a model predict the aggregation propensity (AP) of a short peptide from its sequence? The target comes from coarse-grained molecular dynamics simulations of peptides five to ten residues long. On 3,997 held-out sequences, the LSTM and Transformer had similar mean absolute errors (0.0385 and 0.0379 AP units). Both made larger absolute errors on five-residue peptides than on ten-residue peptides. The five-residue group also had a wider spread of simulated AP values, and both models improved more over a simple baseline in that group. [Length and model comparisons](#error-relative-to-a-length-only-baseline)

## Try it with the included predictions

From the repository root, run the following command with Python 3. It reads the saved test predictions and recomputes mean absolute error, root mean squared error and R² using the standard library.

```sh
python examples/summarize_predictions.py
```

For a one-page overview, read the [project summary](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/project_summary.pdf). To explore where the models make errors, open the [error analysis notebook](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/04_error_analysis.ipynb). It uses the same [test predictions](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/results/test_predictions_all_models.csv). The [training instructions](#11-how-to-run) cover the full workflow.

---

## 1. Project Overview

Peptide self-assembly is strongly influenced by amino-acid composition, sequence order, hydrophobicity, charge, polarity, and aromatic interactions. Since the full peptide sequence space expands exponentially with sequence length, computational models can help predict peptide aggregation propensity and support the discovery of self-assembling peptide candidates.

In this project, I investigate the following question:

> Can sequence-based machine-learning models predict peptide aggregation propensity, and can we interpret what chemical patterns the best model learns?

To address this question, the project includes:

1. Exploratory data analysis of peptide AP labels and amino-acid composition
2. Classical machine-learning baselines using handcrafted features
3. Neural-network models, including MLP, LSTM, and Transformer
4. Test-set error analysis by sequence length and AP interval
5. Transformer interpretability using in-silico single-point mutation scanning

---

## 2. Dataset

The AP labels are derived from coarse-grained molecular dynamics (CGMD) simulations. The regression data and published splits used here are available in [Liu et al.’s data repository at the matching commit](https://github.com/Zihan-Liu-00/BiB_ADV-SCI--DL_for_Peptide/tree/695f95f7c6cc942f25a5fc2654b974cb3cc8ab92/Sequential_Peptides).

The dataset contains peptide sequences from pentapeptides to decapeptides and their corresponding aggregation propensity labels. In this project, the main files are expected to be placed under:

```text
Sequential_Peptides/
├── collection_of_peptide_data.csv
├── train_seqs.csv
├── valid_seqs.csv
└── test_seqs.csv
```

The AP label represents the aggregation propensity of a peptide system. Higher AP values indicate stronger predicted aggregation tendency in the simulation setting.

In this project, the train/validation/test splits contain approximately:

| Split      |            Number of Samples |
| ---------- | ---------------------------: |
| Training   |                       54,159 |
| Validation | 3,999 after overlap cleaning |
| Test       | 3,997 after overlap cleaning |

A small number of overlapping peptide sequences between splits were detected and removed from the validation and test sets to avoid sequence-level data leakage.

---

## 3. Repository Structure

```text
peptide-ap-prediction/
├── README.md
├── requirements.txt
├── 01_data_exploration.ipynb
├── 02_classical_baselines.ipynb
├── 03_neural_networks.ipynb
├── 04_error_analysis.ipynb
├── 05_interpretability_mutation_scan.ipynb
├── Sequential_Peptides/
│   ├── collection_of_peptide_data.csv
│   ├── train_seqs.csv
│   ├── valid_seqs.csv
│   └── test_seqs.csv
├── results/
│   ├── classical_model_comparison.csv
│   ├── neural_network_overall_metrics.csv
│   ├── test_predictions_all_models.csv
│   ├── test_error_analysis_all_models.csv
│   ├── global_mutant_effect_summary.csv
│   ├── global_original_amino_acid_effect_summary.csv
│   ├── global_mutation_effect_matrix.csv
│   └── global_position_specific_mutation_effect.csv
└── figures/
    ├── ap_distribution.png
    ├── model_comparison.png
    ├── transformer_predictions_vs_true_ap.png
    ├── prediction_bias_by_ap_group.png
    ├── mutation_effect_matrix.png
    └── position_specific_mutation_effect.png
```

---

## 4. Workflow

The project is organized into five notebooks.

| Notebook                                  | Purpose                                                                                       |
| ----------------------------------------- | --------------------------------------------------------------------------------------------- |
| `01_data_exploration.ipynb`               | Explore AP distribution, sequence length, amino-acid frequency, and high-vs-low AP enrichment |
| `02_classical_baselines.ipynb`            | Train classical ML baselines using AAC, positional one-hot, and combined features             |
| `03_neural_networks.ipynb`                | Train MLP, LSTM, and Transformer models                                                       |
| `04_error_analysis.ipynb`                 | Analyze test-set errors by peptide length, AP group, and residual bias                        |
| `05_interpretability_mutation_scan.ipynb` | Interpret the trained Transformer using in-silico single-point mutation scanning              |

The overall workflow is:

```text
Peptide sequences
        ↓
Data exploration and split cleaning
        ↓
Feature engineering / sequence tokenization
        ↓
Classical ML and neural-network models
        ↓
Test-set prediction and model comparison
        ↓
Error analysis
        ↓
Mutation-scan interpretability
```

---

## 5. Feature Representations

This project compares three main types of sequence representation.

### 5.1 Amino Acid Composition (AAC)

AAC represents each peptide as a 20-dimensional vector, where each feature is the frequency of one natural amino acid in the sequence.

This representation captures global composition but discards sequence order.

### 5.2 Positional One-Hot Encoding

Each amino acid position is represented using a 20-dimensional one-hot vector. Peptides are padded to a maximum length of 10.

This representation captures position information but is sparse and may be less effective when peptide lengths vary.

### 5.3 Combined Handcrafted Features

The combined representation includes:

* AAC features
* Positional one-hot features
* Normalized peptide length

This representation is used for the MLP model and for classical ML baselines.

### 5.4 Tokenized Sequence Representation

For LSTM and Transformer models, each amino acid is encoded as a token. Padding is used for variable-length peptides.

This representation allows sequence models to learn order-dependent and context-dependent sequence patterns.

---

## 6. Models

The project evaluates both classical machine-learning models and neural-network models.

### 6.1 Classical Machine-Learning Models

The classical baselines include:

* Linear Regression
* Ridge Regression
* Random Forest Regressor
* HistGradientBoosting Regressor

These models were trained on AAC, positional one-hot, and combined handcrafted features.

### 6.2 Neural-Network Models

Three neural-network models were evaluated:

| Model       | Input Representation          |
| ----------- | ----------------------------- |
| MLP         | Combined handcrafted features |
| LSTM        | Tokenized peptide sequence    |
| Transformer | Tokenized peptide sequence    |

The Transformer encoder model uses token embeddings, positional embeddings, self-attention layers, masked mean pooling, and an MLP regression head.

---

## 7. Key Results

The Transformer model achieved the best overall performance among the neural-network models.

| Model       | Input Representation          | Test MAE | Test RMSE | Test R² |
| ----------- | ----------------------------- | -------: | --------: | ------: |
| MLP         | Combined handcrafted features |   0.0413 |    0.0525 |  0.9381 |
| LSTM        | Tokenized sequence            |   0.0385 |    0.0488 |  0.9466 |
| Transformer | Tokenized sequence            |   0.0379 |    0.0480 |  0.9483 |

These metrics use the [saved predictions](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/results/test_predictions_all_models.csv) from one training run. They measure agreement with simulation-derived AP on this split.

Among the classical baselines, the best combined-feature model was HistGradientBoosting, which achieved:

| Model                | Input Representation          | Test MAE | Test R² |
| -------------------- | ----------------------------- | -------: | ------: |
| HistGradientBoosting | Combined handcrafted features |   0.0525 |  0.8924 |

Compared with the best classical baseline, the Transformer achieved a substantially lower test MAE.

---

## 8. Selected Figures

### 8.1 AP Distribution

![AP Distribution](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/ap_distribution.png)

This figure shows the distribution of AP labels in the dataset. Understanding the label distribution is important because extreme low-AP and high-AP samples are relatively more difficult to predict.

### 8.2 Model Comparison

![Model Comparison](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/model_comparison.png)

The chart compares the three neural networks with the strongest classical baseline, histogram gradient boosting (HGB).

### 8.3 Transformer Predictions vs True AP

![Transformer Predictions vs True AP](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/transformer_predictions_vs_true_ap.png)

The Transformer predictions are strongly correlated with the true AP values, with the best overall test performance among the evaluated models.

### 8.4 Prediction Bias by AP Group

![Prediction Bias by AP Group](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/prediction_bias_by_ap_group.png)

The model shows mild regression-to-the-mean behavior. Low-AP peptides tend to be slightly overestimated, while high-AP peptides tend to be slightly underestimated.

### 8.5 Mutation Effect Matrix

![Mutation Effect Matrix](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/mutation_effect_matrix.png)

The mutation effect matrix summarizes how replacing one amino acid with another changes the Transformer-predicted AP.

### 8.6 Position-Specific Mutation Effect

![Position-Specific Mutation Effect](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/position_specific_mutation_effect.png)

This figure shows that residue identity is the dominant factor, while position-specific effects are also present.

---

## 9. Error Analysis

The test-set error analysis revealed several patterns:

1. Sequence-based neural models outperformed the MLP based on handcrafted features.
2. The Transformer achieved the lowest overall MAE and highest R².
3. Shorter peptides showed larger absolute errors than longer peptides.
4. Low-AP samples tended to be slightly overestimated.
5. High-AP samples tended to be slightly underestimated.
6. Some high-error cases involved complex interactions among aromatic, charged, and polar residues.

This suggests that the model captures important sequence-dependent information, but extreme AP samples remain more challenging.

### Error relative to a length-only baseline

How much does the sequence model add if peptide length is already known? For each length from five to ten, a baseline predicts the median AP of that length in the original training split. We compare each saved model prediction with that baseline on the same test peptides. The table below shows the shortest and longest groups for the Transformer.

| Test group | Peptides | SD of reference AP | Baseline MAE | Transformer MAE | MAE reduction vs baseline | Within-length R² |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Five residues | 666 | 0.2873 | 0.2205 | 0.0465 | 78.9% | 0.9582 |
| Ten residues | 841 | 0.1560 | 0.1208 | 0.0336 | 72.2% | 0.9261 |

The Transformer made larger errors in AP units on five-residue peptides, yet reduced the baseline error by an additional **6.69 percentage points** (pointwise 95% bootstrap interval **4.04 to 9.35**). The MLP and LSTM showed the same direction for this five-versus-ten comparison. Within-length R² uses the test-group mean to calculate the variation in the reference labels. Differences in the distribution of these labels matter when comparing lengths. [All six lengths and three models](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/results/length_evaluation/by_length.csv) · [Five-minus-ten contrasts](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/results/length_evaluation/endpoint_contrasts.csv)

![Raw MAE and relative MAE reduction by peptide length for MLP, LSTM and Transformer](https://github.com/YOOZOY/peptide-ap-prediction/raw/HEAD/figures/error_relative_to_length_baseline.png)

Comparing models on **the same peptides**, the Transformer minus LSTM difference in MAE was **−0.00055 AP** (95% interval **−0.00124 to +0.00013**). This split gives little basis for choosing between them on MAE. The corresponding contrasts against the MLP favored both the Transformer (−0.00338 AP) and the LSTM (−0.00283 AP). Weighting all six lengths equally gave similar contrasts. [Paired estimates and intervals](https://github.com/YOOZOY/peptide-ap-prediction/blob/HEAD/results/length_evaluation/paired_mae_contrasts.csv)

These are exploratory comparisons of fixed predictions. The 10,000 bootstrap draws resample peptide rows within each length, keeping the label and all three predictions together (seed 20261118). The intervals condition on these trained models, the six training medians and the observed sample sizes. Related sequences may share errors. Training-seed variation, independent simulation sources and experimental aggregation lie outside this comparison.

To reproduce the tables and figure, place the pinned [upstream regression training CSV](https://github.com/Zihan-Liu-00/BiB_ADV-SCI--DL_for_Peptide/blob/695f95f7c6cc942f25a5fc2654b974cb3cc8ab92/Sequential_Peptides/train_seqs.csv) under `Sequential_Peptides/`. The analysis uses NumPy and pandas. The plotting command uses Matplotlib. Run both from the repository root.

```sh
python analysis/evaluate_by_length.py --training-csv Sequential_Peptides/train_seqs.csv
python analysis/plot_length_evaluation.py
```

---

## 10. Interpretability Analysis

To interpret the trained Transformer model, I performed in-silico mutation scanning.

For each sampled peptide, each amino-acid position was systematically replaced by the other 19 natural amino acids. The change in predicted aggregation propensity was recorded as:

```text
delta_AP = predicted_AP(mutant) - predicted_AP(original)
```

Positive `delta_AP` means the mutation increases the Transformer-predicted AP. Negative `delta_AP` means the mutation decreases the predicted AP.

The global mutation scan was performed on 500 randomly sampled test peptides and generated 72,162 single-point mutant predictions.

### 10.1 Main Findings

The mutation scanning analysis showed chemically meaningful patterns:

* Mutations into aromatic residues W, F, and Y generally increased predicted AP.
* Histidine H also showed a positive effect, but weaker than W/F/Y.
* Hydrophobic aliphatic residues such as L, I, and V showed mild positive effects.
* Mutations into charged or strongly polar residues such as E, D, Q, N, R, and K generally decreased predicted AP.
* Replacing W/F/Y with charged or polar residues led to strong decreases in predicted AP.
* Replacing charged or polar residues with W/F/Y led to strong increases in predicted AP.

These findings suggest that the Transformer learned chemically plausible sequence patterns related to aromaticity, hydrophobicity, charge, and polarity.

### 10.2 Important Caution

The mutation scan explains the behavior of the trained Transformer model. It should be interpreted as a model-based explanation rather than direct experimental evidence. The results do not prove that a specific mutation will necessarily cause the same AP change in real experiments.

---

## 11. How to Run

### 11.1 Install Dependencies

A minimal Python environment should include:

```text
numpy
pandas
matplotlib
scikit-learn
torch
jupyter
```

Install the dependencies with:

```bash
pip install -r requirements.txt
```

### 11.2 Prepare the Dataset

The raw peptide sequence data are not included in this public repository.

For the training workflow, download the four regression CSVs listed below from the [upstream dataset](https://github.com/Zihan-Liu-00/BiB_ADV-SCI--DL_for_Peptide/tree/695f95f7c6cc942f25a5fc2654b974cb3cc8ab92/Sequential_Peptides) and place them under:

```text
Sequential_Peptides/
```

Expected files:

```text
collection_of_peptide_data.csv
train_seqs.csv
valid_seqs.csv
test_seqs.csv
```

### 11.3 Run the Notebooks

Run the notebooks in the following order:

```text
01_data_exploration.ipynb
02_classical_baselines.ipynb
03_neural_networks.ipynb
04_error_analysis.ipynb
05_interpretability_mutation_scan.ipynb
```

The public repository includes summary result files and figures for review. However, the raw dataset and trained model checkpoint are not included.

To fully reproduce the analysis:

1. Prepare the dataset under `Sequential_Peptides/`.
2. Run `01_data_exploration.ipynb`.
3. Run `02_classical_baselines.ipynb`.
4. Run `03_neural_networks.ipynb`, which will generate:

```text
results/best_transformer_model.pt
results/test_predictions_all_models.csv
```

5. Run `04_error_analysis.ipynb`, which uses the saved test predictions.
6. Run `05_interpretability_mutation_scan.ipynb`, which loads the trained Transformer checkpoint.

For reproducibility, restart the kernel and run all cells in each notebook.

---

## 12. Limitations

This project has several limitations:

1. The models are trained on CGMD-derived AP labels rather than direct experimental measurements.
2. The project focuses on sequence-based prediction and does not include graph-based molecular representations.
3. The Transformer was trained using one main random seed; multi-seed evaluation could make the results more statistically robust.
4. The mutation scanning analysis explains model behavior but does not directly prove experimental causality.
5. The project predicts aggregation propensity, but AP alone does not fully determine final self-assembled morphology.

---

## 13. Future Work

Possible extensions include:

1. Multi-seed training and evaluation for more robust performance estimates.
2. Integrated Gradients or other gradient-based attribution methods.
3. Graph neural networks such as GCN, GAT, and GraphSAGE.
4. Sequence-graph co-modeling methods inspired by recent peptide representation learning studies.
5. Candidate screening for high-AP or tunable-AP peptide sequences.
6. Experimental validation or collaboration with wet-lab researchers.

---

## 14. References

This project is inspired by recent work on AI-assisted peptide self-assembly prediction, peptide sequence/graph representation learning, and interpretable peptide property prediction.

Key references include:

1. Wang et al. Deep Learning Empowers the Discovery of Self-Assembling Peptides with Over 10 Trillion Sequences. Advanced Science, 2023. DOI: 10.1002/advs.202301544.

2. Liu et al. Efficient prediction of peptide self-assembly through sequential and graphical encoding. Briefings in Bioinformatics, 2023. DOI: 10.1093/bib/bbad409.

3. Liu et al. Integrating sequence and chemical insights: a co-modeling AI prediction framework for peptides. Journal of Materials Informatics, 2025. DOI: 10.20517/jmi.2024.91.

---

## 15. Project Status

This project is a preliminary but complete reproduction-and-extension mini project. It demonstrates the full workflow of data exploration, baseline modeling, neural-network training, test-set error analysis, and model interpretability for peptide aggregation propensity prediction.

