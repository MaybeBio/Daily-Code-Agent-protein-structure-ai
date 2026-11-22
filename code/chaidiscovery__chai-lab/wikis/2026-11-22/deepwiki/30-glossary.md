# Glossary

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [README.md](README.md)
- [chai_lab/chai1.py](chai_lab/chai1.py)
- [chai_lab/data/dataset/inference_dataset.py](chai_lab/data/dataset/inference_dataset.py)
- [chai_lab/data/dataset/msas/colabfold.py](chai_lab/data/dataset/msas/colabfold.py)
- [chai_lab/data/dataset/msas/utils.py](chai_lab/data/dataset/msas/utils.py)
- [chai_lab/data/io/cif_utils.py](chai_lab/data/io/cif_utils.py)
- [chai_lab/data/io/pdb_utils.py](chai_lab/data/io/pdb_utils.py)
- [chai_lab/data/parsing/msas/aligned_pqt.py](chai_lab/data/parsing/msas/aligned_pqt.py)
- [chai_lab/data/parsing/restraints.py](chai_lab/data/parsing/restraints.py)
- [chai_lab/data/parsing/templates/m8.py](chai_lab/data/parsing/templates/m8.py)
- [chai_lab/data/residue_constants.py](chai_lab/data/residue_constants.py)
- [chai_lab/data/sources/rdkit.py](chai_lab/data/sources/rdkit.py)
- [examples/msas/predict_with_msas.py](examples/msas/predict_with_msas.py)
- [tests/test_cif_utils.py](tests/test_cif_utils.py)
- [tests/test_inference_dataset.py](tests/test_inference_dataset.py)
- [tests/test_rdkit.py](tests/test_rdkit.py)
- [tests/test_restraints.py](tests/test_restraints.py)

</details>



This glossary defines technical terms, internal data structures, and algorithmic concepts used throughout the Chai-1 codebase. It serves as a reference for engineers to map biological and mathematical concepts to their specific implementations in the `chai-lab` repository.

## Core Model Concepts

### Trunk Recycling
A technique where the model's trunk (the main representation-learning component) is executed multiple times, with the outputs of one pass used as inputs for the next. This allows the model to refine its internal representation before passing it to the diffusion head.
*   **Implementation**: Controlled in the inference loop within `run_folding_on_context` [chai_lab/chai1.py:1078-1091]().
*   **Sources**: [chai_lab/chai1.py:1078-1091]()

### Diffusion Loop
The process of iteratively denoising 3D coordinates from a random distribution to a structured molecular conformation. Chai-1 uses a specific noise schedule for this process.
*   **Implementation**: `InferenceNoiseSchedule` [chai_lab/model/diffusion_schedules.py:101]() is used within the sampling loop in `run_folding_on_context` [chai_lab/chai1.py:1093-1135]().
*   **Sources**: [chai_lab/chai1.py:101-1135]()

### Confidence Scoring (pLDDT, PAE, PDE)
Metrics used to estimate the quality of the predicted structure.
*   **pLDDT**: Predicted Local Distance Difference Test. Measures local confidence at the residue/token level.
*   **PAE**: Predicted Aligned Error. Estimates the error in the relative position of two residues.
*   **PDE**: Predicted Distance Error.
*   **Implementation**: Calculated in `get_scores` and `rank` [chai_lab/ranking/rank.py:104]().
*   **Sources**: [chai_lab/chai1.py:104]()

## Data Structures & Entities

### AllAtomFeatureContext
The primary "hub" object that aggregates all features required for model inference, including sequence information, MSAs, templates, and restraints.
*   **Implementation**: `AllAtomFeatureContext` [chai_lab/data/dataset/all_atom_feature_context.py:26]().
*   **Sources**: [chai_lab/chai1.py:26-27]()

### AllAtomStructureContext
Represents the structural state of a complex, including 3D coordinates, atom types, and bonding information. It is often merged from multiple `Chain` objects.
*   **Implementation**: `AllAtomStructureContext` [chai_lab/data/dataset/structure/all_atom_structure_context.py:41]().
*   **Key Method**: `merge` [tests/test_inference_dataset.py:80-82]() combines multiple chains into a single context.
*   **Sources**: [chai_lab/chai1.py:41-43](), [tests/test_inference_dataset.py:80-82]()

### PDBContext
A tensor-based representation of a molecular complex used specifically for I/O operations and PDB/CIF generation.
*   **Implementation**: `PDBContext` [chai_lab/data/io/pdb_utils.py:19-31]().
*   **Data Flow**: Converted from model output batches via `pdb_context_from_batch` [chai_lab/data/io/pdb_utils.py:48-63]().
*   **Sources**: [chai_lab/data/io/pdb_utils.py:19-63]()

### EntityType
An enumeration defining the types of molecules supported by the system.
*   **Values**: `PROTEIN`, `RNA`, `DNA`, `LIGAND`, `MANUAL_GLYCAN`.
*   **Implementation**: `EntityType` [chai_lab/data/parsing/structure/entity_type.py:100]().
*   **Sources**: [chai_lab/chai1.py:100](), [chai_lab/data/dataset/inference_dataset.py:108-127]()

## Data Formats & I/O

