# Protein Dynamics Deep Learning Project

This repository implements a **fully reproducible end-to-end deep learning pipeline** for modeling protein dynamics from Molecular Dynamics (MD) trajectories.

The task is formulated as a **time-series prediction problem**, where a model observes a fixed-length window of past molecular states and predicts the **next full molecular state** (coordinates, velocities, and forces).

The project compares three architectures:

* **RNN**
* **LSTM**
* **Transformer**

---

## 1. Problem Formulation

At each timestep, the molecular state consists of:

* **Atomic coordinates**
* **Atomic velocities**
* **Atomic forces**

Each state is flattened into a single feature vector.

Given a sliding window of past states:
[
X_t = [x_{t-W+1}, \dots, x_t]
]

the model predicts the next state:
[
y_{t+1}
]

All final experiments **include forces in both input and target**.

---

## 2. Repository Structure

```
protein_dynamics_project/
├─ data/
│  └─ raw/
│     ├─ coordinates.csv
│     ├─ velocity.csv
│     └─ forces.csv
├─ processed/
│  ├─ aligned/                     # Step 01 outputs
│  ├─ windows_w{W}/                # Step 02 windows
│  ├─ splits/                      # Step 03 indices
│  ├─ windows_w{W}_norm/           # Step 04 normalized data
│  ├─ models/                      # saved models
│  ├─ results_rnn/
│  ├─ results_lstm/
│  ├─ results_transformer/
│  └─ reports/                     # Step 07 evaluation outputs
├─ src/
│  ├─ 01_preprocessing.py
│  ├─ 02_make_windows.py
│  ├─ 03_train_val_split.py
│  ├─ 04_normalize_windows.py
│  ├─ 05_train_rnn.py
│  ├─ 05_train_lstm.py
│  ├─ 06_train_transformer.py
│  ├─ 07_evaluate_norm_models.py
│  └─ plot_learning_curve.py
├─ project_root.py
├─ run_all_local.ipynb
├─ run_all_google_colab.ipynb
└─ run_all_kaggle_only.ipynb
```

---

## 3. Requirements

* Python **3.9+**
* Required libraries:

  * `numpy`
  * `pandas`
  * `tensorflow`

Optional: GPU for faster training.

---

## 4. Pipeline Overview (01 → 07)

> **Important:** Scripts must be executed in order.

---

### Step 01 — Preprocessing & Alignment

* Reads raw CSV files (robust to delimiters)
* Aligns coordinates, velocities, and forces by timestep
* Infers number of atoms automatically
* Reshapes to `(T, n_atoms, 3)`

Outputs:

```
processed/aligned/
├─ coords_aligned.npy
├─ vels_aligned.npy
└─ forces_aligned.npy
```

Run:

```bash
python src/01_preprocessing.py
```

---

### Step 02 — Sliding Window Generation

Creates supervised samples using a sliding window of size `W`.

* **Input dimension**:
  `Dx = 1242` (coords + vels + forces)
* **Target dimension**:
  `Dy = 1242`

Outputs:

```
processed/windows_w{W}/
├─ X.npy
├─ y.npy
└─ meta.npy
```

Run:

```bash
python src/02_make_windows.py --window 10 --include_forces_in_input true
```

---

### Step 03 — Train / Validation / Test Split

* Chronological split to prevent temporal leakage
* Default:

  * 80% train
  * 10% validation
  * 10% test

Outputs:

```
processed/splits/splits_w{W}/
├─ train_idx.npy
├─ val_idx.npy
└─ test_idx.npy
```

Run:

```bash
python src/03_train_val_split.py --window 10
```

---

### Step 04 — Train-Only Normalization

* Mean and standard deviation computed **only from training data**
* Applied consistently to validation and test sets
* Prevents data leakage

Outputs:

```
processed/windows_w{W}_norm/
├─ X.npy
├─ y.npy
└─ norm_stats.npz
```

Run:

```bash
python src/04_normalize_windows.py --window 10
```

---

### Step 05 — Model Training

Three architectures are trained using the same data and splits.

#### RNN

```bash
python src/05_train_rnn.py --window 10
```

#### LSTM

```bash
python src/05_train_lstm.py --window 10
```

#### Transformer

```bash
python src/06_train_transformer.py --window 10
```

#### Training curriculum

Each model is trained in three phases:

1. **Teacher Forcing (TF)**
   Standard supervised learning using ground-truth inputs.

2. **Masked Input Training (MASK)**
   Random feature masking acts as noise injection and regularization.

3. **Rollout Consistency Regularization**
   Encourages stable predictions when the model consumes its own output for one-step rollout.

   > This is **not classical scheduled sampling**, but a stability-oriented regularizer.

Best models are selected using **validation MSE**.

---

### Step 07 — Evaluation (De-normalized)

Evaluation is performed **only on the test set**.

Procedure:

1. Predict using normalized inputs
2. De-normalize predictions and targets
3. Compute MSE in **original physical units**

Metrics:

* Overall MSE
* Coordinate MSE
* Velocity MSE
* Force MSE

Run:

```bash
python src/07_evaluate_norm_models.py \
  --window 10 \
  --model_path processed/models/lstm_A_w10_best.keras \
  --out_name lstm_w10
```

Outputs:

```
processed/reports/
├─ lstm_w10.json
└─ lstm_w10_mse_blocks.jpg
```

---

## 5. Reproducibility

* Fixed random seeds are used in all training scripts
* Identical splits are reused across all models
* Normalization statistics are saved and reused
* The pipeline runs consistently on:

  * Local machines
  * Google Colab
  * Kaggle
Local machine: Run the pipeline by executing the Python scripts in src/ directly, or use run_all_local.ipynb for convenience.

Google Colab: Open and run run_all_google_colab.ipynb, which mounts Google Drive and executes the same src/ scripts.

Kaggle: Open and run run_all_kaggle_only.ipynb, which locates the project in /kaggle/input and runs the src/ scripts with outputs redirected to /kaggle/working.


---

## 6. Key Design Choices

* Forces are included in both **input and target**
* Normalization is **train-only**
* Evaluation is performed on **de-normalized values**
* All comparisons use the same data splits
* Models predict **next-step dynamics**
