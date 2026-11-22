# Protein Data Representations

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [esm/sdk/api.py](esm/sdk/api.py)
- [esm/utils/structure/metrics.py](esm/utils/structure/metrics.py)
- [esm/utils/structure/protein_chain.py](esm/utils/structure/protein_chain.py)
- [esm/utils/structure/protein_complex.py](esm/utils/structure/protein_complex.py)

</details>



Proteins in the ESM codebase are represented across multiple levels of abstraction, ranging from raw structural files (PDB/mmCIF) to high-level SDK objects for API interactions, and finally to tensor representations used by the transformer models. This multi-layered approach ensures that structural biology data is consistently handled while remaining compatible with deep learning workflows.

### Representation Layers Overview

The codebase transitions between three primary representation spaces:

1.  **File/Structural Space**: Raw data parsed from `.pdb` or `.mmcif` files using libraries like `biotite`.
2.  **SDK Entity Space**: Pythonic objects like `ESMProtein` and `ProteinChain` that encapsulate sequence, structure, and metadata.
3.  **Tensor/Model Space**: Tokenized integer tensors and coordinate tensors (Atom37) used as inputs to ESMC, ESM3, and ESMFold2.

The following diagram illustrates the flow of data through these representations:

#### Protein Data Flow Diagram
```mermaid
graph TD
    subgraph "File Space"
        PDB[".pdb File"]
        MMCIF[".mmcif File"]
    end

    subgraph "SDK Entity Space (Code Entities)"
        PC["ProteinChain (esm.utils.structure.protein_chain)"]
        PComp["ProteinComplex (esm.utils.structure.protein_complex)"]
        ESMP["ESMProtein (esm.sdk.api)"]
    end

    subgraph "Model Space (Tensors)"
        EPT["ESMProteinTensor (esm.sdk.api)"]
        SPI["StructurePredictionInput (esm.sdk.api)"]
    end

    PDB --> PC
    MMCIF --> PComp
    PC --> ESMP
    PComp --> ESMP
    ESMP -- "encoding.tokenize" --> EPT
    ESMP -- "ESMFold2InputBuilder" --> SPI
```
**Sources:** [esm/sdk/api.py:27-137](), [esm/utils/structure/protein_chain.py:143-155](), [esm/utils/structure/protein_complex.py:44-55]()

---

### Core Data Entities

#### ProteinChain & Atom37 Format
The `ProteinChain` class is the fundamental unit for single-chain structural data [esm/utils/structure/protein_chain.py:149-167](). It utilizes the **Atom37** indexing scheme, which maps every residue to a fixed-size 37-atom vector, ensuring a consistent tensor shape regardless of the amino acid type.

*   **Key Capabilities**: PDB/mmCIF parsing, geometric utilities (RMSD, lDDT), and coordinate normalization.
*   **For details, see [ProteinChain & Atom37 Format](#4.1)**.

#### ProteinComplex & MolecularComplex
For multi-chain assemblies and heterogeneous systems (including DNA, RNA, and ligands), the codebase provides `ProteinComplex` and `MolecularComplex`.
*   **ProteinComplex**: Handles assemblies of multiple `ProteinChain` objects [esm/utils/structure/protein_complex.py:150-167]().
*   **MolecularComplex**: A more generalized, flat representation of atoms designed for all-atom modeling tasks.
*   **For details, see [ProteinComplex & MolecularComplex](#4.2)**.

#### ESMProtein (SDK Interface)
The `ESMProtein` class is the primary entry point for users of the ESM SDK [esm/sdk/api.py:27-54](). It acts as a container for multiple "tracks" of data:
*   **Sequence**: Amino acid string [esm/sdk/api.py:29]().
*   **Coordinates**: `torch.Tensor` of shape `(L, 37, 3)` [esm/sdk/api.py:33]().
*   **Annotations**: Secondary structure (SS8), SASA, and InterPro function annotations [esm/sdk/api.py:30-32]().

**Sources:** [esm/sdk/api.py:27-54](), [esm/utils/structure/protein_chain.py:149-167]()

---

### Transitioning to Model Tensors

To perform inference, SDK objects must be converted into tensors. This process involves tokenizing categorical tracks (like sequence and function) and preparing coordinate frames for structural tracks.

#### Data Conversion Mapping
| From | To | Mechanism |
| :--- | :--- | :--- |
| `.pdb` / `.mmcif` | `ESMProtein` | `ESMProtein.from_pdb()` [esm/sdk/api.py:69-75]() |
| `ESMProtein` | `ESMProteinTensor` | `esm.utils.encoding.tokenize_protein` [esm/sdk/api.py:236-240]() |
| `ESMProtein` | `StructurePredictionInput` | `ESMFold2InputBuilder.build()` [esm/sdk/api.py:537-540]() |

#### Structure Prediction Input Builder
The `ESMFold2InputBuilder` prepares complex payloads for structure prediction [esm/sdk/api.py:537-550](). It handles the assembly of Multiple Sequence Alignments (MSAs), templates, and conditioning (e.g., pocket or distogram constraints) into a `StructurePredictionInput` object.

*   **For details, see [Structure Prediction Input Builder](#4.3)**.

#### Code-to-System Mapping
The following diagram bridges the high-level representation concepts to the specific classes and methods used to manipulate them.

```mermaid
classDiagram
    class ProteinDataRepresentation {
        <<Interface>>
    }
    class ESMProtein {
        +sequence: str
        +coordinates: Tensor
        +from_pdb()
        +to_protein_chain()
    }
    class ProteinChain {
        +atom37_positions: ndarray
        +atom37_mask: ndarray
        +to_pdb()
    }
    class ESMProteinTensor {
        +sequence_tokens: Tensor
        +structure_tokens: Tensor
    }
    
    ESMProtein ..|> ProteinDataRepresentation
    ESMProtein --> ProteinChain : "converts via"
    ESMProtein --> ESMProteinTensor : "tokenized into"
```
**Sources:** [esm/sdk/api.py:27-49](), [esm/sdk/api.py:195-210](), [esm/utils/structure/protein_chain.py:149-167]()

---