# Glossary

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/manifest.md](docs/manifest.md)
- [docs/refusals.md](docs/refusals.md)
- [docs/results.md](docs/results.md)
- [src/fastmdxplora/advisories.py](src/fastmdxplora/advisories.py)
- [src/fastmdxplora/batch/explorer.py](src/fastmdxplora/batch/explorer.py)
- [src/fastmdxplora/orchestrator.py](src/fastmdxplora/orchestrator.py)
- [src/fastmdxplora/refusals.py](src/fastmdxplora/refusals.py)
- [src/fastmdxplora/report/convergence.py](src/fastmdxplora/report/convergence.py)
- [src/fastmdxplora/report/document.py](src/fastmdxplora/report/document.py)
- [src/fastmdxplora/report/methods.py](src/fastmdxplora/report/methods.py)
- [src/fastmdxplora/report/run.py](src/fastmdxplora/report/run.py)
- [src/fastmdxplora/report/slides.py](src/fastmdxplora/report/slides.py)
- [src/fastmdxplora/simulation/umbrella.py](src/fastmdxplora/simulation/umbrella.py)
- [src/fastmdxplora/statistics.py](src/fastmdxplora/statistics.py)
- [src/fastmdxplora/utils/presenter.py](src/fastmdxplora/utils/presenter.py)
- [tests/test_a_run_is_held_to_what_its_plan_said.py](tests/test_a_run_is_held_to_what_its_plan_said.py)
- [tests/test_a_series_shows_how_it_converged.py](tests/test_a_series_shows_how_it_converged.py)
- [tests/test_a_short_pilot_sizes_the_study.py](tests/test_a_short_pilot_sizes_the_study.py)
- [tests/test_a_window_can_be_held_at_its_own_constant.py](tests/test_a_window_can_be_held_at_its_own_constant.py)
- [tests/test_batch.py](tests/test_batch.py)
- [tests/test_cli.py](tests/test_cli.py)
- [tests/test_orchestrator.py](tests/test_orchestrator.py)
- [tests/test_presenter.py](tests/test_presenter.py)
- [tests/test_report_wiring.py](tests/test_report_wiring.py)
- [tests/test_umbrella.py](tests/test_umbrella.py)

</details>



## Purpose and Scope

This page provides precise technical definitions for codebase-specific terminology across FastMDXplora. Every concept is anchored to its architectural role, semantic definition, and primary code pointers within the repository.

---

## 1. Core Concepts and Orchestration

### Study
An end-to-end molecular dynamics project encompassing system preparation, simulation execution, statistical analysis, and report generation. In FastMDXplora, single-system runs and multi-system batch campaigns share a unified execution path where a single system is treated as a batch of one `[src/fastmdxplora/batch/explorer.py:1-6]()`.
- **Code pointers:** `[src/fastmdxplora/batch/explorer.py:1-38]`, `[src/fastmdxplora/orchestrator.py:1-17]()`

### Phase
One of the four coordinated sequential stages in the scientific pipeline: `setup`, `simulation`, `analysis`, and `report`. Each phase is managed by the orchestrator and produces structured artifacts and provenance records `[src/fastmdxplora/orchestrator.py:1-16]`, `[src/fastmdxplora/orchestrator.py:56-59]()`.
- **Code pointers:** `[src/fastmdxplora/orchestrator.py:56-59]`, `[src/fastmdxplora/orchestrator.py:95-158]()`

### Manifest
The JSON provenance file (`manifest.json` or `batch_manifest.json`) recording execution status, timestamps, phase artifacts, software versions, and structured refusals for auditability and reproducibility `[src/fastmdxplora/orchestrator.py:140-156]()`.
- **Code pointers:** `[src/fastmdxplora/orchestrator.py:140-156]`, `[docs/manifest.md:1-50]()`

### Resolved Config
The fully expanded and validated configuration (`resolved_config.yml`) resulting from merging user-provided option overrides with schema defaults and environment parameters.
- **Code pointers:** `[src/fastmdxplora/config/loader.py:1-50]()`

### Active Study
The currently targeted study directory or runtime context loaded within the GUI dashboard workspace or API session.
- **Code pointers:** `[src/fastmdxplora/batch/explorer.py:146-165]()`

### Segment
An incremental continuation or restart folder (`segment-*`) created when a simulation run is extended or resumed in place.
- **Code pointers:** `[src/fastmdxplora/batch/explorer.py:146-152]()`

### Sweep
A parameter expansion mechanism that transforms a configuration grid into multiple distinct run specifications (`RunSpec`) executed sequentially or in parallel.
- **Code pointers:** `[src/fastmdxplora/batch/sweep.py:1-50]`, `[src/fastmdxplora/batch/explorer.py:55-60]()`

```mermaid
graph TD
    subgraph "Natural Language Space"
        A[""Study Declaration & Sweep""] --> B[""Pipeline Phase Execution""]
        B --> C[""Resolved Configuration & Manifest""]
    end
    subgraph "Code Entity Space"
        D[""BatchExplorer (explorer.py)""] --> E[""PhaseResult (orchestrator.py)""]
        E --> F[""manifest.json & resolved_config.yml""]
    end
    A -.-> D
    B -.-> E
    C -.-> F
```
*Sources: `[src/fastmdxplora/batch/explorer.py:1-60]`, `[src/fastmdxplora/orchestrator.py:56-158]()`*

---

## 2. Refusals, Advisories, and Quality Control

