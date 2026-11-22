# Orchestrator and Batch Campaigns

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/manifest.md](docs/manifest.md)
- [docs/studies.md](docs/studies.md)
- [src/fastmdxplora/batch/aggregate.py](src/fastmdxplora/batch/aggregate.py)
- [src/fastmdxplora/batch/compare.py](src/fastmdxplora/batch/compare.py)
- [src/fastmdxplora/batch/explorer.py](src/fastmdxplora/batch/explorer.py)
- [src/fastmdxplora/cost.py](src/fastmdxplora/cost.py)
- [src/fastmdxplora/gpu_here.py](src/fastmdxplora/gpu_here.py)
- [src/fastmdxplora/orchestrator.py](src/fastmdxplora/orchestrator.py)
- [src/fastmdxplora/runs_here.py](src/fastmdxplora/runs_here.py)
- [src/fastmdxplora/simulation/binding.py](src/fastmdxplora/simulation/binding.py)
- [src/fastmdxplora/simulation/plumed.py](src/fastmdxplora/simulation/plumed.py)
- [src/fastmdxplora/simulation/reference_state.py](src/fastmdxplora/simulation/reference_state.py)
- [src/fastmdxplora/simulation/umbrella.py](src/fastmdxplora/simulation/umbrella.py)
- [tests/test_a_binding_free_energy_carries_its_spread.py](tests/test_a_binding_free_energy_carries_its_spread.py)
- [tests/test_a_binding_free_energy_says_where_its_reference_fails.py](tests/test_a_binding_free_energy_says_where_its_reference_fails.py)
- [tests/test_a_charged_ligand_is_said.py](tests/test_a_charged_ligand_is_said.py)
- [tests/test_a_short_pilot_sizes_the_study.py](tests/test_a_short_pilot_sizes_the_study.py)
- [tests/test_a_window_can_be_held_at_its_own_constant.py](tests/test_a_window_can_be_held_at_its_own_constant.py)
- [tests/test_a_window_is_held_while_it_equilibrates.py](tests/test_a_window_is_held_while_it_equilibrates.py)
- [tests/test_an_ai_app_starts_only_what_was_checked.py](tests/test_an_ai_app_starts_only_what_was_checked.py)
- [tests/test_batch.py](tests/test_batch.py)
- [tests/test_binding.py](tests/test_binding.py)
- [tests/test_box_record_and_bias_wording.py](tests/test_box_record_and_bias_wording.py)
- [tests/test_cli.py](tests/test_cli.py)
- [tests/test_compare.py](tests/test_compare.py)
- [tests/test_density_is_not_silent.py](tests/test_density_is_not_silent.py)
- [tests/test_no_test_reads_the_source.py](tests/test_no_test_reads_the_source.py)
- [tests/test_one_card_one_line.py](tests/test_one_card_one_line.py)
- [tests/test_orchestrator.py](tests/test_orchestrator.py)
- [tests/test_studies_here_share_the_gpus.py](tests/test_studies_here_share_the_gpus.py)
- [tests/test_the_gui_and_an_ai_app_start_one_at_a_time.py](tests/test_the_gui_and_an_ai_app_start_one_at_a_time.py)
- [tests/test_umbrella.py](tests/test_umbrella.py)
- [tests/test_which_ensemble_production_runs_in.py](tests/test_which_ensemble_production_runs_in.py)

</details>



## Purpose and Scope
This page details the orchestration and batch campaign architecture of FastMDXplora. It covers the phase-based execution engine (`FastMDXplora`), data structures (`RunResult` and `PhaseResult`), parameter sweeps (`BatchExplorer`), process-level parallelization with round-robin GPU device pinning, cross-run comparison/aggregation, and local workspace resource/GPU sharing.

Sources: `src/fastmdxplora/orchestrator.py:1-174()`, `src/fastmdxplora/batch/explorer.py:1-38()`

---

## 1. Orchestrator Phases and Data Structures

FastMDXplora follows a built-in phase-based orchestration pattern rather than a generic Directed Acyclic Graph (DAG) workflow engine. The workflow consists of four canonical phases executed in a strict sequence: setup, simulation, analysis, and report (`src/fastmdxplora/orchestrator.py:56-58()`).

Each phase invocation yields a `PhaseResult` dataclass instance (`src/fastmdxplora/orchestrator.py:94-105()`), capturing:
- `name`: The phase identifier (`setup`, `simulation`, `analysis`, `report`).
- `status`: Execution outcome (`ok`, `skipped`, `error`).
- `output_dir`: Path to phase-specific outputs.
- `started_at` / `finished_at`: Timestamp string telemetry.
- `artifacts`: List of generated files relative to the phase directory.
- `refusal`: Structured refusal dictionary (`src/fastmdxplora/orchestrator.py:105-117()`).
- `produced_by`: Environment, version, and host provenance records (`src/fastmdxplora/orchestrator.py:118-131()`).

A complete study or individual sweep run is encapsulated by `RunResult` (`src/fastmdxplora/orchestrator.py:159-174()`), which aggregates the `run_id`, target system, global status, output directory, sweep parameters, and list of `phases`.

Diagram: Orchestrator Execution Flow and Data Structures
```mermaid
graph TD
    A["UserIntent / CLI"] -->|Config / Args| B["FastMDXplora (orchestrator.py)"]
    B -->|Iterate PHASES| C["Setup Phase"]
    C -->|PhaseResult| D["Simulation Phase"]
    D -->|PhaseResult| E["Analysis Phase"]
    E -->|PhaseResult| F["Report Phase"]
    F -->|Consolidate| G["RunResult (orchestrator.py)"]
    G -->|Write| H["manifest.json"]

    subcode["Code Entity Mapping"]
    PHASES["PHASES tuple (orchestrator.py:58)"]
    PhaseResultClass["PhaseResult (orchestrator.py:94)"]
    RunResultClass["RunResult (orchestrator.py:159)"]
    end
```
Sources: `src/fastmdxplora/orchestrator.py:1-174()`

