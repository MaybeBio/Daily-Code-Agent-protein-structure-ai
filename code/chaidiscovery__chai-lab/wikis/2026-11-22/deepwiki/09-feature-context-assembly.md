# Feature Context Assembly

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [chai_lab/data/dataset/all_atom_feature_context.py](chai_lab/data/dataset/all_atom_feature_context.py)
- [chai_lab/data/features/feature_factory.py](chai_lab/data/features/feature_factory.py)
- [chai_lab/data/features/feature_type.py](chai_lab/data/features/feature_type.py)
- [chai_lab/data/features/feature_utils.py](chai_lab/data/features/feature_utils.py)
- [chai_lab/data/features/generators/base.py](chai_lab/data/features/generators/base.py)

</details>



The Feature Context Assembly system in Chai-1 combines diverse biological and chemical information into a unified `AllAtomFeatureContext` structure. This assembly process integrates structural data, evolutionary information, templates, embeddings, and spatial constraints into a cohesive representation that the model can process.

## Overview

The `AllAtomFeatureContext` class acts as a unified container that consolidates multiple types of data contexts. It is defined in [chai_lab/data/dataset/all_atom_feature_context.py:25-40](). The context is designed to be padded and batched by a collator [chai_lab/data/dataset/all_atom_feature_context.py:27-29]().

### AllAtomFeatureContext Structure

| Field | Type | Description |
| :--- | :--- | :--- |
| `chains` | `list[Chain]` | Metadata for each chain in the system. |
| `structure_context` | `AllAtomStructureContext` | Token and atom level structural data. |
| `msa_context` | `MSAContext` | Primary evolutionary information. |
| `profile_msa_context` | `MSAContext` | MSA data used for profiling. |
| `template_context` | `TemplateContext` | Structural templates from homology. |
| `embedding_context` | `EmbeddingContext \| None` | Sequence embeddings (e.g., ESM). |
| `restraint_context` | `RestraintContext` | User-defined spatial constraints. |

Sources: [chai_lab/data/dataset/all_atom_feature_context.py:25-40]()

### Natural Language to Code Entity Space

This diagram maps conceptual features to their corresponding code implementations within the assembly pipeline.

```mermaid
graph TD
    subgraph "Natural Language Concepts"
        residue_info["Residue & Atom Types"]
        evolutionary_data["Evolutionary Alignments"]
        structural_priors["Homology Templates"]
        language_model["Sequence Embeddings"]
        spatial_priors["Spatial Restraints"]
    end

    subgraph "Code Entity Space"
        AllAtomStructureContext["AllAtomStructureContext"]
        MSAContext["MSAContext"]
        TemplateContext["TemplateContext"]
        EmbeddingContext["EmbeddingContext"]
        RestraintContext["RestraintContext"]
        FeatureFactory["FeatureFactory"]
    end

    residue_info --> AllAtomStructureContext
    evolutionary_data --> MSAContext
    structural_priors --> TemplateContext
    language_model --> EmbeddingContext
    spatial_priors --> RestraintContext

    AllAtomStructureContext -- "structure_context" --> AllAtomFeatureContext["AllAtomFeatureContext"]
    MSAContext -- "msa_context" --> AllAtomFeatureContext
    TemplateContext -- "template_context" --> AllAtomFeatureContext
    EmbeddingContext -- "embedding_context" --> AllAtomFeatureContext
    RestraintContext -- "restraint_context" --> AllAtomFeatureContext

    AllAtomFeatureContext -- "generate(batch)" --> FeatureFactory
```

Sources: [chai_lab/data/dataset/all_atom_feature_context.py:32-39](), [chai_lab/data/features/feature_factory.py:16-23]()

## Components of Feature Context

### Structure Context
The `AllAtomStructureContext` manages the mapping between tokens (residues/entities) and atoms. It handles global indexing when multiple chains are merged via `AllAtomStructureContext.merge` [chai_lab/data/dataset/structure/all_atom_structure_context.py:360-361]().

### MSA Context
Captures evolutionary information. The assembly limits the depth of MSAs to `MAX_MSA_DEPTH` (16,384) during padding [chai_lab/data/dataset/all_atom_feature_context.py:20-20](), [chai_lab/data/dataset/all_atom_feature_context.py:60-61]().

### Template Context
Provides structural hints from known PDB structures. The system supports up to `MAX_NUM_TEMPLATES` (4) [chai_lab/data/dataset/all_atom_feature_context.py:21-21](), [chai_lab/data/dataset/all_atom_feature_context.py:68-69]().

## Feature Factory and Generators

The `FeatureFactory` is the engine that converts an assembled `AllAtomFeatureContext` (after collation into a batch) into actual numerical tensors used by the model trunk.

### Implementation Flow

The factory iterates through a dictionary of `FeatureGenerator` objects, calling their `generate` method on the batch [chai_lab/data/features/feature_factory.py:22-23]().

```mermaid
sequenceDiagram
    participant B as Batch (from AllAtomFeatureContext)
    participant FF as FeatureFactory
    participant FG as FeatureGenerator (Subclass)
    
    FF->>FG: generate(batch)
    activate FG
    FG->>FG: get_input_kwargs_from_batch(batch)
    FG->>FG: _generate(**kwargs)
    FG->>FG: make_feature(data)
    FG-->>FF: Tensor
    deactivate FG
    FF->>FF: Aggregate into dict[str, Tensor]
```

Sources: [chai_lab/data/features/feature_factory.py:16-23](), [chai_lab/data/features/generators/base.py:94-111]()

### Feature Types and Encodings
Features are categorized by `FeatureType` (e.g., `RESIDUE`, `ATOM`, `MSA`, `TEMPLATES`) [chai_lab/data/features/feature_type.py:8-17](). They are encoded using various methods defined in `EncodingType` [chai_lab/data/features/generators/base.py:18-25]():

- **ONE_HOT / OUTERSUM**: Categorical data.
- **RBF / FOURIER**: Continuous distance or positional data.
- **IDENTITY**: Raw floating point values.
- **ESM**: Pre-computed language model embeddings.

The `cast_feature` function ensures tensors are in the correct format and dtype for their encoding type [chai_lab/data/features/generators/base.py:27-54]().

## Assembly for Collation

Before being passed to the model, the `AllAtomFeatureContext` must be converted to a dictionary of tensors. This is performed by the `to_dict()` method, which flattens the nested context objects into a single-level dictionary [chai_lab/data/dataset/all_atom_feature_context.py:78-95]().

### Data Flow to Tensors

| Step | Operation | Source |
| :--- | :--- | :--- |
| 1. Assembly | Combine contexts into `AllAtomFeatureContext` | `chai_lab/chai1.py` |
| 2. Padding | `pad(n_tokens, n_atoms)` | [chai_lab/data/dataset/all_atom_feature_context.py:45-76]() |
| 3. Flattening | `to_dict()` | [chai_lab/data/dataset/all_atom_feature_context.py:78-95]() |
| 4. Generation | `FeatureFactory.generate(batch)` | [chai_lab/data/features/feature_factory.py:22-23]() |

The `to_dict` method specifically handles the mapping of MSA keys like `msa_tokens`, `msa_mask`, and `msa_deletion_matrix`, as well as template and restraint features [chai_lab/data/dataset/all_atom_feature_context.py:79-94]().

Sources: [chai_lab/data/dataset/all_atom_feature_context.py:45-95](), [chai_lab/data/features/feature_factory.py:22-23]()

---