### Refusal
A structured halt mechanism (`Refusal`) raised when a study cannot proceed safely. Unlike unstructured exceptions, refusals carry a stable hierarchical code, a classification kind (`structural`, `semantic`, `environmental`, `insufficient`), a retryable flag, and a strict disclosure policy `[src/fastmdxplora/refusals.py:1-125]`, `[docs/refusals.md:1-43]()`.
- **Code pointers:** `[src/fastmdxplora/refusals.py:1-177]`, `[docs/refusals.md:1-89]()`

### Withholding
The deliberate suppression of derived observables or error estimates when statistical prerequisites—such as equilibration or sufficient independent sample counts—are violated.
- **Code pointers:** `[src/fastmdxplora/statistics.py:1-36]`, `[src/fastmdxplora/statistics.py:134-139]()`

### Remedy
An exact, non-judgmental action prescription (such as an install command or path correction) attached to structural or environmental refusals.
- **Code pointers:** `[src/fastmdxplora/refusals.py:126-155]()`

### Advisory
Non-fatal warnings or recommendations generated during configuration validation or analysis that inform the user of suboptimal parameters without halting execution.
- **Code pointers:** `[src/fastmdxplora/advisories.py:1-30]()`

### Statistical Inefficiency
The autocorrelation time parameter ($g$) measuring the number of MD frames required to yield a single independent sample, used directly in standard error calculations.
- **Code pointers:** `[src/fastmdxplora/statistics.py:28-36]`, `[src/fastmdxplora/statistics.py:59-62]()`

### Equilibration Detection
Chodera's automated algorithm for identifying the optimal starting frame index where initial system relaxation ends and stationary production sampling begins.
- **Code pointers:** `[src/fastmdxplora/statistics.py:31-36]`, `[src/fastmdxplora/statistics.py:61-62]()`

```mermaid
graph TD
    subgraph "Natural Language Space"
        G[""Refusal & Error Classification""] --> H[""Statistical Withholding""]
        H --> I[""Equilibration & Inefficiency Check""]
    end
    subgraph "Code Entity Space"
        J[""refusal_of / CodedError (refusals.py)""] --> K[""Withholding (statistics.py)""]
        K --> L[""detect_equilibration / statistical_inefficiency""]
    end
    G -.-> J
    H -.-> K
    I -.-> L
```
*Sources: `[src/fastmdxplora/refusals.py:1-125]`, `[src/fastmdxplora/statistics.py:1-62]()`*

---

## 3. Simulation and Enhanced Sampling

### Umbrella Window
An individual restrained simulation slice along a collective variable (e.g., distance or angle) designed to sample a localized region of conformational space.
- **Code pointers:** `[src/fastmdxplora/simulation/umbrella.py:1-26]`, `[src/fastmdxplora/simulation/umbrella.py:68-106]()`

### Cone Wall
A flat-bottomed angular restraint that confines a ligand to a solid angle cap relative to a protein-fixed axis, ensuring rigorous bulk reference state calculations without applying artificial harmonic forces in the bound state.
- **Code pointers:** `[src/fastmdxplora/simulation/umbrella.py:68-106]()`

### WHAM
Weighted Histogram Analysis Method implementation used to recombine overlapping umbrella sampling windows into a continuous potential of mean force (PMF) free energy profile.
- **Code pointers:** `[src/fastmdxplora/simulation/umbrella.py:1-19]`, `[tests/test_umbrella.py:38-63]()`

---

## 4. AI Interfaces, Remote Execution, and Telemetry

### Telemetry
Real-time progress monitoring and metrics written to `live_status.json` by the simulation runner, enabling batch progress hearts and GUI polling.
- **Code pointers:** `[src/fastmdxplora/batch/explorer.py:136-160]()`, `[src/fastmdxplora/simulation/runner.py:1-50]()`

### Toolbox
The collection of structured tools and functions exposed to the LLM agent during autonomous configuration proposal loops.
- **Code pointers:** `[src/fastmdxplora/agent/toolbox.py:1-40]()` (conceptual)

### Context Receipt
Structured prompt memory and execution feedback records passed between agent iterations to maintain conversation state and validation history.
- **Code pointers:** `[src/fastmdxplora/agent/receipts.py:1-40]()` (conceptual)

### Agent Mode
The automated natural-language study generation and interactive error-correction execution loop.
- **Code pointers:** `[src/fastmdxplora/cli/main.py:1-50]()`

### Hosting Mode
Local HTTP server configuration, loopback allowlists, and proxy routing behavior for the dependency-free GUI dashboard.
- **Code pointers:** `[src/fastmdxplora/gui/server.py:1-50]()` (conceptual)

### Backend Probe
Diagnostic scripts and inspection routines executed on remote compute nodes to verify package environments, Python versions, and hardware backends.
- **Code pointers:** `[src/fastmdxplora/remote/probe.py:1-40]()` (conceptual)

### Readiness
Verification status determining whether a remote worker environment satisfies all commit parity, dependency, and scheduler prerequisites before study transfer.
- **Code pointers:** `[src/fastmdxplora/remote/readiness.py:1-40]()` (conceptual)

### Send ID
Unique tracking identifier assigned when dispatching study payloads to remote clusters or worker queues.
- **Code pointers:** `[src/fastmdxplora/remote/desk.py:1-40]()` (conceptual)

### GPU Room
VRAM accounting and hardware capacity calculation subsystem used for optimal GPU allocation and batch packing.
- **Code pointers:** `[src/fastmdxplora/remote/gpu_room.py:1-40]()` (conceptual)

### Plan Token
Cryptographic hash token ensuring input safety, boundary checks, and path integrity during remote file transfers.
- **Code pointers:** `[src/fastmdxplora/remote/inputs.py:1-40]()` (conceptual)