---

## 2. Batch Campaigns and Sweep Expansion

FastMDXplora unifies single-run execution and parameter sweeps into a single code path via `BatchExplorer` (`src/fastmdxplora/batch/explorer.py:1-15()`). A single-system configuration is treated simply as a batch size of one (`src/fastmdxplora/batch/explorer.py:3-6()`).

### Output Layout Adaptation
The output directory layout adapts based on the run count (`src/fastmdxplora/batch/explorer.py:8-15()`):
- **Single run**: Flat layout written directly to the target output directory (`output/setup/`, `output/simulation/`, etc.), containing the root `manifest.json` and `resolved_config.yml`. No `runs/` wrapper folder is created.
- **Multiple runs / Sweeps**: Each run is placed in `output/runs/<id>/` as an isolated study directory, accompanied by a top-level `batch_manifest.json` indexing all member runs.

### Sweep Expansion
Parameter sweeps and multiple systems are normalized and expanded via `expand_runs` and `normalize_sweep` (`src/fastmdxplora/batch/explorer.py:55-60()`), generating a list of immutable `RunSpec` objects that resolve configuration inheritance (`base < per-system < sweep`).

Diagram: Batch Explorer Execution Path
```mermaid
graph TD
    I["Batch Configuration file"] --> J["expand_runs (sweep.py)"]
    J --> K["List of RunSpec"]
    K --> L{"Run Count == 1?"}
    L -->|Yes| M["Flat Directory Output (setup/, simulation/)"]
    L -->|No| N["Runs Subdirectory (runs/<id>/) + batch_manifest.json"]
    M --> O["BatchExplorer (explorer.py)"]
    N --> O

    subcode2["Code Entity Mapping"]
    ExplorerClass["BatchExplorer (explorer.py)"]
    SweepExpander["expand_runs (sweep.py)"]
    end
```
Sources: `src/fastmdxplora/batch/explorer.py:1-60()`, `src/fastmdxplora/batch/sweep.py:1-60()`

---

## 3. Parallel Execution and Device Pinning

Execution modes are governed by the `execution:` configuration block (`src/fastmdxplora/batch/explorer.py:17-38()`):
- `sequential`: Runs studies one after another within the primary process.
- `parallel`: Dispatches runs across a process pool of size `workers` using `ProcessPoolExecutor` (`src/fastmdxplora/batch/explorer.py:46-51()`). Process-based parallelism is mandatory because OpenMM contexts and the Python GIL do not share safely across threads (`src/fastmdxplora/batch/explorer.py:35-37()`).

### GPU Device Pinning
When `devices: [0, 1, ...]` is specified alongside parallel execution, workers are pinned to distinct GPU devices in a round-robin fashion (one run per GPU) (`src/fastmdxplora/batch/explorer.py:20-23()`). Device assignment injects `CUDA_VISIBLE_DEVICES` into the worker subprocess environment. 

Sources: `src/fastmdxplora/batch/explorer.py:17-52()`

---

## 4. Comparison, Aggregation and Workspace GPU Sharing

### Comparison and Aggregation
Campaign outcomes can be analyzed collectively using comparison and aggregation modules (`src/fastmdxplora/batch/compare.py`, `src/fastmdxplora/batch/aggregate.py`). These utilities scan batch run directories, extract time-series metrics (e.g., RMSD, energy, hydrogen bonds), compute statistical summaries, and align trajectories across distinct sweep parameters.

### Local GPU Sharing and Workspace Concurrency
When running multiple studies concurrently on a single local workstation, FastMDXplora prevents race conditions and VRAM oversubscription through workspace runtime controls (`src/fastmdxplora/runs_here.py`, `src/fastmdxplora/gpu_here.py`):
- **Starting Locks**: Workspace initialization and study spawning hold an OS-level file lock (`STARTING_FILE`, `.fastmdxplora-starting`) to serialize concurrent start requests (`src/fastmdxplora/runs_here.py:46-95()`).
- **Active Run Registry**: Started studies record their process metadata, directory, and allocated GPU UUID in `RUNS_FILE` (`.fastmdxplora-runs.json`) (`src/fastmdxplora/runs_here.py:52-54()`).
- **VRAM Accounting**: The `gpu_room` subsystem queries local GPU memory usage (via `nvidia-smi` or cached empirical learning profiles) to verify whether an incoming study fits within available VRAM before dispatching (`src/fastmdxplora/remote/gpu_room.py`).

Diagram: Workspace and GPU Concurrency Management
```mermaid
graph TD
    P["Incoming Study Start Request"] --> Q["starting_in (runs_here.py)"]
    Q -->|Acquire OS File Lock| R[".fastmdxplora-starting"]
    R --> S["may_start Check (gpu_here.py)"]
    S --> T{"VRAM Available?"}
    T -->|No| U["Refuse with No Room Error"]
    T -->|Yes| V["Allocate GPU / CUDA_VISIBLE_DEVICES"]
    V --> W["Record Run in .fastmdxplora-runs.json"]
    W --> X["Spawn Subprocess Execution"]

    subcode3["Code Entity Mappings"]
    WorkspaceLock["starting_in (runs_here.py:72)"]
    GpuRoomCheck["may_start (runs_here.py)"]
    end
```
Sources: `src/fastmdxplora/runs_here.py:1-173()`, `src/fastmdxplora/gpu_here.py:1-50()`, `src/fastmdxplora/remote/gpu_room.py:1-50()`

---