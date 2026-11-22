# Scientific Validation, Corpus and Preregistration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [docs/developers.md](docs/developers.md)
- [docs/validation.md](docs/validation.md)
- [preregistration/agent-eval-v2.md](preregistration/agent-eval-v2.md)
- [preregistration/agent-eval.md](preregistration/agent-eval.md)
- [preregistration/agent-looks.md](preregistration/agent-looks.md)
- [preregistration/stopping-calibration-shared-start-heldout.json](preregistration/stopping-calibration-shared-start-heldout.json)
- [preregistration/stopping-calibration-shared-start-registered.json](preregistration/stopping-calibration-shared-start-registered.json)
- [preregistration/stopping-calibration.md](preregistration/stopping-calibration.md)
- [src/fastmdxplora/agent/evaluate.py](src/fastmdxplora/agent/evaluate.py)
- [src/fastmdxplora/analysis/analyze.py](src/fastmdxplora/analysis/analyze.py)
- [src/fastmdxplora/simulation/stopping.py](src/fastmdxplora/simulation/stopping.py)
- [src/fastmdxplora/validation/agent_eval.py](src/fastmdxplora/validation/agent_eval.py)
- [src/fastmdxplora/validation/agent_looks.py](src/fastmdxplora/validation/agent_looks.py)
- [src/fastmdxplora/validation/cross_tool.py](src/fastmdxplora/validation/cross_tool.py)
- [src/fastmdxplora/validation/environments.py](src/fastmdxplora/validation/environments.py)
- [src/fastmdxplora/validation/stopping_calibration.py](src/fastmdxplora/validation/stopping_calibration.py)
- [tests/data/agent_eval/context_2026-10-13.json.gz](tests/data/agent_eval/context_2026-10-13.json.gz)
- [tests/data/agent_eval/context_without_2026-10-13.json.gz](tests/data/agent_eval/context_without_2026-10-13.json.gz)
- [tests/data/agent_eval/run_2026-10-13.json.gz](tests/data/agent_eval/run_2026-10-13.json.gz)
- [tests/test_a_figure_is_plotted.py](tests/test_a_figure_is_plotted.py)
- [tests/test_a_molecule_alone_is_made_whole.py](tests/test_a_molecule_alone_is_made_whole.py)
- [tests/test_a_number_the_world_does_not_have.py](tests/test_a_number_the_world_does_not_have.py)
- [tests/test_a_study_runs_until_it_knows.py](tests/test_a_study_runs_until_it_knows.py)
- [tests/test_cross_tool_helpers.py](tests/test_cross_tool_helpers.py)
- [tests/test_cross_tool_survives_the_move.py](tests/test_cross_tool_survives_the_move.py)
- [tests/test_environments.py](tests/test_environments.py)
- [tests/test_replicas_share_their_start.py](tests/test_replicas_share_their_start.py)
- [tests/test_the_agent_is_evaluated.py](tests/test_the_agent_is_evaluated.py)
- [tests/test_the_agents_looking_is_measured.py](tests/test_the_agents_looking_is_measured.py)
- [tests/test_the_interface_is_measured_not_assumed.py](tests/test_the_interface_is_measured_not_assumed.py)
- [tests/test_the_stopping_rule_is_calibrated.py](tests/test_the_stopping_rule_is_calibrated.py)

</details>



### Purpose and Scope
This page details the validation framework of FastMDXplora (`src/fastmdxplora/validation/`), which measures rates, tests independent software interoperability, evaluates guardrail corpora, verifies cross-environment configuration parity, runs agent evaluations against preregistered specifications, and calibrates dynamic stopping rules. Unlike the test suite (`tests/`), which asserts logical correctness during code execution, the validation infrastructure measures scientific fidelity against external references, human-agent interaction standards, and statistical bounds.

---

## 1. The Validation Architecture and Philosophy

The validation subsystem operates on the principle that automated molecular dynamics pipelines must be continuously audited against independent implementations and standardized corpora. Rather than relying on internal self-consistency, FastMDXplora isolates validation packages (such as `ProLIF` and `MDAnalysis`) as external references.

The core validation modules include:
- `fastmdxplora.validation.cross_tool`: Interoperability checks against independent reference libraries `[src/fastmdxplora/validation/cross_tool.py:1-51]()`.
- `fastmdxplora.validation.corpus`: Guardrail corpus testing refusal behavior on `DEFECTS` and `CLEAN` cases `[docs/validation.md:12-30]()`.
- `fastmdxplora.validation.environments`: Field-by-field parity checking across different runtime installations (`resolved_config.yml` and structure hashes) `[docs/validation.md:94-122]()`.
- `fastmdxplora.validation.agent_eval`: Versioned evaluation framework for natural-language agent turns and task completion `[src/fastmdxplora/validation/agent_eval.py:1-71]()`.
- `fastmdxplora.validation.stopping_calibration`: Calibration suite tracking statistical coverage of dynamic stopping rules `[preregistration/stopping-calibration.md:1-24]()`.