### .aligned.pqt (Aligned Parquet)
A specialized Parquet format used by Chai-1 to store Multiple Sequence Alignments (MSAs). It includes metadata like `source_database` and `pairing_key` (often a taxonomic ID) to facilitate cross-chain MSA pairing.
*   **Implementation**: `AlignedParquetModel` [chai_lab/data/parsing/msas/aligned_pqt.py:37-44]().
*   **Parsing**: `parse_aligned_pqt_to_msa_context` [chai_lab/data/parsing/msas/aligned_pqt.py:63-139]().
*   **Sources**: [chai_lab/data/parsing/msas/aligned_pqt.py:37-139]()

### .m8 (MMseqs2 Alignment Format)
A tab-separated format used to describe template hits found during a sequence search.
*   **Implementation**: Parsed by `parse_m8_file` [chai_lab/data/parsing/templates/m8.py:22-46]().
*   **Sources**: [chai_lab/data/parsing/templates/m8.py:22-46]()

### .apkl (Antipickle)
A serialization format used for caching conformers. It is a safer and more robust alternative to standard Python pickles.
*   **Usage**: Loading cached conformers in `RefConformerGenerator` [chai_lab/data/sources/rdkit.py:60-73]().
*   **Sources**: [chai_lab/data/sources/rdkit.py:60-73]()

## Feature Generation Terms

### MSAContext
Contains tokenized MSA sequences, deletion counts, and taxonomic pairing information.
*   **Implementation**: `MSAContext` [chai_lab/data/dataset/msas/msa_context.py:37]().
*   **Subsampling**: Handled by `subsample_and_reorder_msa_feats_n_mask` [chai_lab/data/dataset/msas/utils.py:51-86]().
*   **Sources**: [chai_lab/chai1.py:37-40](), [chai_lab/data/dataset/msas/utils.py:51-86]()

### RestraintContext
Encapsulates user-defined physical constraints (contacts, pockets, covalent bonds) that guide the folding process.
*   **Implementation**: `RestraintContext` [chai_lab/data/dataset/constraints/restraint_context.py:28]().
*   **Parsing**: `parse_pairwise_table` [chai_lab/data/parsing/restraints.py:173-187]().
*   **Sources**: [chai_lab/chai1.py:28-31](), [chai_lab/data/parsing/restraints.py:173-187]()

### Conformer Data
Idealized 3D coordinates and metadata (element, charge, atom names) for a single residue or ligand, typically generated via RDKit.
*   **Implementation**: `ConformerData` [chai_lab/data/parsing/structure/residue.py:21]().
*   **Generation**: `RefConformerGenerator.generate` [chai_lab/data/sources/rdkit.py:144-175]() uses `ETKDGv3` for ligands.
*   **Sources**: [chai_lab/data/sources/rdkit.py:21-175]()

## System Diagrams

### Data Mapping: Input to Code Entities
This diagram illustrates how raw user inputs (FASTA, SMILES) are transformed into internal code objects.

Structure Prediction Input Flow
```mermaid
graph TD
    subgraph "Natural Language / File Space"
        F["input.fasta"]
        S["SMILES string"]
        R["restraints.csv"]
    end

    subgraph "Code Entity Space"
        In["Input Class [chai_lab/data/dataset/inference_dataset.py]"]
        AED["AllAtomEntityData [chai_lab/data/parsing/structure/all_atom_entity_data.py]"]
        RCG["RefConformerGenerator [chai_lab/data/sources/rdkit.py]"]
        SC["AllAtomStructureContext [chai_lab/data/dataset/structure/all_atom_structure_context.py]"]
        PI["PairwiseInteraction [chai_lab/data/parsing/restraints.py]"]
    end

    F -->|read_fasta| In
    S -->|get_lig_residues| In
    In -->|raw_inputs_to_entities_data| AED
    AED -->|AllAtomResidueTokenizer| SC
    RCG -->|provides conformers| SC
    R -->|parse_pairwise_table| PI
```
**Sources**: [chai_lab/data/dataset/inference_dataset.py:39-177](), [chai_lab/data/sources/rdkit.py:38-175](), [chai_lab/data/parsing/restraints.py:173-187]()

### Inference Pipeline: Context to Coordinates
This diagram shows the flow of data through the model components during a single inference run.

Model Execution Data Flow
```mermaid
graph TD
    subgraph "Feature Assembly"
        AFC["AllAtomFeatureContext"]
        FF["FeatureFactory [chai_lab/data/features/feature_factory.py]"]
    end

    subgraph "Model Trunk [chai_lab/chai1.py]"
        MW["ModuleWrapper"]
        TR["Trunk Recycle Loop"]
    end

    subgraph "Output Generation"
        DS["Diffusion Sampling"]
        PC["PDBContext [chai_lab/data/io/pdb_utils.py]"]
        CIF["save_to_cif [chai_lab/data/io/cif_utils.py]"]
    end

    AFC --> FF
    FF -->|forward_crop_size| MW
    MW --> TR
    TR --> DS
    DS -->|pdb_context_from_batch| PC
    PC --> CIF
```
**Sources**: [chai_lab/chai1.py:115-148](), [chai_lab/chai1.py:1078-1135](), [chai_lab/data/io/pdb_utils.py:48-63](), [chai_lab/data/io/cif_utils.py:156-172]()