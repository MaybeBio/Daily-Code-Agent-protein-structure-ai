# Scientific Pipeline

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/fastmdxplora/config/schema.py](src/fastmdxplora/config/schema.py)
- [src/fastmdxplora/setup/pdbfix.py](src/fastmdxplora/setup/pdbfix.py)
- [src/fastmdxplora/setup/pipeline.py](src/fastmdxplora/setup/pipeline.py)
- [src/fastmdxplora/setup/prepare.py](src/fastmdxplora/setup/prepare.py)
- [src/fastmdxplora/simulation/pipeline.py](src/fastmdxplora/simulation/pipeline.py)
- [src/fastmdxplora/simulation/runner.py](src/fastmdxplora/simulation/runner.py)
- [tests/test_setup_layer.py](tests/test_setup_layer.py)
- [tests/test_the_refusals_are_being_named.py](tests/test_the_refusals_are_being_named.py)

</details>



## Purpose and Scope

The FastMDXplora scientific pipeline transforms raw molecular structures into rigorous thermodynamic and dynamic insights through four sequential phases: setup, simulation, analysis, and report generation. Artifacts flow deterministically between these phases using structured file bundles (`system.xml`, `state.xml`, trajectories, and JSON manifests) stored within a study workspace. 

This page provides a high-level architectural overview of how the pipeline stages interact. For detailed technical specifications, deep-dive configuration options, and implementation specifics, refer to the child pages linked throughout.

Sources: `src/fastmdxplora/setup/pipeline.py:1-45` [src/fastmdxplora/setup/pipeline.py:1-45](), `src/fastmdxplora/simulation/pipeline.py:1-44` [src/fastmdxplora/simulation/pipeline.py:1-44]()

---

## Pipeline Artifact Flow

The diagram below maps the natural language space of user study requests and configuration blocks to the underlying code entities that execute each phase of the scientific pipeline.

Title: Pipeline Artifact Flow and Code Entities

```mermaid
graph TD
    UserRequest[""UserStructureOrPDB""] --> SetupPhase[""run (setup/pipeline.py)""]
    SetupPhase --> PreparedArtifacts[""system.xml, state.xml, topology.pdb (setup/prepare.py)""]
    PreparedArtifacts --> SimPhase[""run (simulation/pipeline.py)""]
    SimPhase --> Runner[""run_simulation (simulation/runner.py)""]
    Runner --> Trajectory[""TrajectoryFramesAndLogs""]
    Trajectory --> AnalysisPhase[""AnalysisOrchestrator""]
    AnalysisPhase --> ReportPhase[""ReportGeneratorAndStatistics""]
    
    subgraph NaturalLanguageSpace
        UserRequest
    end

    subgraph CodeEntitySpace
        SetupPhase
        PreparedArtifacts
        SimPhase
        Runner
        Trajectory
        AnalysisPhase
        ReportPhase
    end
```

Sources: `src/fastmdxplora/setup/pipeline.py:1-25` [src/fastmdxplora/setup/pipeline.py:1-25](), `src/fastmdxplora/simulation/pipeline.py:1-12` [src/fastmdxplora/simulation/pipeline.py:1-12](), `src/fastmdxplora/simulation/runner.py:1-14` [src/fastmdxplora/simulation/runner.py:1-14]()

---

## 3.1 Setup Phase: System Preparation

The setup phase bridges raw structural inputs (PDB files, RCSB accession codes, or sequences) to a parameterised, solvated, and neutralised OpenMM system. It resolves force fields, handles missing residues or heavy atoms via PDBFixer, assigns protonation states at a target pH, and packs periodic water boxes with specified ionic strengths.

