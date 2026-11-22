# Advanced Topics

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/deploy.yml](.github/workflows/deploy.yml)
- [.github/workflows/run_tests.yml](.github/workflows/run_tests.yml)
- [LICENSE](LICENSE)
- [doc/source/data.rst](doc/source/data.rst)
- [doc/source/file_formats.rst](doc/source/file_formats.rst)
- [doc/source/general_overview.rst](doc/source/general_overview.rst)
- [doc/source/graph_algorithms.rst](doc/source/graph_algorithms.rst)
- [doc/source/martinize2_workflow.rst](doc/source/martinize2_workflow.rst)
- [doc/source/processors.rst](doc/source/processors.rst)
- [doc/source/technical_background.rst](doc/source/technical_background.rst)
- [pyproject.toml](pyproject.toml)

</details>



This page covers advanced topics for power users and developers working with the vermouth-martinize system. While the [Basic Usage](#5.1) and other tutorial pages cover common workflows, this section delves into the technical details, file formats, customization options, and development practices essential for extending the system's capabilities.

## File Formats

Vermouth uses specialized file formats to define force fields, mappings between force fields, and molecule descriptions. Understanding these formats is essential for creating custom force fields or modifying existing ones.

### Force Field Files (.ff)

These files define blocks, links, and modifications that describe how atoms interact. The file format uses a directive-based structure with sections and subsections enclosed in square brackets.

**Force Field File Structure**

```mermaid
graph TD
    FF["Force Field File (.ff)"]
    
    FF --> Macros["[macros]<br>Substitution patterns"]
    FF --> Variables["[variables]<br>Force field parameters"]
    FF --> Citations["[citations]<br>References to bibtex"]
    FF --> Blocks["[moleculetype]<br>Residue templates"]
    FF --> Links["[links]<br>Inter-residue connections"]
    FF --> Mods["[modification]<br>PTMs and protonation states"]
    
    Blocks --> BlockAtoms["[atoms]<br>Atom definitions"]
    Blocks --> BlockEdges["[edges]<br>Bond connections"]
    Blocks --> BlockInteractions["[interaction_name]<br>Bonds, angles, dihedrals, etc."]
    
    Links --> LinkAtoms["[atoms]<br>Atom attribute overrides"]
    Links --> LinkPatterns["[patterns]<br>Pattern matching rules"]
    Links --> LinkFeatures["[features]<br>Feature flags"]
    Links --> LinkEdges["[edges]<br>Bond connections"]
    Links --> LinkInteractions["[interaction_name]<br>Inter-residue parameters"]
```

Sources: [doc/source/file_formats.rst:1-395]()

### Mapping Files (.map & .mapping)

Mapping files define conversions between force fields, typically from a higher resolution (atomistic) to a lower resolution (coarse-grained) representation.

**Mapping File Structure**

```mermaid
graph TD
    MAP["Mapping Files"]
    
    MAP --> MapFile[".map format<br>Block mappings"]
    MAP --> MappingFile[".mapping format<br>Modification mappings"]
    
    MapFile --> MolDir["[molecule]<br>Residue name"]
    MapFile --> FromDir["[from]<br>Origin force field"]
    MapFile --> ToDir["[to]<br>Target force field"]
    MapFile --> MartiniDir["[martini]<br>Coarse-grained bead names"]
    MapFile --> AtomsDir["[atoms]<br>Atom-to-bead mappings"]
    
    MappingFile --> ModDir["[modification]<br>PTM specification"]
    MappingFile --> MFromDir["[from]<br>Origin force field"]
    MappingFile --> MToDir["[to]<br>Target force field"]
    MappingFile --> FromBlocksDir["[from blocks]<br>Modification name in origin FF"]
    MappingFile --> ToBlocksDir["[to blocks]<br>Modification name in target FF"]
    MappingFile --> MappingDir["[mapping]<br>Atom-to-bead mapping rules"]
```

Sources: [doc/source/file_formats.rst:409-546]()

## Custom Force Fields

Creating custom force fields allows you to define new molecules, interactions, or modify existing ones. This is essential for working with non-standard molecules or implementing alternative parametrizations.

### Directory Structure

A typical directory structure for a custom force field follows this pattern:

```
my_forcefield/
├── force_fields/
│   └── my_forcefield/
│       ├── my_forcefield.ff     # Main force field file
│       ├── aminoacids.ff        # Residue definitions
│       ├── modifications.ff     # PTMs and alternate states
│       └── citations.bib        # References
└── mappings/
    ├── my_forcefield_to_martini3.map   # Mapping to Martini
    ├── charmm36_to_my_forcefield.map   # Mapping from atomistic
    └── modifications/
        └── phosphorylation.mapping     # PTM mappings
```

### Force Field Implementation

To implement a custom force field, you need to create the following components:

1. **Blocks**: Define all residues/molecules your force field supports
2. **Links**: Define interactions between residues (e.g., peptide bonds)
3. **Modifications**: Define altered states (e.g., PTMs, protonation states)
4. **Mappings**: Create mappings to/from existing force fields

**Force Field Loading Process**

```mermaid
flowchart TD
    FFDir["force_field_directory/.ff files"] --> FFParser["vermouth.ffinput.FFDirector"]
    ITPDir["ITP Files (Gromacs format)"] --> ITPParser["vermouth.gmx.itp_read.ITPDirector"]
    
    FFParser --> FF["vermouth.forcefield.ForceField"]
    ITPParser --> FF
    
    FF --> Blocks["Force Field Blocks<br>(residue templates)"]
    FF --> Links["Force Field Links<br>(connections)"]
    FF --> Modifications["Force Field Modifications<br>(PTMs)"]
    FF --> Variables["Force Field Variables<br>(parameters)"]
    
    MappingDir["mapping_directory/.map files"] --> MapParser["vermouth.map_parser.MappingDirector"]
    MappingDir2["mapping_directory/.mapping files"] --> MapParser
    
    MapParser --> Mappings["Mapping objects"]
    
    FF --> DoMapping["vermouth.processors.do_mapping.DoMapping"]
    Mappings --> DoMapping
```

Sources: [doc/source/data.rst:93-105](), [doc/source/martinize2_workflow.rst:197-246]()

## Development Guide

This section covers information for developers who want to contribute to the vermouth-martinize project.

### CI/CD Pipeline

The project uses GitHub Actions for continuous integration and deployment, defined in the `.github/workflows` directory.

**CI/CD Workflow**

```mermaid
flowchart TD
    PR["Pull Request / Push"] --> Jobs["GitHub Actions Jobs"]
    
    Jobs --> Build["Build Job<br>(Multiple Python versions)"]
    Jobs --> Lint["Lint Job<br>(Pylint checks)"]
    Jobs --> Docs["Documentation Job<br>(Sphinx build)"]
    
    Build --> RunTests["Run Tests<br>(pytest)"]
    RunTests --> Coverage["Generate Coverage Report"]
    
    Lint --> RunPylint["Run Pylint<br>Minimum score: 8.0/10"]
    
    Docs --> BuildDocs["Build Sphinx Docs"]
    
    RunTests --> Deploy["Deploy Job<br>(Requires all jobs success)"]
    Coverage --> Deploy
    RunPylint --> Deploy
    BuildDocs --> Deploy
    
    Deploy --> PyPI["Deploy to PyPI<br>(For releases only)"]
```

Sources: [.github/workflows/run_tests.yml:1-154](), [.github/workflows/deploy.yml:1-151]()

### Testing Framework

The project uses pytest for unit and integration testing, with coverage reporting through the coverage.py tool.

#### Running Tests

To run tests locally:

```bash
# Install test dependencies
pip install -r requirements-tests.txt

# Run tests
pytest -vv

# Generate coverage report
coverage run $(which pytest) -vv
coverage report
```

#### Test Organization

Tests are located in the `vermouth/tests/` directory, organized to mirror the structure of the main code. The project uses hypothesis for property-based testing of complex behaviors.

Sources: [pyproject.toml:9-17](), [.github/workflows/run_tests.yml:52-58]()

## Graph Algorithms

Vermouth represents molecules as graphs, where atoms are nodes and bonds are edges. This enables sophisticated graph operations for molecule manipulation and identification.

**Graph Algorithm Hierarchy**

```mermaid
graph TD
    MolGraph["Molecule Graph<br>(vermouth.molecule.Molecule)"]
    
    MolGraph --> Isomorphism["Graph Isomorphism<br>Exact Structural Matching"]
    MolGraph --> Subgraph["Subgraph Isomorphism<br>Pattern Matching"]
    MolGraph --> MCIS["Maximum Common Induced Subgraph<br>Best Match Finding"]
    
    Isomorphism --> ISMAGS["ISMAGS Algorithm<br>(vermouth.ismags)"]
    ISMAGS --> SymmetryHandling["Handles Molecular Symmetry"]
    
    Subgraph --> LinkMatching["Link Pattern Matching<br>(vermouth.processors.do_links)"]
    Subgraph --> ModMatching["Modification Detection<br>(vermouth.processors.canonicalize_modifications)"]
    
    MCIS --> RepairGraph["Graph Repair<br>(vermouth.processors.repair_graph)"]
    MCIS --> AtomIdentification["Atom Name Assignment"]
```

Sources: [doc/source/graph_algorithms.rst:1-131]()

The various isomorphism algorithms are used throughout the martinize2 pipeline:

1. **Graph isomorphism**: Finding exactly matching graphs
2. **Subgraph isomorphism**: Finding molecular patterns within larger structures
3. **Induced subgraph isomorphism**: Finding patterns while preserving connection patterns
4. **Maximum common induced subgraph**: Finding the largest overlap between two graphs

The ISMAGS algorithm efficiently handles symmetry in molecular graphs, which is particularly important for large molecules with many equivalent atoms.

## Processor Pipeline

Vermouth uses a modular processor-based architecture for transforming molecules. Each processor performs a specific task in the pipeline, allowing for flexible composition of transformation steps.

**Processor Architecture**

```mermaid
flowchart TD
    Processor["vermouth.processors.processor.Processor<br>Base class"]
    
    Processor --> RunSystem["run_system()<br>Process entire system"]
    Processor --> RunMolecule["run_molecule()<br>Process single molecule"]
    
    PipelineClasses["Processor implementations"] --> PDBInput["vermouth.processors.pdb_reader.PDBInput<br>Read PDB files"]
    PipelineClasses --> MakeBonds["vermouth.processors.make_bonds.MakeBonds<br>Create bond graph"]
    PipelineClasses --> RepairGraph["vermouth.processors.repair_graph.RepairGraph<br>Fix missing atoms"]
    PipelineClasses --> CanonMods["vermouth.processors.canonicalize_modifications.CanonicalizeModifications<br>Identify PTMs"]
    PipelineClasses --> DoMapping["vermouth.processors.do_mapping.DoMapping<br>Resolution transformation"]
    PipelineClasses --> DoLinks["vermouth.processors.do_links.DoLinks<br>Apply links"]
    PipelineClasses --> RubberBand["vermouth.processors.apply_rubber_band.ApplyRubberBand<br>Elastic network"]
    
    PipelineFlow["Martinize2 Pipeline"] --> Step1["1. Read input files (PDB/GRO)"]
    Step1 --> Step2["2. Repair the input graph"]
    Step2 --> Step3["3. Resolution transformation"]
    Step3 --> Step4["4. Apply Links"]
    Step4 --> Step5["5. Post-processing (elastic networks, Go models)"]
    Step5 --> Step6["6. Write output"]
```

Sources: [doc/source/processors.rst:1-19](), [doc/source/martinize2_workflow.rst:1-296]()

To implement a custom processor:

1. Subclass `vermouth.processors.processor.Processor`
2. Implement either `run_molecule` (preferred) or `run_system` method
3. Return a modified molecule or system

## License and Contributors

The vermouth-martinize project is licensed under the Apache License 2.0. This permissive license allows for both academic and commercial use, with appropriate attribution.

Sources: [LICENSE:1-206]()

## Distribution and Packaging

The project uses Python Build and Package (PBP) for building and distributing the package. The package is available on PyPI and can be installed using pip:

```bash
pip install vermouth
```

The package defines several requirements files:
- `requirements-tests.txt`: Dependencies for testing
- `requirements-docs.txt`: Dependencies for building documentation

Sources: [pyproject.toml:1-8](), [.github/workflows/run_tests.yml:45-52]()

---