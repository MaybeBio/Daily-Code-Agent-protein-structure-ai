# Structural Alphabets and Prediction (3Di)

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [csubst/output_safety.py](csubst/output_safety.py)
- [csubst/resource_cache.py](csubst/resource_cache.py)
- [csubst/structural_alphabet.py](csubst/structural_alphabet.py)
- [csubst/structural_observation.py](csubst/structural_observation.py)
- [csubst/structural_prediction.py](csubst/structural_prediction.py)
- [csubst/structural_reference.py](csubst/structural_reference.py)
- [csubst/structural_validation.py](csubst/structural_validation.py)
- [csubst/vesm.py](csubst/vesm.py)
- [docs/STRUCTURAL_OBSERVATION.md](docs/STRUCTURAL_OBSERVATION.md)
- [docs/STRUCTURAL_VALIDATION.md](docs/STRUCTURAL_VALIDATION.md)
- [reports/3di_pilot_20260910/README.md](reports/3di_pilot_20260910/README.md)
- [reports/3di_pilot_20260910/comparison.json](reports/3di_pilot_20260910/comparison.json)
- [reports/3di_pilot_20260910/esm3di-35m/manifest.json](reports/3di_pilot_20260910/esm3di-35m/manifest.json)
- [tests/unit/test_3di_state_cache.py](tests/unit/test_3di_state_cache.py)
- [tests/unit/test_structural_prediction.py](tests/unit/test_structural_prediction.py)
- [tests/unit/test_vesm.py](tests/unit/test_vesm.py)

</details>



## Purpose and Scope

This leaf page details the implementation of structural alphabets (Foldseek 3Di and MORPH numerical encodings), neural prediction backends (`prostt5`, `prostt5-cnn`, and `esm3di-35m`), caching layers, and the experimental validation, reference extraction, and fixed-GTR observation modules. These components enable mapping protein amino acid sequences to structural states, scoring confidence via language models, and performing structural observation modeling without modifying the core phylogenetic combinatorial substitution search algorithms.

Sources: `csubst/structural_alphabet.py:1-35()`, `csubst/structural_prediction.py:1-40()`, `csubst/structural_validation.py:1-24()`

---

## 1. Structural Alphabets and ASCII Mapping (`csubst/structural_alphabet.py`)

The codebase defines 20-state structural alphabets derived from Foldseek 3Di structural states (`ACDEFGHIKLMNPQRSTVWY`) and maps them to numerical MORPH indices (`0123456789ABCDEFGHIJ`) for downstream tensor operations.

### State Orders and ASCII Conversion
- `_THREEDI_STATE_ORDERS`: NumPy object array containing the canonical 20 3Di state characters `[csubst/structural_alphabet.py:18-18]()`.
- `_MORPH_STATE_ORDERS`: NumPy object array containing the 20 MORPH symbols `[csubst/structural_alphabet.py:20-20]()`.
- `_to_ascii_matrix()`: Validates that aligned sequences have equal length and converts sequence strings into `np.uint8` ASCII byte matrices `[csubst/structural_alphabet.py:45-65]()`.
- `is_3di_recode()`: Inspects configuration dictionaries to determine if `nonsyn_recode` is set to `3di20` `[csubst/structural_alphabet.py:33-35]()`.

```mermaid
graph TD
    A["AlignedSequences"] --> B[_to_ascii_matrix]
    B --> C["Uint8ASCIIArray"]
    C --> D["predict_3di"]
    D --> E["MorphConversion"]
    E --> F["_convert_3di_symbol_to_morph"]

    sub-sections:
    Sources: csubst/structural_alphabet.py:18-65()
```

Sources: `csubst/structural_alphabet.py:18-65()`

---

## 2. Neural Prediction Backends and Dispatch (`csubst/structural_prediction.py`)

Structural prediction supports multiple neural network backends governed by configuration options and managed resource caches.

