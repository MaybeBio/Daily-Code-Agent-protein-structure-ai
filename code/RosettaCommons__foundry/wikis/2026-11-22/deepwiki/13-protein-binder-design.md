# Protein Binder Design

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [models/rfd3/docs/.assets/conditioning.png](models/rfd3/docs/.assets/conditioning.png)
- [models/rfd3/docs/.assets/input_selection.png](models/rfd3/docs/.assets/input_selection.png)
- [models/rfd3/docs/.assets/partial_diff.png](models/rfd3/docs/.assets/partial_diff.png)
- [models/rfd3/docs/tutorials/enzyme_design_tutorial.md](models/rfd3/docs/tutorials/enzyme_design_tutorial.md)
- [models/rfd3/docs/tutorials/enzyme_tutorial_files/outputs.zip](models/rfd3/docs/tutorials/enzyme_tutorial_files/outputs.zip)
- [models/rfd3/docs/tutorials/enzyme_tutorial_files/rfd3_enzyme_tutorial.json](models/rfd3/docs/tutorials/enzyme_tutorial_files/rfd3_enzyme_tutorial.json)
- [models/rfd3/docs/tutorials/na_binder_tutorial.md](models/rfd3/docs/tutorials/na_binder_tutorial.md)
- [models/rfd3/docs/tutorials/ppi_design_tutorial.md](models/rfd3/docs/tutorials/ppi_design_tutorial.md)

</details>



## Purpose and Scope

This document describes how to design protein binders using RFdiffusion3 (RFD3). Protein binder design involves generating novel protein scaffolds that bind to a specific target protein at designated interface residues (hotspots). This page focuses on the configuration and execution of protein-protein interaction design tasks using hotspot conditioning.

For small molecule binder design, see [Small Molecule Binder Design](#4.4.2). For enzyme design using unindexed motifs, see [Enzyme Design](#4.4.3). For general RFD3 capabilities, see [RFD3 Overview and Capabilities](#4.1).

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:1-23](), [models/rfd3/README.md:46-49]()

## Overview

Protein binder design with RFD3 uses hotspot-guided conditional diffusion to generate protein backbones that form interfaces with target proteins. The model conditions generation on:

1.  **Target structure**: Fixed coordinates of the target protein provided via the `input` field.
2.  **Hotspot residues**: Specific atoms on the target that should be contacted by the binder, specified in `select_hotspots`.
3.  **Binder length**: Desired length range for the generated binder, defined in the `contig` string or `length` field.
4.  **Origin placement**: Strategic positioning of the binder relative to hotspots using `infer_ori_strategy`.

**Key Design Pattern**: Hotspot-conditioned diffusion

```mermaid
graph TB
    subgraph "Natural Language / User Input"
        UserTarget["Target Protein PDB"]
        UserHotspots["Contact residues/atoms"]
        UserLength["Binder size (e.g. 50-100)"]
    end

    subgraph "Code Entity Space (InputSpecification)"
        InputSpec["InputSpecification (dialect 2)"]
        FieldInput["input: path/to/target.pdb"]
        FieldContig["contig: '50-100,/0,A1-100'"]
        FieldHotspots["select_hotspots: {'A10': 'CZ'}"]
        FieldOri["infer_ori_strategy: 'hotspots'"]
    end
    
    subgraph "Inference Pipeline (Code Entities)"
        Engine["RFD3InferenceEngine"]
        Parser["create_atom_array_from_design_specification"]
        Sampler["ConditionalDiffusionSampler"]
        Metrics["HbondMetrics"]
    end
    
    UserTarget --> FieldInput
    UserHotspots --> FieldHotspots
    UserLength --> FieldContig
    
    FieldInput --> InputSpec
    FieldContig --> InputSpec
    FieldHotspots --> InputSpec
    FieldOri --> InputSpec
    
    InputSpec --> Parser
    Parser --> Engine
    Engine --> Sampler
    Sampler --> Metrics
```

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:38-96](), [models/rfd3/docs/input.md:1-185]()

## InputSpecification Parameters

Protein binder design requires specific `InputSpecification` fields. While tutorials often show YAML format, the underlying schema is the `InputSpecification` class.

### Core Parameters

| Parameter | Type | Description | Required |
| :--- | :--- | :--- | :--- |
| `input` | `str` | Path to target protein PDB/CIF file [models/rfd3/docs/tutorials/ppi_design_tutorial.md:48-51]() | Yes |
| `contig` | `str` | Binder length range and target selection [models/rfd3/docs/tutorials/ppi_design_tutorial.md:58-65]() | Yes |
| `select_hotspots` | `Dict` | Hotspot atoms for interface design [models/rfd3/docs/tutorials/ppi_design_tutorial.md:71-79]() | Yes |
| `infer_ori_strategy` | `str` | Origin placement strategy: `"hotspots"` [models/rfd3/docs/tutorials/ppi_design_tutorial.md:88-92]() | Recommended |
| `is_non_loopy` | `bool` | Reduces loop content in designed binder [models/rfd3/docs/tutorials/ppi_design_tutorial.md:93-96]() | Recommended |

