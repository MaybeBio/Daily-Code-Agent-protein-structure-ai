# ESMFold2 – All-Atom Structure Prediction

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [cookbook/tutorials/binder_design.ipynb](cookbook/tutorials/binder_design.ipynb)
- [cookbook/tutorials/esmc_sae_feature_interpretation.ipynb](cookbook/tutorials/esmc_sae_feature_interpretation.ipynb)
- [esm/models/esmfold2/conformers.py](esm/models/esmfold2/conformers.py)
- [esm/models/esmfold2/constants.py](esm/models/esmfold2/constants.py)
- [esm/models/esmfold2/output.py](esm/models/esmfold2/output.py)
- [esm/models/esmfold2/paired_msa.py](esm/models/esmfold2/paired_msa.py)
- [esm/models/esmfold2/prepare_input.py](esm/models/esmfold2/prepare_input.py)
- [esm/models/esmfold2/processor.py](esm/models/esmfold2/processor.py)
- [esm/models/esmfold2/types.py](esm/models/esmfold2/types.py)
- [esm/utils/constants/models.py](esm/utils/constants/models.py)

</details>



ESMFold2 is a diffusion-based structure prediction pipeline designed for high-accuracy all-atom modeling of proteins, nucleic acids, and small molecule ligands. Unlike the original ESMFold which used a folding trunk to predict coordinates directly, ESMFold2 leverages a generative approach to handle complex hetero-complexes and multi-chain assemblies.

## Pipeline Overview

The ESMFold2 pipeline follows a structured flow from high-level sequence and constraint definitions to low-level tensor representations, culminating in a diffusion-based structure generation process.

### Code Entity Space to System Flow
The following diagram bridges the high-level input types to the internal processing classes used to prepare data for the model.

```mermaid
graph TD
    subgraph "Input Space (StructurePredictionInput)"
        PI["ProteinInput"]
        DI["DNAInput"]
        RI["RNAInput"]
        LI["LigandInput"]
    end

    SPI["StructurePredictionInput"] --> CLEAN["clean_esmfold2_input"]
    CLEAN --> BUILDER["ESMFold2InputBuilder"]
    
    subgraph "Internal Processing"
        BUILDER --> PREP["prepare_esmfold2_input"]
        PREP --> CCD["load_ccd"]
        PREP --> MSA_PROC["construct_paired_msa"]
    end

    PREP --> TENSORS["Feature Tensors (torch.Tensor)"]
    PREP --> CINFO["list[ChainInfo]"]

    TENSORS --> MODEL["ESMFold2 Model Forward"]
    CINFO --> OUTPUT["build_molecular_complex_from_features"]
```
Sources: [esm/models/esmfold2/processor.py:143-186](), [esm/models/esmfold2/prepare_input.py:1-5]()

## Input Specification

The entry point for all predictions is the `StructurePredictionInput` dataclass. It serves as a container for sequences, Multiple Sequence Alignments (MSAs), and spatial conditioning.

### Support for Hetero-complexes
ESMFold2 supports a variety of molecular inputs defined in `esm.models.esmfold2.types`:
*   **`ProteinInput`**: Supports amino acid sequences, MSAs, and post-translational `Modification` objects [esm/models/esmfold2/types.py:11-19]().
*   **`DNAInput` / `RNAInput`**: Supports nucleic acid sequences [esm/models/esmfold2/types.py:14-18]().
*   **`LigandInput`**: Supports small molecules defined by Chemical Component Dictionary (CCD) codes [esm/models/esmfold2/types.py:15-19]().

### Conditioning and Constraints
Predictions can be guided by external information:
*   **`DistogramConditioning`**: Provides distance constraints between specific atoms [esm/models/esmfold2/types.py:13-19]().
*   **`CovalentBond`**: Explicitly defines bonds between entities, such as protein-ligand linkages [esm/models/esmfold2/types.py:12-19]().

## Input Preparation & Tokenization

The `ESMFold2InputBuilder` orchestrates the conversion of high-level inputs into model-ready tensors.

### The Cleaning Phase
Before tokenization, `clean_esmfold2_input` handles sequence normalization. It expands polyprotein sequences (separated by `|`) into individual `ProteinInput` objects and groups identical sequences to optimize the MSA representation [esm/models/esmfold2/processor.py:86-181](). This function also converts `|` chainbreak tokens to `:` in the sequence and raises an error if `covalent_bonds` are provided with chainbreaks [esm/models/esmfold2/processor.py:94-112]().

### Atom and Token Generation
The core logic resides in `prepare_esmfold2_input`. This function iterates through the provided sequences to build two primary metadata lists:
1.  **`TokenInfo`**: Metadata for every residue or atom-token (in the case of ligands/modifications), tracking `asym_id`, `entity_id`, and `res_type` [esm/models/esmfold2/prepare_input.py:81-93]().
2.  **`AtomInfo`**: Detailed metadata for every atom, including element symbols, atomic numbers, and idealized coordinates retrieved from the CCD [esm/models/esmfold2/prepare_input.py:68-78]().

