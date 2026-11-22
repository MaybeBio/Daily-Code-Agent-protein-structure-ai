# rf3 CLI

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rf3/README.md](models/rf3/README.md)
- [models/rf3/configs/experiment/pretrained/rf3.yaml](models/rf3/configs/experiment/pretrained/rf3.yaml)
- [models/rf3/docs/examples/3en2_from_file.cif](models/rf3/docs/examples/3en2_from_file.cif)
- [models/rf3/docs/examples/3en2_from_json_with_msa.json](models/rf3/docs/examples/3en2_from_json_with_msa.json)
- [models/rf3/docs/examples/5hkn_from_file.cif](models/rf3/docs/examples/5hkn_from_file.cif)
- [models/rf3/docs/examples/7o1r_from_json.json](models/rf3/docs/examples/7o1r_from_json.json)
- [models/rf3/docs/examples/7xli_template_antigen_and_framework.json](models/rf3/docs/examples/7xli_template_antigen_and_framework.json)
- [models/rf3/docs/examples/9dfn.cif](models/rf3/docs/examples/9dfn.cif)
- [models/rf3/docs/examples/9dfn_template_ligand_and_protein.json](models/rf3/docs/examples/9dfn_template_ligand_and_protein.json)
- [models/rf3/docs/examples/ligands/HEM.sdf](models/rf3/docs/examples/ligands/HEM.sdf)
- [models/rf3/docs/examples/ligands/NAG.cif](models/rf3/docs/examples/ligands/NAG.cif)
- [models/rf3/src/rf3/callbacks/dump_validation_structures.py](models/rf3/src/rf3/callbacks/dump_validation_structures.py)
- [models/rf3/src/rf3/cli.py](models/rf3/src/rf3/cli.py)
- [models/rf3/src/rf3/utils/io.py](models/rf3/src/rf3/utils/io.py)
- [models/rfd3/src/rfd3/cli.py](models/rfd3/src/rfd3/cli.py)
- [pyproject.toml](pyproject.toml)

</details>



The `rf3` CLI provides command-line access to RosettaFold3 structure prediction capabilities. It supports folding proteins, nucleic acids, small molecules, and their complexes from sequence, MSA, and optional template information.