### Backend Identification and Checkpoint Resolution
- `get_model_cache_key()`: Inspects `sa_backend` and computes cache keys incorporating CNN or LoRA checkpoint SHA-256 hashes `[csubst/structural_prediction.py:42-50]()`.
- `ensure_encoder_resource()`: Atomically prepares, downloads (if permitted), and verifies required model weights and configuration files for `prostt5-cnn` and `esm3di-35m` backends against expected SHA-256 digests `[csubst/structural_prediction.py:51-105]()`.
- `EncoderPredictor`: Class managing the PyTorch tokenizer, backbone model, device placement (`cpu`, `cuda`, `mps`), and batch inference `[csubst/structural_prediction.py:120-135]()`. Residue-budget batching prevents out-of-memory (OOM) errors by splitting long sequence batches dynamically.

```mermaid
graph TD
    A["UserConfig sa_backend"] --> B[get_model_cache_key]
    B --> C[ensure_encoder_resource]
    C --> D["EncoderPredictor"]
    D --> E["predict_batch"]
    E --> F["TorchModelForward"]

    sub-sections:
    Sources: csubst/structural_prediction.py:42-154()
```

Sources: `csubst/structural_prediction.py:42-154()`

---

## 3. Caching, Output Safety, and Validation (`csubst/structural_validation.py`)

Prediction artifacts and intermediate states are isolated from raw inputs using atomic writes and strict schema validations.

### Prediction Records and Serialization
- `PredictionRecord`: Immutable dataclass holding gapless amino acid sequences, predicted 3Di states, model keys, and residue-by-state logit arrays `[csubst/structural_validation.py:30-45]()`.
- `save_predictions()`: Atomically serializes prediction records and metadata into compressed `.npz` archives using temporary file staging and hard-link publication `[csubst/structural_validation.py:95-127]()`.
- `load_predictions()`: Reads and validates prediction archives against expected schema versions (`SCHEMA_VERSION = 1`) and state order specifications `[csubst/structural_validation.py:129-149]()`.

```mermaid
graph TD
    A["PredictionRecords"] --> B[save_predictions]
    B --> C["NamedTemporaryFile.npz"]
    C --> D["os.link Atomic Publication"]
    D --> E[load_predictions]
    E --> F["JSON Metadata & Array Validation"]

    sub-sections:
    Sources: csubst/structural_validation.py:30-149()
```

Sources: `csubst/structural_validation.py:30-149()`

---

## 4. Experimental References and Fixed-GTR Observation (`csubst/structural_reference.py`, `structural_observation.py`)

The structural observation pipeline bridges experimental PDB/CIF structures with phylogenetic likelihood calculations.

### Reference Extraction and Observation Likelihoods
- **Foldseek Integration**: Extracts 3Di reference alphabets from experimental structures using pinned Foldseek releases with conservative structural masking (excluding missing backbone atoms, non-consecutive polymer breaks, and unobserved partner neighborhoods) `[docs/STRUCTURAL_OBSERVATION.md:10-75]()`.
- `observation_likelihoods()`: Maps observed character indices (with `-1` for missing data) to conditional probabilities $P(\text{observed} \mid \text{true})$ based on confusion matrices `[docs/STRUCTURAL_OBSERVATION.md:99-105]()`.
- `fixed_gtr_posteriors()`: Computes node marginals and parent-child endpoint joints using log-space pruning and outside recursions under a fixed, reversible rate matrix $Q$ and stationary frequencies $\pi$ `[docs/STRUCTURAL_OBSERVATION.md:105-115]()`.

```mermaid
graph TD
    A["ExperimentalCIF / PDB"] --> B[FoldseekExtractor]
    B --> C["ConservativeMasking"]
    C --> D[structural_observation.observation_likelihoods]
    D --> E[fixed_gtr_posteriors]
    E --> F["NodeMarginals & EndpointJoints"]

    sub-sections:
    Sources: docs/STRUCTURAL_OBSERVATION.md:10-115()
```

Sources: `docs/STRUCTURAL_OBSERVATION.md:10-115()`

---