Sources: `src/fastmdxplora/validation/cross_tool.py:1-51]`, `[docs/validation.md:1-122]`, `[src/fastmdxplora/validation/agent_eval.py:1-71]`.

---

## 2. Cross-Tool Agreement Package

To prevent internal code drift and implementation bias, FastMDXplora compares its analysis products against independent reference implementations (`ProLIF` for protein-ligand interactions and `MDAnalysis` for geometric observables) without shipping them as mandatory package dependencies `[src/fastmdxplora/validation/cross_tool.py:24-51]`.

### Key Functions and Data Flow
- **Artifact Discovery**: `load_manifest()` and `find_artifact()` locate simulation trajectories and topologies using the study's `manifest.json` as the source of truth, automatically re-rooting cluster-absolute paths for local file systems `[src/fastmdxplora/validation/cross_tool.py:145-172]`.
- **Periodic Boundary Healing**: `_ReimageLigand` corrects molecules split across periodic boundaries using template bonds before distance metrics are computed by reference tools `[src/fastmdxplora/validation/cross_tool.py:18-20]`, `[tests/test_cross_tool_helpers.py:105-148]()`.
- **Residue Normalization**: `residue_label()` maps heterogeneous tool string formatting (e.g., `"ASP 189 A"`, `"ASP189.A"`, `"ASP189-OD1"`) into unified identifiers (`"ASP189"`) to enable reliable table joins `[src/fastmdxplora/validation/cross_tool.py:135-142]`, `[tests/test_cross_tool_helpers.py:33-46]()`.
- **Pre-Registered Tolerances**:
  - `HARMONIZED_OCCUPANCY_TOL_PP = 5.0` (percentage points per residue kind) `[src/fastmdxplora/validation/cross_tool.py:42-44]()`.
  - `OBSERVABLE_TOL_NM = 1e-3` (maximum absolute delta for RMSD and radius of gyration traces) `[src/fastmdxplora/validation/cross_tool.py:45]()`.
  - `NEGATIVE_OCCUPANCY_MAX_PCT = 5.0` (upper bound for cavity interactions in negative control runs) `[src/fastmdxplora/validation/cross_tool.py:46]()`.

```mermaid
title "Natural Language Space to Code Entity Space: Cross-Tool Validation"
graph TD
    NL1[""Compare protein-ligand interactions against ProLIF""] --> Code1[""fastmdxplora.validation.cross_tool.interactions()""]
    NL2[""Re-root cluster paths and locate files""] --> Code2[""fastmdxplora.validation.cross_tool.find_artifact()""]
    NL3[""Heal periodic boundary splitting""] --> Code3[""fastmdxplora.validation.cross_tool._ReimageLigand()""]
    NL4[""Normalize residue string labels""] --> Code4[""fastmdxplora.validation.cross_tool.residue_label()""]

    Code1 --> Code2
    Code2 --> Code3
    Code3 --> Code4
```

Sources: `[src/fastmdxplora/validation/cross_tool.py:1-172]`, `[tests/test_cross_tool_helpers.py:33-148]`.

---

## 3. Guardrail Corpus and Refusal Validation

The validation corpus evaluates the robustness of FastMDXplora's refusal philosophy. Every refusal issued by the software represents a structural, semantic, or environmental claim that a study must not proceed `[docs/validation.md:16-17]`.

### Corpus Structure and Outcomes
The corpus comprises two distinct test collections (`fastmdxplora.validation.corpus`):
- **`DEFECTS`**: Studies containing flawed parameters, incompatible force fields, or invalid configurations that *should* be refused `[docs/validation.md:19]`.
- **`CLEAN`**: Valid, production-ready studies that *should* proceed untouched `[docs/validation.md:20]`.

Cases yield one of three outcomes:
1. `proceeded`: Execution continues normally.
2. `refused`: Execution halts with a defined `StudyError` code.
3. `qualified`: Execution proceeds under documented constraints (e.g., constant-pressure equilibration segments) `[docs/validation.md:38-46]`.

```mermaid
title "Guardrail Corpus Evaluation Flow"
graph TD
    Case[""Corpus Case: Case(name, run, expect, because)""] --> Evaluator[""fastmdxplora.validation.corpus.run_corpus()""]
    Evaluator --> Outcome{""Observe Outcome""}
    Outcome -->|""Flawed input""| Refused[""refused (StudyError raised)""]
    Outcome -->|""Valid input""| Clean[""proceeded (Execution valid)""]
    Outcome -->|""Boundary case""| Qualified[""qualified (Warning/Note emitted)""]
```

Sources: `[docs/validation.md:1-50]`.

---

## 4. Environment Parity and Reproducibility Checks

To guarantee that FastMDXplora configurations are portable across execution substrates, the environment validation suite (`fastmdxplora.validation.environments`) compares runs executed inside containers, Conda environments, and PyPI wheel installations `[docs/validation.md:94-97]`.

