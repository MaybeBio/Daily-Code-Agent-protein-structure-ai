# Subcommands and Argument Parsing

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Makefile](Makefile)
- [csubst/cli.py](csubst/cli.py)
- [csubst/cli_io.py](csubst/cli_io.py)
- [csubst/config_types.py](csubst/config_types.py)
- [csubst/main_dataset.py](csubst/main_dataset.py)
- [csubst/main_doctor.py](csubst/main_doctor.py)
- [csubst/main_download.py](csubst/main_download.py)
- [csubst/main_inspect.py](csubst/main_inspect.py)
- [csubst/output_run.py](csubst/output_run.py)
- [docs/CLI_SAFETY.md](docs/CLI_SAFETY.md)
- [tests/cli/test_cli_logging.py](tests/cli/test_cli_logging.py)
- [tests/cli/test_cli_validation.py](tests/cli/test_cli_validation.py)
- [tests/cli/test_output_lifecycle.py](tests/cli/test_output_lifecycle.py)
- [tests/integration/test_foreground_targets.py](tests/integration/test_foreground_targets.py)
- [tests/integration/test_main_dataset.py](tests/integration/test_main_dataset.py)
- [tests/integration/test_resource_cache.py](tests/integration/test_resource_cache.py)
- [tests/parity/test_expected_sparse.py](tests/parity/test_expected_sparse.py)
- [tests/parity/test_omega_expected_state.py](tests/parity/test_omega_expected_state.py)
- [tests/parity/test_omega_expected_state_parity.py](tests/parity/test_omega_expected_state_parity.py)
- [tests/unit/test_main_download.py](tests/unit/test_main_download.py)
- [tests/unit/test_simulate_core.py](tests/unit/test_simulate_core.py)
- [tests/unit/test_substitution_dense_tensor.py](tests/unit/test_substitution_dense_tensor.py)

</details>



This page covers the technical architecture of the `csubst` command-line interface (CLI) argument parsing engine, subcommand routing, preflight I/O safety checks, and the typed configuration contracts. It details how the entrypoint parses command-line arguments, validates destinations via preflight hooks, and dispatches execution to downstream module entrypoints (`main_*`).

---

## Parser Construction and Option Groups

The command-line interface is initialized in `csubst/cli.py`, where `_build_parser()` constructs the top-level `argparse.ArgumentParser` along with sub-parsers for each subcommand [csubst/cli.py:1](). 

Shared option groups—such as output namespaces (`--outdir`, `--output_prefix`, `--log_file`)—are injected across subcommands using helper utilities like `_add_output_namespace_args()` and `_make_output_parent_parser()` [csubst/cli.py:151-180](). The CLI also supports advanced arguments hidden by default unless `--help-advanced` is invoked, which is normalized via `_normalize_help_argv()` [csubst/cli.py:55-66]().

```mermaid
graph TD
    A["CLI Entrypoint sys.argv"] --> B["_normalize_help_argv"]
    B --> C["_build_parser"]
    C --> D["argparse.ArgumentParser"]
    D --> E["Shared Output Groups _add_output_namespace_args"]
    D --> F["Sub-parsers Action"]
    
    Sources: "csubst/cli.py:55-180"
```

Sources: `csubst/cli.py:55-180`

---

## Subcommand Dispatchers and Module Routing

When an execution request matches a subcommand, `csubst` maps the parsed namespace attributes to specific functional execution handlers (`main_*` dispatchers). The table below lists the subcommands and their respective handler modules:

| Subcommand | Handler Module & Function | Primary Purpose |
| :--- | :--- | :--- |
| `search` / `analyze` | `csubst.main_analyze` | Combinatorial substitution search and omega calculation |
| `scan` | `csubst.main_scan` | Recurrent substitution scanning in foreground lineages |
| `sites` | `csubst.main_sites` | Site-level analysis, structural annotation, and tree plotting |
| `simulate` | `csubst.main_simulate` | Sequence and substitution tree simulation |
| `dataset` | `csubst.main_dataset:main_dataset` | Bundling and unpacking example datasets (e.g., PGK, PEPC) |
| `download` | `csubst.main_download:main_download` | Model resource caching (VESM-35M, ProstT5, ESM-3Di) |
| `doctor` | `csubst.main_doctor` | Environment and input file diagnostics |
| `inspect` | `csubst.main_inspect` | Data inspection, state plotting, and branch combinatorics |
| `benchmark` | `csubst.main_benchmark` | Performance benchmarking and parameter grid searching |

