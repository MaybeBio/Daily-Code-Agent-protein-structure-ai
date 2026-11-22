# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [model_workflow/mwf.py](model_workflow/mwf.py)
- [model_workflow/utils/constants.py](model_workflow/utils/constants.py)

</details>



The MDDB-workflow repository provides a comprehensive framework for processing and analyzing molecular dynamics (MD) simulation data. It standardizes raw MD files, validates them through integrity tests, performs various analyses, and prepares the processed data for upload to the MDDB database.

Sources: [README.md:1-5]()

## Purpose and Scope

This workflow system serves as a robust pipeline that:

1. Processes raw MD data (topologies and trajectories) into standardized formats
2. Validates data integrity through several quality checks and tests
3. Performs a wide range of analyses on MD simulations
4. Generates metadata and other output files required for the MDDB database
5. Provides a command-line interface for automating these tasks

The MDDB-workflow is designed to operate on molecular dynamics simulations that consist of structure (atom coordinates), trajectory (atom movements over time), and topology (atom properties and connectivity) data.

For information about the command-line interface, see [Command Line Interface](#5).

Sources: [README.md:1-5](), [README.md:79-97](), [model_workflow/mwf.py:89-104]()

## System Architecture

The MDDB-workflow is organized around a well-defined architecture centered on two main classes that manage molecular dynamics data.

```mermaid
classDiagram
    class "Project" {
        +directory: str
        +input_files
        +MDs: List[MD]
        +topology_file
        +register
        +run_analyses()
    }
    
    class "MD" {
        +project: Project
        +directory: str
        +input_structure_file
        +input_trajectory_files
        +structure_file
        +trajectory_file
        +register
        +structure
        +process_input_files()
    }
    
    class "Structure" {
        +atoms: List[Atom]
        +bonds: List[List[int]]
        +select()
        +set_new_coordinates()
    }
    
    class "Register" {
        +file: File
        +tests: dict
        +cache: dict
        +update_test()
        +update_cache()
        +add_warning()
    }
    
    class "File" {
        +path: str
        +filename: str
        +format: str
        +exists: bool
        +remove()
        +rename_to()
    }
    
    "Project" *-- "MD" : manages
    "MD" --> "Structure" : uses
    "MD" --> "Register" : tracks tests
    "Project" --> "Register" : tracks tests
    "MD" --> "File" : manages files
    "Project" --> "File" : manages files
</mermaid>

**Core Classes and Their Relationships:**

1. **Project Class**: Manages a collection of related MD simulations, handles project-level settings and files.
2. **MD Class**: Represents a single molecular dynamics simulation, handles structure and trajectory processing.
3. **Structure Class**: Represents molecular structures and provides methods to manipulate them.
4. **Register Class**: Tracks test executions and caches results to avoid redundant operations.
5. **File Class**: A utility class for handling file operations consistently.

Sources: [model_workflow/mwf.py:100-1126](), [model_workflow/mwf.py:457-474](), [model_workflow/mwf.py:172-174]()

## Data Flow

The following diagram illustrates how data flows through the MDDB-workflow system:

```mermaid
flowchart TB
    subgraph "Input"
        raw_top["Raw Topology\n(.prmtop, .tpr, .psf)"]
        raw_traj["Raw Trajectories\n(.nc, .xtc, .dcd)"]
        inputs["inputs.yml\nConfiguration"]
    end

    subgraph "Processing"
        check["check_inputs()\nValidate formats"]
        convert["convert()\nStandardize formats"]
        filter["filter_atoms()\nRemove water/ions"]
        image["image_and_fit()\nFix PBC issues"]
        correct["structure_corrector()\nFix elements/bonds"]
        test["Register\nRun integrity tests"]
    end

    subgraph "Analysis"
        analyses["Analysis Modules\nRMSD, RMSF, PCA, etc."]
        mapping["generate_protein_mapping()\nResidues and chains"]
        interactions["process_interactions()\nInteraction analysis"]
        metadata["generate_metadata()\nPrepare for database"]
        topology["generate_topology()\nStandardized topology"]
    end

    subgraph "Output"
        structure["structure.pdb\nStandardized structure"]
        trajectory["trajectory.xtc\nStandardized trajectory"]
        top_json["topology.json\nStandardized topology"]
        meta_json["metadata.json\nProject metadata"]
        analysis_files["Analysis output files\n(.json)"]
    end

    raw_top --> check
    raw_traj --> check
    inputs --> check

    check --> convert
    convert --> filter
    filter --> image
    image --> correct
    correct --> test
    
    test --> analyses
    test --> mapping
    test --> interactions
    mapping --> metadata
    interactions --> metadata
    analyses --> metadata
    test --> topology
    
    correct --> structure
    image --> trajectory
    topology --> top_json
    metadata --> meta_json
    analyses --> analysis_files
</mermaid>

This workflow processes data in several stages:

1. **Input Validation**: Raw MD files are checked for format compatibility and existence
2. **Processing**: Files are converted, filtered, imaged, and corrected to meet standards
3. **Testing**: Data undergoes integrity tests to ensure quality
4. **Analysis**: Various analyses are performed on the processed data
5. **Output Generation**: Standardized files and analysis results are generated

Sources: [model_workflow/mwf.py:476-968](), [README.md:98-167]()

## Key Components

### 1. Processing Tools

The workflow includes several key processing tools to transform raw MD data:

| Tool | Function | Purpose |
|------|----------|---------|
| `check_inputs` | Validates input files | Ensures files exist and have compatible formats |
| `filter_atoms` | Removes unwanted atoms | Typically removes water and counter ions |
| `find_safe_bonds` | Identifies stable bonds | Extracts bonds from topology or guesses from distances |
| `structure_corrector` | Fixes structural issues | Corrects elements and ensures bond coherence |
| `image_and_fit` | Corrects trajectory | Ensures molecules stay whole across periodic boundaries |
| `generate_map` | Creates residue mappings | Maps residues to reference databases |
| `generate_topology` | Standardizes topology | Creates a common format for topology information |
| `generate_metadata` | Creates metadata | Prepares data about the simulation for the database |

Sources: [model_workflow/mwf.py:15-39]()

### 2. Analysis Modules

The workflow provides a comprehensive set of analysis capabilities:

| Category | Analyses | Description |
|----------|----------|-------------|
| Structural | RMSD, RMSF, RGYR | Basic structural measurements |
| Conformational | PCA, Clusters | Advanced conformational analysis |
| Energetic | Energies, SASA | Energy calculations and surface area |
| Interaction | Hydrogen bonds, Pockets | Analysis of molecular interactions |
| Membrane | Thickness, Area per lipid | Specialized membrane analyses |
| Advanced | Markov models, Helical parameters | Sophisticated analyses |

Sources: [model_workflow/mwf.py:57-80]()

### 3. Testing Framework

The workflow incorporates a robust testing system to ensure data integrity:

```mermaid
flowchart LR
    subgraph "Test Categories"
        structure["Structure Tests"]
        topology["Topology Tests"]
        trajectory["Trajectory Tests"]
    end
    
    subgraph "Key Tests"
        stable["stable_bonds\nStable bonds test"]
        coherent["coherent_bonds\nCoherent bonds test"]
        integrity["trajectory_integrity\nNo sudden jumps"]
        elements["correct_elements\nValid elements"]
        refseq["reference_sequence\nSequence matching"]
        interact["stable_interactions\nInteractions exist"]
    end
    
    subgraph "Test Actions"
        register["Register.update_test()\nRecord test result"]
        warning["Register.add_warning()\nLog warnings"]
        mercy["Project.mercy\nAllow test to fail"]
        trust["Project.trust\nSkip test"]
    end
    
    structure --> stable
    structure --> coherent
    structure --> elements
    
    topology --> stable
    topology --> coherent
    
    trajectory --> integrity
    trajectory --> interact
    
    stable & coherent & integrity & elements & refseq & interact --> register
    register --> warning
    mercy --> register
    trust --> register
</mermaid>

The testing framework is designed to validate the integrity of MD data, with options to skip tests or allow them to fail with warnings.

Sources: [README.md:171-243](), [model_workflow/utils/constants.py:190-234]()

## Workflow Execution

The MDDB-workflow is typically executed through the command-line interface, which invokes a sequence of operations:

```mermaid
sequenceDiagram
    participant User
    participant CLI as "mwf CLI"
    participant P as "Project"
    participant MD as "MD"
    participant Tools as "Processing Tools"
    participant Analyses as "Analysis Modules"
    
    User->>CLI: mwf run -top topology.prmtop -traj trajectory.xtc
    CLI->>P: Create Project(directory, inputs)
    P->>MD: Create MD objects for each directory
    
    loop For each MD
        MD->>Tools: check_inputs()
        MD->>Tools: filter_atoms()
        MD->>Tools: find_safe_bonds()
        MD->>Tools: structure_corrector()
        MD->>Tools: image_and_fit()
        
        loop For each test
            MD->>MD: Run test (e.g., is_trajectory_integral())
            alt Test failed and no mercy
                MD-->>P: Report failure
                P-->>CLI: Abort execution
                CLI-->>User: Display error
            end
        end
        
        Note over MD,Tools: If all tests pass or are allowed to fail
        
        MD->>Tools: generate_protein_mapping()
        MD->>Tools: process_interactions()
        MD->>Tools: generate_metadata()
        
        loop For each analysis
            MD->>Analyses: Run analysis (e.g., rmsds())
            Analyses-->>MD: Analysis results
            MD->>Tools: Save analysis to JSON
        end
    end
    
    P-->>CLI: Report completion
    CLI-->>User: Display success message
</mermaid>

The execution follows these main steps:

1. The command-line interface (`mwf`) parses arguments and initiates a Project
2. The Project creates MD objects for each directory to be processed
3. Each MD goes through processing steps (filtering, correcting, etc.)
4. Tests are run to validate the processed data
5. If tests pass or are allowed to fail, analyses are performed
6. Results are saved to standardized output files

Sources: [model_workflow/mwf.py:89-98](), [README.md:98-167]()

## Integration with MDDB Database

The processed data is prepared for upload to the MDDB database:

1. **Standard Files**: `structure.pdb`, `trajectory.xtc`, and `topology.json` are the core output files
2. **Metadata**: `metadata.json` contains information about the simulation, authors, and processing details
3. **Analysis Results**: Various JSON files containing analysis results are generated

After processing with the MDDB-workflow, files can be uploaded to the database using the separate [MDDB-loader](https://github.com/mmb-irb/MDDB-loader) tool.

Sources: [README.md:1-5](), [model_workflow/utils/constants.py:130-175]()

---