### Comparison Matrix
- **`resolved_config.yml`**: Must match **exactly** across environments to verify default resolution parity `[docs/validation.md:99-102]`.
- **Input Structure SHA-256**: Checked via `setup/setup_parameters.json` to ensure identical input topologies `[docs/validation.md:99-102]`.
- **Trajectory Results**: Do **not** match exactly due to non-deterministic solvent generation seeds and thermal noise initialization. This variance is explicitly accounted for rather than treated as a defect `[docs/validation.md:103-110]`.

Sources: `[docs/validation.md:94-122]`, `[tests/test_environments.py]`.

---

## 5. Agent Evaluation Harness and Preregistrations

The natural-language agent interface is evaluated through a versioned framework (`fastmdxplora.validation.agent_eval`) governed by preregistered specifications (`preregistration/agent-eval-v2.md`) `[src/fastmdxplora/validation/agent_eval.py:1-110]`, `[preregistration/agent-eval-v2.md:1-15]`.

### Evaluation Kinds and Tiers
Cases are categorized into functional kinds and tested across multiple tiers (easy, medium, hard):
- `write` (16 cases): Generates an accepted study configuration from a single prompt `[src/fastmdxplora/validation/agent_eval.py:19-21]`, `[preregistration/agent-eval.md:60-80]`.
- `edit` (6 cases): Modifies an existing configuration over conversational turns `[src/fastmdxplora/validation/agent_eval.py:22-23]`.
- `repair` (4 cases): Fixes a refused configuration upon user attachment `[src/fastmdxplora/validation/agent_eval.py:24-25]`.
- `no_structure` / `refusal` / `no_action` (Safety kinds, 11 total): Ensures safety boundaries are respected without hallucinating structures or bypassing refusals `[src/fastmdxplora/validation/agent_eval.py:26-33], [116]`.
- `docs` (31 cases) & `records` (2 cases): Answers questions regarding documentation (`read_docs`) and finished study metrics `[src/fastmdxplora/validation/agent_eval.py:35-39]`.
- `context` (8 cases, Version 2): Evaluates multi-turn memory, UI page hints, and `@`-mentions `[src/fastmdxplora/validation/agent_eval.py:40-44]`, `[preregistration/agent-eval-v2.md:16-25]`.

```mermaid
title "Natural Language Space to Code Entity Space: Agent Evaluation"
graph TD
    NL_Agent[""User: Simulate 1UBQ for 10 ns with 310 K""] --> Code_Eval[""fastmdxplora.validation.agent_eval.run()""]
    Code_Eval --> Code_Propose[""fastmdxplora.agent.turns.propose_config()""]
    Code_Propose --> Code_Judge[""fastmdxplora.validation.agent_eval.judge()""]
    Code_Judge --> Outcome[""Verdict: Pass/Fail against preregistered config""]
```

Sources: `[src/fastmdxplora/validation/agent_eval.py:1-120]`, `[preregistration/agent-eval.md:1-88]`, `[preregistration/agent-eval-v2.md:1-131]`.

---

## 6. Stopping Calibration and Statistical Guardrails

Dynamic stopping rules (`simulation.stop_when`) allow studies to run iteratively until specified standard errors or relative errors are achieved, bounded by maximum ceilings `[src/fastmdxplora/simulation/stopping.py:1-26]`.

### Calibration Metrics
Calibrated against synthetic AR(1) time-series and two-state models (`fastmdxplora.validation.stopping_calibration` and `preregistration/stopping-calibration.md`), the stopping logic tracks:
- **Statistical Inefficiency**: Automatically calculated to account for autocorrelation time when estimating standard errors `[preregistration/stopping-calibration.md:17-23]`.
- **Replica Agreement**: Enforces independent start seeds (`simulation.random_seed`) to prevent premature convergence trapped in local energy minima. Replicas must agree within Cochran's Q threshold (`AGREE_WITHIN = 2.0`) `[src/fastmdxplora/simulation/stopping.py:55-58]`, `[tests/test_a_study_runs_until_it_knows.py:61-80]`.
- **Withholding Check**: Unresolved correlations or insufficient sampling lengths automatically trigger mean withholding to prevent reporting unverified precision `[preregistration/stopping-calibration.md:41-47]`.

```mermaid
title "Stopping Calibration and Iterative Execution Loop"
graph TD
    Start[""Initialize simulation piece""] --> Run[""Run simulation segment""]
    Run --> Analysis[""Execute target analysis (e.g. RMSD)""]
    Analysis --> Check[""fastmdxplora.simulation.stopping.check_stopping()""]
    Check --> Evaluated{""Target error met & replicas agree?""}
    Evaluated -->|""No""| Extend[""Extend study (MOST_PER_ROUND limit)""]
    Extend --> Run
    Evaluated -->|""Yes""| Complete[""Finalize study manifest & record findings""]
```

Sources: `[src/fastmdxplora/simulation/stopping.py:1-146]`, `[preregistration/stopping-calibration.md:1-121]`, `[tests/test_a_study_runs_until_it_knows.py:1-150]`.

---