The mapping from natural language subcommands to code entities is illustrated below:

```mermaid
graph TD
    subnames["Subcommand Name Space"]
    subnames -->|"analyze / search"| analyze["csubst/main_analyze.py"]
    subnames -->|"scan"| scan["csubst/main_scan.py"]
    subnames -->|"sites"| sites["csubst/main_sites.py"]
    subnames -->|"simulate"| simulate["csubst/main_simulate.py"]
    subnames -->|"dataset"| dataset["csubst/main_dataset.py:main_dataset"]
    subnames -->|"download"| download["csubst/main_download.py:main_download"]
    subnames -->|"doctor"| doctor["csubst/main_doctor.py"]
    subnames -->|"inspect"| inspect["csubst/main_inspect.py"]
    subnames -->|"benchmark"| benchmark["csubst/main_benchmark.py"]

    Sources: "csubst/main_dataset.py:146-155", "csubst/main_download.py:17-68", "csubst/main_inspect.py:1-190"
```

Sources: `csubst/main_dataset.py:146-155`, `csubst/main_download.py:17-68`, `csubst/main_inspect.py:1-190`

---

## Preflight I/O Safety and Argument Validation

Before any numerical libraries or model weights are loaded, `csubst` performs preflight checks via `csubst/cli_io.py` to prevent output streams (such as `--log_file`) from overwriting valid inputs or existing critical outputs [csubst/cli_io.py:1-98]().

The `input_paths()` function dynamically traverses parser actions and raw `argv` tokens to identify every supplied and inferred input file path [csubst/cli_io.py:20-91](). `validate_log_destination()` and `validate_output_destinations()` then enforce safety invariants, raising a `ValueError` (exiting with code 2) if an input/log collision or unsafe symlink redirection is detected [csubst/cli_io.py:93-125](), [docs/CLI_SAFETY.md:1-22]().

```mermaid
graph TD
    A["Parsed Arguments & argv"] --> B["cli_io.input_paths"]
    B --> C["cli_io.validate_log_destination"]
    B --> D["cli_io.validate_output_destinations"]
    C -->|"Collision detected"| E["Raise ValueError / Exit 2"]
    D -->|"Collision detected"| E
    C -->|"Safe"| F["Proceed to Subcommand Execution"]
    D -->|"Safe"| F

    Sources: "csubst/cli_io.py:20-125", "docs/CLI_SAFETY.md:1-22"
```

Sources: `csubst/cli_io.py:20-125`, `docs/CLI_SAFETY.md:1-22`

---

## Typed Configuration Contracts (`AnalysisConfig`)

Subcommand dispatchers receive configuration parameters packaged into typed dictionary structures defined in `csubst/config_types.py` [csubst/config_types.py:1-158](). 

The master `AnalysisConfig` inherits from several categorized `TypedDict` definitions to separate concerns across pipeline stages:
* `InputConfig`: Alignment files, tree files, frontend traits, and model resources [csubst/config_types.py:13-32]().
* `OutputConfig`: Output directories, filename prefixes, and log paths [csubst/config_types.py:34-41]().
* `NumericConfig`: Floating-point tolerance, thread counts, and random number seeds [csubst/config_types.py:43-54]().
* `ModelConfig`: Substitution models, posterior calculation settings, and expectation methods [csubst/config_types.py:55-89]().
* `ScanConfig`: Scan calibration options, permutation parameters, and CTMC precision [csubst/config_types.py:132-146]().

Sources: `csubst/config_types.py:1-158`

---