# Structural Templates

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/dataset/templates/align.py](chai_lab/data/dataset/templates/align.py)
- [chai_lab/data/dataset/templates/context.py](chai_lab/data/dataset/templates/context.py)
- [chai_lab/data/dataset/templates/load.py](chai_lab/data/dataset/templates/load.py)
- [chai_lab/data/io/rcsb.py](chai_lab/data/io/rcsb.py)
- [chai_lab/data/parsing/templates/m8.py](chai_lab/data/parsing/templates/m8.py)
- [chai_lab/data/parsing/templates/template_hit.py](chai_lab/data/parsing/templates/template_hit.py)
- [chai_lab/data/sources/rdkit.py](chai_lab/data/sources/rdkit.py)
- [chai_lab/tools/kalign.py](chai_lab/tools/kalign.py)
- [tests/test_rdkit.py](tests/test_rdkit.py)

</details>



This document describes the template-based structure prediction capabilities within the Chai-1 molecular structure prediction system. Templates are known 3D structures with sequence similarity to the target sequence that can significantly improve prediction accuracy by providing structural information from homologous proteins.

## Template System Overview

Templates in Chai-1 are processed through a pipeline that parses template hits from M8 format files, downloads structures from RCSB, aligns sequences using Kalign, and extracts structural features that inform the diffusion model during structure prediction.

### Template Processing Pipeline

```mermaid
flowchart TD
    subgraph "Template Discovery"
        M8File["M8 Format File<br/>Template search results"] --> parse_m8_file["parse_m8_file()"]
        parse_m8_file --> parse_m8_to_template_hits["parse_m8_to_template_hits()"]
        parse_m8_to_template_hits --> TemplateHit["TemplateHit objects"]
    end

    subgraph "Structure Loading"
        TemplateHit --> download_cif_file["download_cif_file()"]
        download_cif_file --> gemmi_read["gemmi.read_structure()"]
        gemmi_read --> kalign_query_to_reference["kalign_query_to_reference()"]
        kalign_query_to_reference --> get_template_data["get_template_data()"]
        get_template_data --> LoadedTemplate["LoadedTemplate objects"]
    end

    subgraph "Feature Extraction"
        LoadedTemplate --> template_restype["template_restype"]
        LoadedTemplate --> template_pseudo_beta_mask["template_pseudo_beta_mask"]
        LoadedTemplate --> template_distances["template_pseudo_beta_distances"]
        LoadedTemplate --> template_unit_vector["template_unit_vector"]
        LoadedTemplate --> template_backbone_frame_mask["template_backbone_frame_mask"]
    end

    subgraph "Context Assembly"
        template_restype --> TemplateContext["TemplateContext.from_loaded_templates()"]
        template_pseudo_beta_mask --> TemplateContext
        template_distances --> TemplateContext
        template_unit_vector --> TemplateContext
        template_backbone_frame_mask --> TemplateContext
    end

    TemplateContext --> get_template_context["get_template_context()"]
    get_template_context --> AllAtomFeatureContext["AllAtomFeatureContext"]
```

Sources: [chai_lab/data/parsing/templates/m8.py:22-130](), [chai_lab/data/dataset/templates/load.py:262-411](), [chai_lab/data/dataset/templates/context.py:334-420]()

## M8 Format Template Hit Discovery

Template hits are discovered by parsing M8 format files, which contain the results of template search algorithms. The M8 format is a tab-delimited format that includes alignment statistics and coordinates.

### M8 File Parsing

```mermaid
flowchart TD
    subgraph "M8 File Format"
        M8File["M8 Format File<br/>Tab-delimited search results"] --> parse_m8_file["parse_m8_file()"]
        parse_m8_file --> DataFrame["pandas.DataFrame<br/>query_id, subject_id, pident,<br/>length, mismatch, gapopen,<br/>query_start, query_end,<br/>subject_start, subject_end,<br/>evalue, bitscore, comment"]
    end

    subgraph "Template Hit Processing"
        DataFrame --> iterate_rows["Iterate over rows"]
        iterate_rows --> split_subject["Split subject_id<br/>into hit_identifier, hit_chain"]
        split_subject --> download_cif_file["download_cif_file()"]
        download_cif_file --> gemmi_chain["gemmi.Chain.get_polymer()"]
        gemmi_chain --> kalign_query_to_reference["kalign_query_to_reference()"]
        kalign_query_to_reference --> tokenize_sequences["tokenize_sequences_to_arrays()"]
        tokenize_sequences --> TemplateHit["TemplateHit object"]
    end
```

