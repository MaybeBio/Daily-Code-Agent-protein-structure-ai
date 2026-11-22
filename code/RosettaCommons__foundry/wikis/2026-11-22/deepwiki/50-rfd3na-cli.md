# rfd3na CLI

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rf3/configs/experiment/pretrained/rf3.yaml](models/rf3/configs/experiment/pretrained/rf3.yaml)
- [models/rf3/src/rf3/callbacks/dump_validation_structures.py](models/rf3/src/rf3/callbacks/dump_validation_structures.py)
- [models/rf3/src/rf3/cli.py](models/rf3/src/rf3/cli.py)
- [models/rf3/src/rf3/utils/io.py](models/rf3/src/rf3/utils/io.py)
- [models/rfd3/docs/examples/na_binder_design.md](models/rfd3/docs/examples/na_binder_design.md)
- [models/rfd3/src/rfd3/cli.py](models/rfd3/src/rfd3/cli.py)
- [pyproject.toml](pyproject.toml)

</details>



The `rfd3na` CLI provides the primary interface for running RosettaFold3-Diffusion Nucleic Acid (RFD3NA) design tasks. It extends the capabilities of the standard `rfd3` tool to support multipolymer design, specifically enabling the generation of protein backbones in the presence of or in complex with DNA and RNA chains.

## Purpose and Scope

The `rfd3na` command is used to invoke the RFD3NA inference engine. It handles the parsing of complex design specifications, including nucleic acid chain definitions, and manages the diffusion sampling process to produce all-atom structures of protein-nucleic acid complexes.

Key features accessible via the CLI include:
*   **Multipolymer Design**: Support for protein, DNA, and RNA chains within a single design task.
*   **Nucleic Acid Specification**: Detailed control over fixed vs. diffused nucleic acid atoms.
*   **Sequence Integration**: Ability to read nucleic acid sequences directly from input headers.
*   **Hydra-based Configuration**: Full access to model hyperparameters and inference settings via command-line overrides.

Sources: [models/rfd3na/src/rfd3na/cli.py:12-43](), [pyproject.toml:92-92]()

## CLI Command: design

The `design` command is the main entry point for running inference. It uses the `typer` library to manage the command-line interface and `hydra` for configuration management.

### Usage Syntax
```bash
rfd3na design [HYDRA_OVERRIDES]
```

### Parameters and Overrides

| Parameter | Description |
| :--- | :--- |
| `inputs` | Path to a JSON file containing the design specifications (contigs, lengths, etc.). |
| `out_dir` | Directory where the generated structures and trajectories will be saved. |
| `ckpt_path` | Path to the RFD3NA model checkpoint file. |
| `inference_engine` | Defaults to `rfdiffusion3na`. Determines the inference logic used. |
| `read_sequence_from_sequence_head` | Boolean flag to determine if nucleic acid sequences should be parsed from the PDB file headers. |

Sources: [models/rfd3na/src/rfd3na/cli.py:12-36](), [models/rfd3/docs/examples/na_binder_design.md:5-8]()

## System Architecture and Data Flow

The `rfd3na` CLI acts as a wrapper that initializes the environment, composes the configuration, and executes the `run_inference` function.

### Natural Language to Code Entity Space: CLI Execution
The following diagram maps the CLI command components to their respective code entities and configuration paths.

Title: rfd3na CLI Execution Mapping
```mermaid
graph TD
    subgraph "CLI Command Space"
        CMD["rfd3na design"]
        ARGS["inputs=design.json out_dir=./outputs"]
    end

    subgraph "Code Entity Space"
        CLI_APP["models/rfd3na/src/rfd3na/cli.py: app"]
        DESIGN_FUNC["models/rfd3na/src/rfd3na/cli.py: design()"]
        RUN_INF["models/rfd3na/src/rfd3na/run_inference.py: run_inference()"]
    end

    subgraph "Configuration Space"
        CONFIG_DIR["models/rfd3na/configs/"]
        INF_YAML["inference.yaml"]
    end

    CMD --> CLI_APP
    CLI_APP --> DESIGN_FUNC
    ARGS --> DESIGN_FUNC
    DESIGN_FUNC -- "compose(config_name='inference')" --> INF_YAML
    INF_YAML -- "Path" --> CONFIG_DIR
    DESIGN_FUNC -- "calls" --> RUN_INF
```
Sources: [models/rfd3na/src/rfd3na/cli.py:6-43](), [pyproject.toml:92-92](), [models/rfd3/src/rfd3/cli.py:12-69]()

## Implementation Details

### Configuration Initialization
The CLI identifies the configuration directory based on the execution environment (development vs. installed package). It uses `initialize_config_dir` from Hydra to load the base `inference.yaml` and applies user-provided overrides.

### Inference Execution Flow
Once the configuration is composed, the CLI performs a lazy import of `run_inference`. This prevents heavy dependencies (like PyTorch and AtomWorks) from loading during basic CLI help or argument parsing, improving responsiveness.

Title: RFD3NA Inference Data Flow
```mermaid
sequenceDiagram
    participant User as CLI User
    participant CLI as rfd3na/cli.py
    participant Hydra as Hydra Config
    participant Engine as run_inference()
    
    User->>CLI: rfd3na design inputs=spec.json
    CLI->>Hydra: initialize_config_dir(config_path)
    Hydra-->>CLI: cfg object
    CLI->>Engine: run_inference(cfg)
    Note over Engine: Load Checkpoint
    Note over Engine: Parse DesignInputSpecification
    Note over Engine: Diffusion Sampling
    Engine-->>User: Output .cif files
```
Sources: [models/rfd3na/src/rfd3na/cli.py:18-43](), [models/rfd3/src/rfd3/cli.py:12-69]()

## Nucleic Acid Specific Configurations

When using the `rfd3na` CLI, specific parameters in the `inputs` JSON or as Hydra overrides are critical for nucleic acid handling:

1.  **Contig Specification**: Nucleic acid chains must be explicitly defined in the contig string (e.g., `A1-10` for a DNA strand).
2.  **Fixed Atom Selection**: The `select_fixed_atoms` parameter allows users to specify which parts of the nucleic acid should remain static and which should be sampled by the model.
3.  **Sequence Handling**: If `read_sequence_from_sequence_head` is enabled, the model will attempt to extract the specific nucleotide sequence from the input PDB/CIF file to inform the design.

### Example CLI Command with Overrides
```bash
rfd3na design \
    inputs=./my_dna_protein_complex.json \
    out_dir=./results \
    inference_engine.read_sequence_from_sequence_head=True \
    inference_engine.sampling.num_steps=50
```

Sources: [models/rfd3/docs/examples/na_binder_design.md:23-37](), [models/rfd3/docs/examples/na_binder_design.md:57-68]()

---