### Contig Specification Format

The `contig` field for binder design follows the pattern:
`"<binder_length_range>,/0,<target_chain><target_start>-<target_end>"`

*   **Binder length range**: `"40-120"` specifies the length of the generated binder.
*   **Chain break**: `/0` indicates a chain break between the binder and target.
*   **Target selection**: `"E6-155"` selects residues 6-155 from chain E of the input.

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:58-65](), [models/rfd3/docs/input.md:44-67]()

## Hotspot Selection

Hotspots define the specific atoms on the target protein that should be contacted by the generated binder. RFD3 was trained to produce structures where hotspots are typically at most 4.5 Å from any heavy atom on the binder [models/rfd3/docs/tutorials/ppi_design_tutorial.md:71-73]().

### Hotspot Format

The `select_hotspots` parameter maps residue identifiers to specific atoms:

```yaml
select_hotspots:
    E64: CD2,CZ
    E88: CG,CZ
    E96: CD1,CZ
```

**Key components**:
*   **Residue identifier**: `"E64"` = chain E, residue 64.
*   **Atom names**: Comma-separated list of atom names.
*   **Requirement**: Residues used as hotspots must be included in the `contig` string [models/rfd3/docs/tutorials/ppi_design_tutorial.md:85-87]().

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:71-87](), [models/rfd3/docs/input.md:57-60]()

## Origin Placement Strategy

The `infer_ori_strategy` parameter controls the placement of the "ORI token", which specifies the center of mass of the designed portion of the output structure [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:71-73]().

### Strategy Comparison

| Strategy | Description |
| :--- | :--- |
| `"hotspots"` | Places the ORI token 10Å outward from the center of mass of the hotspots [models/rfd3/docs/tutorials/ppi_design_tutorial.md:88-92](). |
| `"com"` | Centers origin at the center of mass of the target protein. |
| `Manual` | User provides explicit coordinates, e.g., `"ori_token": [0,1,0]` [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:73](). |

### Hotspots Strategy Implementation

```mermaid
graph TD
    subgraph "RFD3InferenceEngine.run"
        Spec["DesignInputSpecification"]
        InferOri["infer_ori_strategy == 'hotspots'"]
        
        subgraph "Coordinate Calculation"
            HotspotCoords["Get coords for select_hotspots"]
            COM["Calculate Center of Mass (COM)"]
            Offset["Shift 10Å outward from COM"]
            Token["Set ori_token coordinate"]
        end
    end

    Spec --> InferOri
    InferOri --> HotspotCoords
    HotspotCoords --> COM
    COM --> Offset
    Offset --> Token
```

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:88-92](), [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:71-82]()

## Execution and Workflow

### Command-Line Execution

Run protein binder design using the `rfd3 design` command:

```bash
rfd3 design \
    out_dir=outputs/binder \
    inputs=ppi_tutorial.yaml
```

### Workflow Stages

1.  **Input Parsing**: `create_atom_array_from_design_specification` parses the YAML/JSON and creates an `AtomArray` with hotspot annotations.
2.  **Inference**: `RFD3InferenceEngine` executes the diffusion sampling, utilizing the `ConditionalDiffusionSampler`.
3.  **Validation**: Post-generation, hydrogen bond metrics are calculated using the `HbondMetrics` class, which interfaces with the `HBPLUS` external tool [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:109-218]().

Sources: [models/rfd3/README.md:18-31](), [models/rfd3/docs/input.md:99-111]()

## Interface Validation

RFD3 evaluates the generated binder-target interface using hydrogen bond patterns.

**Key metrics** (from `HbondMetrics`):

| Metric | Description |
| :--- | :--- |
| `num_hbonds` | Total hydrogen bonds at the motif-diffused interface [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:218](). |
| `correct_donor_percent` | Fraction of predicted donor atoms matching target hotspots [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:109](). |
| `correct_acceptor_percent` | Fraction of predicted acceptor atoms matching target hotspots [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:110](). |

**Requirement**: The `HBPLUS` tool must be configured in the `.env` file via the `HBPLUS_PATH` variable.

Sources: [models/rfd3/src/rfd3/metrics/hbonds_hbplus_metrics.py:1-309](), [models/rfd3/README.md:117-122]()

## Best Practices for Binder Design

*   **Scientific Intuition**: Hotspot selection should be based on literature or structural knowledge of catalytic/functional residues [models/rfd3/docs/tutorials/ppi_design_tutorial.md:71-73]().
*   **Loop Control**: Always set `is_non_loopy: true` for PPI design to improve the structural integrity of the binder [models/rfd3/docs/tutorials/ppi_design_tutorial.md:93-95]().
*   **Coordinate Constraints**: Use `select_fixed_atoms` if specific residues on the target need to maintain precise geometries relative to the interface [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:83-94]().
*   **Unindexed Motifs**: If a specific functional motif must be present in the binder but its sequence position is unknown, use the `unindex` option [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:60-63]().

Sources: [models/rfd3/docs/tutorials/ppi_design_tutorial.md:71-96](), [models/rfd3/docs/tutorials/enzyme_design_tutorial.md:60-94]()

---