The `parse_m8_to_template_hits` function processes each hit by:
1. Extracting PDB ID and chain ID from the `subject_id` field [chai_lab/data/parsing/templates/m8.py:79-80]().
2. Downloading the CIF file using `download_cif_file` [chai_lab/data/parsing/templates/m8.py:82-87]().
3. Parsing the structure with `gemmi.read_structure` [chai_lab/data/parsing/templates/m8.py:88-88]().
4. Aligning the hit sequence to the query using `kalign_query_to_reference` [chai_lab/data/parsing/templates/m8.py:97-97]().
5. Tokenizing the aligned sequence for model input using `tokenize_sequences_to_arrays` [chai_lab/data/parsing/templates/m8.py:101-101]().

Sources: [chai_lab/data/parsing/templates/m8.py:22-130](), [chai_lab/data/io/rcsb.py:9-18]()

## Template Hit Representation

The `TemplateHit` class represents a match between a query sequence and a known structure discovered from M8 search results. Each hit contains alignment information and indices that map between query and template positions.

```mermaid
classDiagram
    class TemplateHit {
        +query_pdb_id: str
        +query_sequence: str
        +index: int
        +pdb_id: str
        +chain_id: str
        +hit_start: int
        +hit_end: int
        +hit_tokens: Int32Tensor
        +deletion_matrix: UInt8Tensor
        +query_seq_realigned: str
        +cif_path: Path
        +hit_sequence() str
        +indices_query() Int32Tensor
        +indices_hit_within_subregion() Int32Tensor
        +indices_hit() Int32Tensor
        +hit_valid_mask() BoolTensor
        +query_start_end() tuple
    }

    note for TemplateHit "Created by parse_m8_to_template_hits()\nfrom M8 format search results"
```

### Key Properties and Methods

| Property | Type | Description |
|----------|------|-------------|
| `hit_sequence` | `str` | Amino acid sequence of the template hit [chai_lab/data/parsing/templates/template_hit.py:71-74]() |
| `indices_query` | `Int32[Tensor, "m"]` | Query residue indices corresponding to hit [chai_lab/data/parsing/templates/template_hit.py:77-83]() |
| `indices_hit` | `Int32[Tensor, "n"]` | Hit indices within full hit sequence [chai_lab/data/parsing/templates/template_hit.py:109-111]() |
| `hit_valid_mask` | `Bool[Tensor, "n"]` | Mask indicating valid positions (not gaps) [chai_lab/data/parsing/templates/template_hit.py:114-129]() |
| `query_start_end` | `tuple[int, int]` | Start and end positions in query sequence [chai_lab/data/parsing/templates/template_hit.py:132-135]() |

The `indices_hit` property accounts for insertions and deletions in the alignment by using the `deletion_matrix` and `hit_tokens` [chai_lab/data/parsing/templates/template_hit.py:92-106]().

Sources: [chai_lab/data/parsing/templates/template_hit.py:14-136]()

## Template Loading and Processing

Templates are loaded using the `get_template_data` function, which converts `TemplateHit` objects into `LoadedTemplate` objects containing the actual structural data.

### Template Loading Pipeline