The `tokenize_protein` function handles protein sequences, applying modifications and generating tokens and atoms. Modified residues are atom-tokenized (one token per atom), while standard residues produce one token with all heavy atoms [esm/models/esmfold2/prepare_input.py:190-205](). Similarly, `tokenize_dna`, `tokenize_rna`, and `tokenize_ligand` handle their respective molecule types.

### CCD Conformer Loading
For ligands and modified residues, ESMFold2 uses the Chemical Component Dictionary (CCD). The `load_ccd` utility downloads or loads a serialized RDKit-based dictionary to provide "Computed" or "Ideal" coordinates for atom-level initialization [esm/models/esmfold2/conformers.py:36-76](). The `get_idealized_atom_pos` and `get_ligand_idealized_atom_pos` functions retrieve these positions based on residue type or name and atom name [esm/models/esmfold2/conformers.py:155-192]().

Sources: [esm/models/esmfold2/prepare_input.py:176-203](), [esm/models/esmfold2/processor.py:143-152]()

## Multiple Sequence Alignment (MSA)

ESMFold2 utilizes paired MSAs for multi-chain protein complexes. The `construct_paired_msa` function is responsible for this process [esm/models/esmfold2/paired_msa.py:105-105]().

| Feature | Implementation |
| :--- | :--- |
| **Taxonomy Pairing** | Uses `key=N` tokens in FASTA headers to pair sequences from the same organism [esm/models/esmfold2/paired_msa.py:3-7](). The `_taxonomy_from_header` function extracts this information [esm/models/esmfold2/paired_msa.py:35-39]().
| **Block-Diagonalization** | Unpaired sequences are placed in chain-specific blocks to prevent false inter-chain correlations [esm/models/esmfold2/paired_msa.py:192-200]().
| **Insertion Handling** | Strips lowercase letters and `.` from A3M formats, storing them as `deletion_count` [esm/models/esmfold2/paired_msa.py:42-78](). The `msa_to_res_type_and_deletions` function performs this conversion [esm/models/esmfold2/paired_msa.py:42-87]().

The `construct_paired_msa` function takes `chain_msas`, `chain_query_res_types`, `token_asym_ids`, and `token_res_ids` as input to build the final MSA features [esm/models/esmfold2/paired_msa.py:105-120](). It returns `msa_residues`, `deletion_value`, and `is_paired` arrays [esm/models/esmfold2/paired_msa.py:125-130]().

Sources: [esm/models/esmfold2/paired_msa.py:86-121]()

## Output Construction

After the model performs the forward pass (diffusion sampling), the raw coordinate tensors must be mapped back to a structured molecular format.

### MolecularComplex Assembly
The `build_molecular_complex_from_features` function performs the following steps:
1.  **Filtering**: Applies the `atom_mask` to remove non-existent or unpredicted atoms [esm/models/esmfold2/output.py:33-37]().
2.  **Mapping**: Uses `chain_infos` (the metadata generated during input prep) to assign atoms to their respective residues and chains [esm/models/esmfold2/output.py:52-56]().
3.  **Ligand Collapse**: For non-polymer chains (`MOL_TYPE_NONPOLYMER`), it collapses multiple atom-tokens into a single residue entry for the final `MolecularComplex` [esm/models/esmfold2/output.py:57-82]().
4.  **Confidence Extraction**: Maps per-token pLDDT scores from the model back to the residues [esm/models/esmfold2/output.py:92-94]().

### Result Mapping
The output is encapsulated in a `MolecularComplex`, which provides methods for exporting to PDB or mmCIF formats via `esm.utils.structure.molecular_complex`.

```mermaid
classDiagram
    class StructurePredictionInput {
        +list sequences
        +DistogramConditioning distogram_conditioning
        +list covalent_bonds
    }
    class ESMFold2InputBuilder {
        +prepare_input(input)
    }
    class MolecularComplex {
        +np.ndarray atom_positions
        +np.ndarray plddt
        +list sequence
        +to_pdb()
        +to_mmcif()
    }
    StructurePredictionInput --|> ProteinInput
    StructurePredictionInput --|> DNAInput
    StructurePredictionInput --|> RNAInput
    StructurePredictionInput --|> LigandInput
    ESMFold2InputBuilder ..> StructurePredictionInput : processes
    ESMFold2InputBuilder ..> MolecularComplex : produces via output.py
```

Sources: [esm/models/esmfold2/output.py:18-126](), [esm/models/esmfold2/processor.py:10-18]()

---