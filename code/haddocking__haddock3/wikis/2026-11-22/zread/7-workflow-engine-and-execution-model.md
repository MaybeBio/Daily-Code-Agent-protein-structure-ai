

The HADDOCK3 workflow engine orchestrates the execution of computational docking protocols through a modular, step-based architecture. This execution model enables flexible composition of topology preparation, sampling, refinement, scoring, and analysis stages while supporting local, parallel, and HPC environments. Understanding this system is essential for both running standard workflows and designing custom protocols.

## Core Architecture Components

The workflow engine comprises three hierarchical abstractions: the `WorkflowManager` (orchestration layer), the `Workflow` (composition layer), and individual `Step` objects (execution units). This separation of concerns allows for clear lifecycle management—setup, execution, cleanup, and post-processing—while maintaining the flexibility to restart or extend runs at any stage.

The `WorkflowManager` serves as the primary conductor, responsible for reading workflow configurations, managing execution state, and coordinating cleanup and post-processing activities. It initializes a `Workflow` object containing a sequence of `Step` objects, each representing one module in the docking protocol. Each `Step` encapsulates module-specific configuration, working directory management, and execution logic. This design enables modules to be developed and tested in isolation while participating seamlessly in larger workflows.

```
┌─────────────────────────────────────────────────────────────────┐
│                        WorkflowManager                          │
│  • Orchestrates entire workflow lifecycle                        │
│  • Handles restart/extend operations                             │
│  • Coordinates post-processing and cleanup                      │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ initializes
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Workflow                                │
│  • Holds ordered sequence of steps                               │
│  • Merges global and module-specific parameters                 │
│  • Creates Step objects with proper configuration                │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ contains
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│           ┌───────────────┐  ┌───────────────┐  ┌─────────────┐│
│           │    Step 0     │  │    Step 1     │  │   Step N    ││
│           │  (topoaa)     │  │ (rigidbody)   │  │ (refinement)││
│           │               │  │               │  │             ││
│           │ • config      │  │ • config      │  │ • config    ││
│           │ • working_dir │  │ • working_dir │  │ • working_dir││
│           │ • module_obj  │  │ • module_obj  │  │ • module_obj││
│           └───────────────┘  └───────────────┘  └─────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

The module system builds on Python's dynamic import capabilities, with each module residing in category directories (topology, sampling, refinement, scoring, analysis, extras) and implementing the `BaseHaddockModule` interface. This architecture enables runtime module discovery through the `modules_category` dictionary, which maps module names to their categories and allows the workflow engine to locate and instantiate modules dynamically.

## Execution Flow and Lifecycle

A typical HADDOCK3 execution follows a four-phase lifecycle: preparation, execution, post-processing, and cleanup. The main CLI entry point in `cli.py` initiates this process by parsing the configuration file, setting up the run directory, and instantiating the appropriate `WorkflowManager`—either a standard manager or an `WorkflowManagerExtend` for continuation from a previous run.

```
┌─────────────────────────────────────────────────────────────────┐
│                    HADDOCK3 Execution Lifecycle                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   1. Setup      │───▶│  2. Execution    │───▶│ 3. Post-process │
│                 │    │                  │    │                 │
│ • Parse config   │    │ • Iterate steps  │    │ • Analyze results│
│ • Create dirs   │    │ • Execute modules│    │ • Generate reports│
│ • Setup logging │    │ • Handle errors  │    │ • Calculate statistics│
└─────────────────┘    └──────────────────┘    └────────┬────────┘
                                                         │
                                                         ▼
                                              ┌─────────────────┐
                                              │   4. Cleanup    │
                                              │                 │
                                              │ • Remove temps  │
                                              │ • Archive if needed│
                                              │ • Final report  │
                                              └─────────────────┘