For general RosettaFold3 concepts and capabilities, see [RF3 Overview](#5.1). For programmatic access to the inference engine, see [RF3 Inference](#5.2). For checkpoint management, see [Checkpoint Management](#8.1).

---

## Command Structure

The `rf3` CLI provides two equivalent commands for running structure prediction:

```bash
rf3 fold [OPTIONS] [HYDRA_OVERRIDES...]
rf3 predict [OPTIONS] [HYDRA_OVERRIDES...]  # Alias for fold
```

Both commands accept the same arguments and options. The `predict` command exists as a convenience alias.

**Sources:** [models/rf3/src/rf3/cli.py:9-17](), [models/rf3/src/rf3/cli.py:72-82]()

---

## Command Entry Points

```mermaid
graph TB
    User["User Shell Command"]
    PyProject["pyproject.toml<br/>Entry Point Definition"]
    CLI["rf3.cli:app<br/>Typer Application"]
    Fold["fold() command"]
    Predict["predict() command"]
    HydraInit["initialize_config_dir()"]
    Compose["compose()"]
    InferenceScript["rf3.inference:run_inference()"]
    
    User -->|"rf3 fold"| PyProject
    User -->|"rf3 predict"| PyProject
    PyProject --> CLI
    CLI --> Fold
    CLI --> Predict
    Predict -.->|"Alias"| Fold
    Fold --> HydraInit
    HydraInit --> Compose
    Compose --> InferenceScript
    
    subgraph "Logic Layer"
    InferenceScript
    end
    
    style CLI fill:#f9f9f9
```

The `rf3` command is registered as a console script entry point in `pyproject.toml`, which routes to the Typer application defined in `rf3.cli`. The `fold` command initializes Hydra configuration, composes the final config with overrides, and delegates to the main inference script.

**Sources:** [pyproject.toml:90](), [models/rf3/src/rf3/cli.py:6-17](), [models/rf3/src/rf3/cli.py:64-69]()

---

## Basic Usage

### Simple Input File

The most basic usage accepts a single input file path (JSON or CIF):

```bash
rf3 fold input.json
```

The CLI automatically detects single positional arguments without `=` and treats them as the `inputs` parameter by prepending `inputs=`.

**Sources:** [models/rf3/src/rf3/cli.py:46-48](), [models/rf3/README.md:65-67]()

### Multiple Inputs

To predict multiple structures, pass a list of files using Hydra syntax:

```bash
# Multiple files with Hydra list syntax
rf3 fold inputs='[file1.json,file2.json]'
```

### Output Directory

Specify where predictions should be saved:

```bash
rf3 fold inputs='input.json' out_dir='/path/to/output'
```

**Sources:** [models/rf3/README.md:66](), [models/rf3/src/rf3/cli.py:46-51]()

---

## Configuration System

The RF3 CLI uses Hydra for hierarchical configuration management. All parameters can be specified as command-line overrides using `key=value` syntax.

```mermaid
graph TB
    ConfigDir["models/rf3/configs/"]
    InferenceYAML["inference.yaml<br/>Top-level config"]
    EngineYAML["inference_engine/rf3.yaml<br/>Engine parameters"]
    
    CLI["CLI Overrides<br/>key=value pairs"]
    HydraCompose["Hydra compose()"]
    FinalConfig["Final DictConfig"]
    
    ConfigDir --> InferenceYAML
    InferenceYAML --> HydraCompose
    EngineYAML --> HydraCompose
    CLI --> HydraCompose
    
    HydraCompose --> FinalConfig
    FinalConfig --> RunInference["rf3.inference:run_inference(cfg)"]
    
    style FinalConfig fill:#f9f9f9
```

Configuration merges in this order (later values override earlier):
1. Default `inference.yaml`
2. `inference_engine=rf3` (automatically added if not specified)
3. Command-line overrides

**Sources:** [models/rf3/src/rf3/cli.py:53-59](), [models/rf3/src/rf3/cli.py:64-65]()

---

## Common Parameters

### Model and Sampling Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ckpt_path` | str | `null` | Path to model checkpoint (.ckpt or .pt) |
| `n_recycles` | int | `10` | Number of structure recycling iterations |
| `diffusion_batch_size` | int | `1` | Number of samples to generate per input |
| `num_steps` | int | `50` | Number of diffusion denoising steps |

**Sources:** [models/rf3/README.md:69-71](), [models/rf3/configs/experiment/pretrained/rf3.yaml:1-10]()

### Quality and Resource Control

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `early_stopping_plddt_threshold` | float | `null` | Stop early if pLDDT is below this threshold |
| `raise_if_missing_msa_for_protein_of_length_n` | int | `null` | Error if proteins >= N residues lack MSAs |
| `verbose` | bool | `false` | Enable detailed logging |

**Sources:** [models/rf3/README.md:137-141](), [models/rf3/src/rf3/cli.py:14-16]()

---

## Usage Examples

### Folding with MSA (JSON Input)

Create a JSON file specifying sequences and MSA paths:

```json
{
    "name": "example_with_msa",
    "components": [
        {
            "seq": "AINRLQL...",
            "msa_path": "/path/to/msa.a3m",
            "chain_id": "A"
        }
    ]
}
```

Run with:
```bash
rf3 fold inputs='example.json' out_dir='./output'
```

**Sources:** [models/rf3/README.md:98-114](), [models/rf3/docs/examples/3en2_from_json_with_msa.json:1-15]()

### Folding with Templates

Specify template CIF files and selection strings:

```json
{
    "name": "template_example",
    "components": [
        { "path": "antigen.cif" },
        { "path": "antibody.cif" }
    ],
    "template_selection": ["A", "B/*/1-42"]
}
```

**Sources:** [models/rf3/docs/examples/7xli_template_antigen_and_framework.json:1-14]()

### Ligand and Bond Specification

Specify small molecules via CCD code, SMILES, or file paths, and define covalent bonds:

```json
{
    "name": "ligand_complex",
    "components": [
        { "seq": "MKSL...", "chain_id": "A" },
        { "ccd_code": "MG" },
        { "path": "ligand.sdf" },
        { "smiles": "[nH]1cc[nH+]c1" }
    ],
    "bonds": [
        ["A/ASN/133/ND2", "F/NAG/1/C1"]
    ]
}
```

**Sources:** [models/rf3/docs/examples/7o1r_from_json.json:1-32]()

---

## Output Files

Upon successful execution, the following files are generated in the `out_dir`:

| File | Description |
|------|-------------|
| `*_confidences.csv` | Overall confidence metrics (pLDDT, pTM, etc.) |
| `*_ranking_scores.csv` | Granular confidence metrics for all generated folds |
| `*_model.cif` | Structure file for the highest-ranked sample |
| `*_summary_confidences.json` | Additional metadata for the top-scoring fold |
| `seed-0_sample-n/` | Directories containing structure and score files for other samples |

**Sources:** [models/rf3/README.md:80-86]()

---

## Verbose Mode

Enable detailed logging to see configuration trees and internal execution steps:

```bash
rf3 fold inputs='input.json' --verbose
```

By default, the CLI uses a minimal logging configuration to reduce noise.

**Sources:** [models/rf3/src/rf3/cli.py:19-23](), [models/rf3/src/rf3/cli.py:61-62]()

---