For detailed information on heterogen management, CCD lookups, membrane building, and size estimation checks, see [Setup Phase: System Preparation](#3.1).

Sources: `src/fastmdxplora/setup/pipeline.py:1-25` [src/fastmdxplora/setup/pipeline.py:1-25](), `src/fastmdxplora/setup/prepare.py:1-39` [src/fastmdxplora/setup/prepare.py:1-39]()

---

## 3.2 Simulation Phase

The simulation phase consumes the serialized `system.xml`, `state.xml`, and `topology.pdb` artifacts produced during setup. It executes an OpenMM-backed runner across multiple compute platforms (CUDA, OpenCL, CPU) while recording telemetry, enforcing stage planning, and managing execution checkpoints.

For deep technical details on integrators, barostats, and enhanced sampling, see [Simulation Phase](#3.2).

Sources: `src/fastmdxplora/simulation/pipeline.py:1-44` [src/fastmdxplora/simulation/pipeline.py:1-44](), `src/fastmdxplora/simulation/runner.py:1-18` [src/fastmdxplora/simulation/runner.py:1-18]()

### 3.2.1 MD Runner, Platforms and Checkpoints

The core runner executes a standard four-stage MD pipeline: energy minimization, NVT equilibration, NPT equilibration, and production run execution. It handles variable-step integrators, thermal bath coupling via Langevin thermostats, barostat frequency adjustments, and checkpoint seal verifications.

For details on stage parameters, resume logic, and stop graces, see [MD Runner, Platforms and Checkpoints](#3.2.1).

Sources: `src/fastmdxplora/simulation/runner.py:1-14` [src/fastmdxplora/simulation/runner.py:1-14](), `src/fastmdxplora/simulation/runner.py:120-159` [src/fastmdxplora/simulation/runner.py:120-159]()

### 3.2.2 Enhanced Sampling and Free Energy

When standard production dynamics are insufficient to cross high free-energy barriers, FastMDXplora integrates advanced sampling methodologies. These include umbrella sampling with WHAM post-processing, well-tempered metadynamics, steered molecular dynamics, and PLUMED plugin orchestration.

For specific configuration guides and free energy profile calculations, see [Enhanced Sampling and Free Energy](#3.2.2).

Sources: `src/fastmdxplora/simulation/pipeline.py:139-158` [src/fastmdxplora/simulation/pipeline.py:139-158]()

---

## 3.3 Analysis Phase

The analysis phase processes trajectory frames generated during production MD to extract structural, dynamic, thermodynamic, and ligand-interaction metrics. The framework uses a registered list of analyses ranging from foundational metrics like RMSD and radius of gyration to complex spatial distribution functions.

For a comprehensive catalog of available analysis routines and trajectory loading conventions, see [Analysis Phase](#3.3).

Sources: `src/fastmdxplora/config/schema.py:41-76` [src/fastmdxplora/config/schema.py:41-76]()

### 3.3.1 Structural and Dynamic Analyses

Structural evaluations track macromolecular stability, backbone fluctuations, compactness, solvent-accessible surface area, and secondary structure persistence across time. 

For implementation details on RMSD, RMSF, Rg, SASA, and hydrogen bonding calculations, see [Structural and Dynamic Analyses](#3.3.1).

Sources: `src/fastmdxplora/config/schema.py:45-50` [src/fastmdxplora/config/schema.py:45-50]()

### 3.3.2 Ligand, Interaction and Solvent Analyses

Protein-ligand systems require specialized scrutiny. This subsection covers ligand RMSD/RMSF tracking, contact map generation, hydrogen bond occupancy, and hydration shell (water site) characterization.

For detailed protocols on binding site solvent dynamics and interaction profiling, see [Ligand, Interaction and Solvent Analyses](#3.3.2).

Sources: `src/fastmdxplora/config/schema.py:46-48` [src/fastmdxplora/config/schema.py:46-48]()

### 3.3.3 Membrane, Thermodynamic and Reweighted Analyses

For membrane-embedded systems and biased simulations, specialized metrics evaluate bilayer thickness, area per lipid, lipid acyl-chain order parameters, system thermodynamics, and WHAM/metadynamics reweighted averages.

For complete coverage of membrane and reweighted observable pipelines, see [Membrane, Thermodynamic and Reweighted Analyses](#3.3.3).

Sources: `src/fastmdxplora/config/schema.py:55-64` [src/fastmdxplora/config/schema.py:55-64](), `src/fastmdxplora/config/schema.py:72-75` [src/fastmdxplora/config/schema.py:72-75]()

---

## 3.4 Report Phase and Statistics

The report phase synthesizes artifact records, trajectory summaries, and statistical evaluations into publication-ready documents, presentation slides, or PDF summaries. It handles automated methods prose generation, convergence assessments, and statistical inefficiency calculations to ensure reproducibility and transparency before study deposition.

For details on report compilation, statistical withholding rules, and export bundles, see [Report Phase and Statistics](#3.4).

Sources: `src/fastmdxplora/config/schema.py:4-25` [src/fastmdxplora/config/schema.py:4-25]()

---