```

During the execution phase, the `WorkflowManager.run()` method iterates through steps starting from the specified restart index. Each `Step.execute()` method performs several critical operations: creating the working directory (if it doesn't exist), dynamically importing the module's Python code, instantiating the module with the appropriate order and path, updating module parameters with the step's configuration, saving the configuration to disk, and invoking the module's `run()` method.

The execution order is determined by the sequence of modules in the configuration file, and each step receives configuration parameters through a recursive merge process. Global parameters defined at the workflow level (e.g., `ncores`, `clean`, `mode`) are merged with module-specific parameters, with module-level definitions taking precedence. This hierarchical configuration system allows users to set common defaults while maintaining the flexibility to override them per module.

Error handling follows a structured approach: keyboard interrupts trigger immediate program termination, module execution errors raise exceptions that can be caught and logged, and specific modules like `caprieval` can trigger controlled workflow termination via `HaddockTermination` exceptions. The `WorkflowManager` tracks the termination point to ensure cleanup operations respect the partial execution state.

## Parallel Execution Model

HADDOCK3 implements a flexible parallel execution framework that automatically scales from single-core workstations to large-scale computing clusters. The parallel execution model centers on three key abstractions: `GenericTask` (executable work units), `Worker` (process-based execution units), and `Scheduler` (task distribution and coordination). This design allows modules to define parallelizable work without managing the complexity of process management directly.

The `Scheduler` class in `libparallel.py` implements intelligent task distribution by splitting workloads into chunks based on available cores. When a module requires parallel execution (e.g., generating multiple docking models), it creates a list of tasks and passes them to the scheduler. The scheduler determines the optimal number of processes, creates worker processes, and distributes tasks using a task queue pattern. Each worker process executes tasks sequentially and writes results to a shared queue, which the scheduler monitors for completion.

> [!TIP]
> Modules don't need to implement parallelization logic directly. By defining their computational work as a list of callable tasks and using the `Scheduler`, they automatically benefit from multiprocessing, HPC, or grid execution depending on the configured mode.

Parallel execution supports three distinct modes:
- **Local multiprocessing**: Uses Python's `multiprocessing` module to spawn worker processes on the local machine. This is the default for desktop and workstation environments.
- **MPI execution**: Leverages `MPIScheduler` to distribute work across multiple nodes in a cluster, coordinating through MPI's communication primitives.
- **HPC job submission**: Uses `HPCScheduler` to generate job scripts for SLURM or Torque schedulers, enabling execution on large computing clusters without manual job management.

The scheduler automatically detects available resources and adjusts process count accordingly, respecting both user-specified core limits (`ncores` parameter) and system constraints. This ensures efficient resource utilization while preventing over-subscription that could degrade performance.

## HPC Integration and Job Management

For large-scale docking simulations requiring cluster resources, HADDOCK3 provides sophisticated HPC integration through the `HPCScheduler` class. This integration abstracts the complexities of job submission, monitoring, and result collection, allowing researchers to submit workflows from login nodes while jobs execute on compute nodes.

The `HPCWorker` class represents a single cluster job containing multiple CNS (Crystallography and NMR System) tasks. Each worker prepares a job script appropriate for the configured scheduler (SLURM or Torque), setting up environment variables, resource requests, and execution commands. The worker maintains state information about the job's status (queued, running, finished, failed) and provides methods to query status updates and cancel jobs if necessary.

HPC execution follows a multi-stage process:
1. **Job preparation**: Tasks are grouped into workers based on the `concat` parameter, which determines how many CNS jobs each HPC job should contain. This balances overhead against parallelism.
2. **Script generation**: Scheduler-specific headers are generated with appropriate resource specifications (queue, number of cores, wall time, memory).
3. **Submission**: Jobs are submitted to the cluster scheduler using system commands (`sbatch` for SLURM, `qsub` for Torque).
4. **Monitoring**: Worker processes periodically query job status using scheduler commands (`scontrol`, `qstat`) and update state accordingly.
5. **Collection**: Once jobs complete, the scheduler collects results and makes them available to the parent module.

The HPC integration supports both interactive and batch modes. In interactive mode, users can monitor job progress in real-time. In batch mode, the workflow engine submits jobs and can exit, with job completion detection handled when the workflow is later resumed or extended.

## Module System and Extension Points

The module system represents one of HADDOCK3's most powerful architectural features, enabling the extension of core functionality through a well-defined plugin interface. All modules inherit from `BaseHaddockModule`, which establishes the contract for module behavior while providing common functionality like parameter management, path handling, and input/output coordination.

Key aspects of the module system:

| Component | Responsibility | Implementation |
|-----------|---------------|----------------|
| **Parameter Management** | Hierarchical config with validation | `update_params()`, recursive merge with defaults |
| **Path Handling** | Automatic relative/absolute path conversion | `add_parent_to_paths()`, `_fill_emptypaths()` |
| **I/O Coordination** | Standardized input/output via ModuleIO | `export_io_models()`, `previous_io` |
| **Execution** | Module-specific computational logic | `_run()` (abstract), `run()` (template method) |
| **Error Handling** | Fault tolerance and CNS error detection | `finish_with_error()`, `find_all_cns_errors()` |

Modules are organized into categories reflecting their role in the docking protocol:
- **Topology**: Molecular topology generation (e.g., `topoaa`, `topocg`)
- **Sampling**: Conformational sampling algorithms (e.g., `rigidbody`, `flexref`)
- **Refinement**: Energy minimization and dynamics (e.g., `emref`, `mdref`)
- **Scoring**: Model evaluation and scoring (e.g., `emscoring`, `mdscoring`)
- **Analysis**: Post-simulation analysis (e.g., `clustfcc`, `contactmap`)
- **Extras**: Utility and special-purpose modules (e.g., `exit` for workflow termination)

The module discovery mechanism uses filesystem scanning to identify available modules. The `modules_category` dictionary is built by traversing category directories and matching module folders, enabling runtime discovery without manual registration. This makes adding new modules as simple as creating a directory with the appropriate structure and implementing the `BaseHaddockModule` interface.

## Restart and Extend Functionality

HADDOCK3 provides robust support for resuming interrupted workflows and extending completed runs with additional steps. These capabilities are essential for long-running docking simulations where interruptions (system failures, job timeouts, resource limits) are common.

Restart functionality uses the `restart` parameter to specify a step index from which execution should resume. When a restart is initiated, the `WorkflowManager` creates a `Workflow` starting from the specified step, skipping completed steps. The CLI handles this by checking for existing step directories and ensuring that the restart point has valid output from the previous step.

The extend functionality enables workflows to be continued from a completed run with additional modules. This is implemented through `WorkflowManagerExtend`, which inherits from `WorkflowManager` but modifies initialization to detect the highest-numbered step folder and continue from the next step. This use case supports scenarios where researchers want to try additional refinement or analysis protocols without repeating expensive earlier steps.

Both restart and extend operations rely on the `ModuleIO` system, which maintains persistent records of each step's input and output models. When a workflow is resumed, the loading mechanism automatically retrieves output from the previous step, ensuring continuity. This persistence layer, combined with the step-based working directory structure (e.g., `0_topoaa`, `1_rigidbody`), creates a robust checkpoint system that enables reliable recovery from failures.

## Configuration and Parameter System

The configuration system provides a hierarchical parameter management framework that balances flexibility with sensible defaults. Parameters flow through three levels: mandatory global parameters (e.g., molecules), non-mandatory global parameters (e.g., `ncores`, `clean`, `mode`), and module-specific parameters. This hierarchy allows users to define common settings once while maintaining per-module customization capability.

Configuration files support both `.cfg` (legacy INI-style) and `.yaml` formats, with readers registered in the `config_readers` dictionary. The `recursive_dict_update()` function implements the merge strategy, where more specific definitions override more general ones. This enables workflow-level default setting that can be selectively overridden at the module level.

The `non_mandatory_general_parameters_defaults` dictionary defines parameters that modules can optionally use. Common parameters include:
- `ncores`: Number of cores for parallel execution
- `clean`: Whether to remove intermediate files after completion
- `mode`: Execution mode (local, MPI, HPC, grid)
- `queue`: HPC queue for job submission
- `tolerance`: Fault tolerance percentage for output generation

Parameters are validated during module initialization through `_fill_emptypaths()` and `_confirm_fnames_exist()` methods, which ensure that paths are properly constructed and input files exist before execution begins. This early validation prevents mid-execution failures due to missing inputs or misconfigured paths.

## Next Steps

With a solid understanding of the workflow engine and execution model, you're well-positioned to explore more specialized topics:

- **CNS Integration**: Learn how modules generate and execute CNS scripts in [CNS Integration and Script Generation](8-cns-integration-and-script-generation)
- **Module Development**: Dive deeper into creating custom modules in [Module System and Plugin Architecture](9-module-system-and-plugin-architecture)
- **Parallel Execution**: Understand MPI configuration and scaling strategies in [MPI Configuration](4-mpi-configuration)
- **Practical Usage**: See real workflow examples in [Quick Start](2-quick-start)

The workflow engine's modular design and robust error handling make HADDOCK3 both powerful and accessible for computational docking studies. Whether running standard protocols or developing custom workflows, understanding these architectural foundations will help you make the most of the platform's capabilities.