```mermaid
flowchart TD
    subgraph "Input Processing"
        TemplateHitIterator["Iterator[TemplateHit]"] --> check_overlap["Check overlap with<br/>query_crop_indices"]
        check_overlap --> _get_entity_data["_get_entity_data()"]
    end

    subgraph "Structure Processing"
        _get_entity_data --> structure_to_entities_data["structure_to_entities_data()"]
        structure_to_entities_data --> AllAtomEntityData["AllAtomEntityData"]
        AllAtomEntityData --> tokenize_entity["tokenizer.tokenize_entity()"]
        tokenize_entity --> AllAtomStructureContext["AllAtomStructureContext"]
    end

    subgraph "Template Validation"
        AllAtomStructureContext --> drop_unresolved["Drop unresolved residues<br/>get_centre_positions_and_mask()"]
        drop_unresolved --> strict_subsequence_check["Strict subsequence check<br/>Compare sequences"]
        strict_subsequence_check --> LoadedTemplate["LoadedTemplate"]
    end

    subgraph "Feature Extraction"
        LoadedTemplate --> template_restype["template_restype"]
        LoadedTemplate --> template_pseudo_beta_mask["template_pseudo_beta_mask"]
        LoadedTemplate --> template_pseudo_beta_distances["template_pseudo_beta_distances"]
        LoadedTemplate --> template_backbone_frame_mask["template_backbone_frame_mask"]
        LoadedTemplate --> template_unit_vector["template_unit_vector"]
    end
```

### LoadedTemplate Class Structure

```mermaid
classDiagram
    class LoadedTemplate {
        +query_crop_indices: Int32Tensor
        +template_hit: TemplateHit
        +template_hit_structure_context: AllAtomStructureContext
        +query_identifier() str
        +hit_identifier() str
        +template_hit_indices() Int32Tensor
        +template_query_match_indices() Int32Tensor
        +cropped_template_query_match_indices() Int32Tensor
        +template_restype() Int32Tensor
        +template_pseudo_beta_mask() BoolTensor
        +template_pseudo_beta_distances() FloatTensor
        +template_backbone_frame_mask() BoolTensor
        +template_unit_vector() FloatTensor
    }

    LoadedTemplate *-- TemplateHit
    LoadedTemplate *-- AllAtomStructureContext
```

### Key Features and Properties

The `LoadedTemplate` class provides properties that extract features directly for the model:
- `template_restype`: Extracts residue types and handles gaps using `rc.residue_types_with_nucleotides_order["-"]` [chai_lab/data/dataset/templates/load.py:121-128]().
- `template_pseudo_beta_mask`: Computes the existence mask for reference atoms (e.g., Cβ) [chai_lab/data/dataset/templates/load.py:131-144]().
- `template_pseudo_beta_distances`: Calculates pairwise distances between reference atoms, filling masked regions with a large value (100.0) [chai_lab/data/dataset/templates/load.py:147-171]().

Sources: [chai_lab/data/dataset/templates/load.py:58-232](), [chai_lab/data/dataset/templates/load.py:262-411]()

## Template Alignment with Kalign

Sequence alignment is a critical step in template processing. Chai-1 uses the Kalign tool to align query sequences to template sequences through the `kalign_query_to_reference` function.

### Kalign Alignment Process

```mermaid
flowchart TD
    subgraph "Input Preprocessing"
        QuerySeq["Query Sequence"] --> clean_query["query.upper().replace('-', '')"]
        RefSeq["Reference Sequence"] --> RefSeq
        clean_query --> write_fastas["write_fastas()"]
        RefSeq --> write_fastas
    end

    subgraph "Kalign Execution"
        write_fastas --> temp_fasta["Temporary FASTA file"]
        temp_fasta --> kalign_subprocess["subprocess.run(['kalign', '-i', input, '-o', output])"]
        kalign_subprocess --> read_fasta["read_fasta()"]
        read_fasta --> KalignAlignment["KalignAlignment"]
    end

    subgraph "Alignment Processing"
        KalignAlignment --> query_a3m_line["query_a3m_line property"]
        KalignAlignment --> reference_span["reference_span property"]
        query_a3m_line --> tokenize_sequences["tokenize_sequences_to_arrays()"]
        tokenize_sequences --> TemplateHit["TemplateHit creation"]
    end
```

### KalignAlignment Class

```mermaid
classDiagram
    class KalignAlignment {
        +reference_aligned: str
        +query_aligned: str
        +query_a3m_line() str
        +reference_span() tuple[int, int]
        +__post_init__()
    }

    note for KalignAlignment "Validates alignment:\n- Same length sequences\n- No double gaps\n- Proper A3M formatting"
```

