# Protein Function Predictor

Which molecular functions might a protein have? This web app takes an amino-acid sequence and ranks ten Gene Ontology molecular function terms, including ATP binding, RNA binding and DNA binding. Each result shows the model’s score, the threshold for that term and whether the score cleared it.

The model achieved **0.580 macro average precision on 289 held-out proteins**. Proteins in the same sequence-similarity cluster stayed in the same partition, reducing the chance that close relatives would make the test artificially easy.

[Try a prediction](#try-a-prediction) · [View a completed prediction](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/docs/prediction-demo.png) · [See evaluation results](#evaluation)

<a href="https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/docs/prediction-demo.png"><img src="https://github.com/kheefuiyong/protein-function-predictor/raw/HEAD/docs/prediction-demo.png" alt="The web app showing the example sequence and all ten scored predictions" width="540"></a>

## Try a prediction

Start in the root of a fresh clone. The trained classifier is included. The first launch downloads the public ESM2 weights from Hugging Face, so keep the machine online until the app starts. A CPU is sufficient.

**Set up Python.** The steps below were verified on macOS with Python 3.12.15. On macOS or Linux, create and activate a virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

On Windows with Python 3.12 installed, the equivalent PowerShell commands are:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Install and launch.** The scikit-learn version matches the one used to save the classifier.

```bash
python -m pip install . "scikit-learn==1.9.0"
python -m uvicorn protein_function_predictor.api:app --host 127.0.0.1 --port 8000
```

**Run the example.** When the terminal reports `Application startup complete`, open [the local app](http://127.0.0.1:8000). Paste the example sequence below and click **Predict function**. Leave the terminal open while using the app. Press Ctrl+C there to stop it.

```text
MRWQEMGYIFYPRKLR
```

The verification run returned ten rows. Here are the first two, rounded as shown in the browser:

| GO term | Score | Threshold | Decision |
| --- | ---: | ---: | --- |
| GO:0003677 (DNA binding) | 0.632 | 0.213 | Predicted |
| GO:0003723 (RNA binding) | 0.138 | 0.391 | Not predicted |

This short input demonstrates how to read the output. A positive call means the score crossed a threshold fitted on validation data. The score is not a calibrated probability of biological function.

For programmatic use, open the [interactive API documentation](http://127.0.0.1:8000/docs) while the app is running. The browser uses the same `POST /predict` endpoint.

## How it works

1. **Define the task.** From 5,000 reviewed UniProtKB/Swiss-Prot records, the pipeline removes invalid and duplicate sequences and selects ten frequent molecular function terms. The resulting dataset contains 2,035 proteins with at least one selected annotation. A protein can have multiple labels.
2. **Represent each sequence.** The pretrained ESM2 model stays frozen. Averaging the amino-acid representations produces one 320-dimensional vector per protein.
3. **Score each function.** One logistic regression classifier per term converts the vector into ten scores. The validation set determines the regularisation setting and each term’s decision threshold.
4. **Serve the result.** FastAPI loads the saved classifier and serves both the prediction endpoint and the browser interface. The app accepts up to 1,024 standard amino acids per sequence.

## Evaluation

MMseqs2 grouped sequences by similarity before the split. The training set contained 1,452 proteins, the validation set 294 and the test set 289.

| Metric | Validation | Held-out test |
| --- | ---: | ---: |
| Macro average precision | 0.625 | **0.580** |
| Micro average precision | 0.667 | 0.622 |
| Macro F1 | 0.622 | 0.570 |
| Micro F1 | 0.614 | 0.555 |

Macro average precision gives each function equal weight. A classifier that assigned every protein the same score within each function would obtain **0.155** on this test set. Performance varied by function: test average precision was 0.910 for ATP binding, 0.598 for RNA binding and 0.279 for DNA binding.

The benchmark covers proteins with at least one of the ten selected annotations. Performance on proteins outside that group is unknown. Gene Ontology annotations can be incomplete, and experimental evidence is needed to confirm a predicted function.

## Explore the repository

| Question | Where to look |
| --- | --- |
| How were the task and labels defined? | [ML task](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/docs/ml_task.md) |
| How were related proteins grouped? | [Clustering script](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/scripts/cluster_sequences.sh) and [split assignment](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/src/protein_function_predictor/splitting.py) |
| How was the classifier chosen and tested? | [Model selection](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/docs/model_selection.md) and [held-out evaluation](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/docs/baseline_evaluation.md) |
| How does a sequence reach the browser as a prediction? | [Inference](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/src/protein_function_predictor/inference.py), [API](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/src/protein_function_predictor/api.py) and [browser interface](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/src/protein_function_predictor/static) |
| Where are the checks and packaging? | [Automated tests](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/tests) and [Dockerfile](https://github.com/kheefuiyong/protein-function-predictor/blob/HEAD/Dockerfile) |