The `query_a3m_line` property converts the alignment to A3M format by marking query insertions as lowercase [chai_lab/tools/kalign.py:35-42](). The `reference_span` property identifies the coverage range on the reference sequence [chai_lab/tools/kalign.py:44-57]().

Sources: [chai_lab/tools/kalign.py:19-111]()

## Template Context Assembly

Individual `LoadedTemplate` objects are assembled into a unified `TemplateContext` that can be processed by the model. The `TemplateContext` class handles alignment, padding, and merging of multiple templates.

### TemplateContext Structure

```mermaid
classDiagram
    class TemplateContext {
        +template_restype: Int32Tensor
        +template_pseudo_beta_mask: BoolTensor
        +template_backbone_frame_mask: BoolTensor
        +template_distances: FloatTensor
        +template_unit_vector: FloatTensor
        +num_tokens() int
        +num_templates() int
        +num_nonnull_templates() int
        +template_mask() BoolTensor
        +to_dict() dict
        +empty() TemplateContext
        +index_select() TemplateContext
        +merge() TemplateContext
        +pad() TemplateContext
        +from_loaded_templates() TemplateContext
    }

    note for TemplateContext "Tensor dimensions:\n[n_templates, n_tokens]\n[n_templates, n_tokens, n_tokens]\n[n_templates, n_tokens, n_tokens, 3]"
```

### Template Feature Extraction

Templates provide several key features that inform the structure prediction:

| Feature | Tensor Shape | Description |
|---------|-------------|-------------|
| `template_restype` | `[n_templates, n_tokens]` | Amino acid residue types [chai_lab/data/dataset/templates/context.py:46]() |
| `template_pseudo_beta_mask` | `[n_templates, n_tokens]` | Mask for valid Cβ positions [chai_lab/data/dataset/templates/context.py:47]() |
| `template_distances` | `[n_templates, n_tokens, n_tokens]` | Pairwise Cβ distances [chai_lab/data/dataset/templates/context.py:49]() |
| `template_backbone_frame_mask` | `[n_templates, n_tokens]` | Mask for complete N-Cα-C frames [chai_lab/data/dataset/templates/context.py:48]() |
| `template_unit_vector` | `[n_templates, n_tokens, n_tokens, 3]` | Unit vectors in backbone frame [chai_lab/data/dataset/templates/context.py:50]() |

### Merging and Alignment

The `merge` method concatenates multiple `TemplateContext` objects along the sequence dimension while properly tiling the 2D distance and unit vector matrices [chai_lab/data/dataset/templates/context.py:119-180](). 1D and 2D features are aligned to the global token indices using `align_1d` and `align_2d` [chai_lab/data/dataset/templates/align.py:18-67]().

Sources: [chai_lab/data/dataset/templates/context.py:42-332](), [chai_lab/data/dataset/templates/align.py:1-68]()

## Integration with the Prediction Pipeline

Templates are integrated into the `AllAtomFeatureContext`, which serves as the central data structure for structure prediction in Chai-1.

```mermaid
flowchart TD
    MSAContext["MSA Context"] --> AllAtomFeatureContext["AllAtomFeatureContext"]
    TemplateContext["Template Context"] --> AllAtomFeatureContext
    ESMContext["ESM Embedding Context"] --> AllAtomFeatureContext
    StructureContext["Structure Context"] --> AllAtomFeatureContext
    RestraintContext["Restraint Context"] --> AllAtomFeatureContext
    
    AllAtomFeatureContext --> ModelComponents["Model Components<br>(Feature Embedder, Token Embedder,<br>Trunk, Diffusion Module)"]
    ModelComponents --> DiffusionResults["Diffusion Results"]
```

Templates are discovered via M8 search results, downloaded from RCSB [chai_lab/data/io/rcsb.py:9-18](), and processed into tensors. The `CHAI_TEMPLATE_CIF_FOLDER` environment variable can be used to specify the storage location for downloaded CIF files [chai_lab/data/dataset/templates/context.py:36-38]().

Sources: [chai_lab/data/dataset/templates/load.py:262-411](), [chai_lab/data/dataset/templates/context.py:36-38]()

---