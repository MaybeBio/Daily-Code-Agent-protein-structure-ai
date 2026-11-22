# Antibody-Specific Tools

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [igfold/utils/ab_metrics.py](igfold/utils/ab_metrics.py)
- [igfold/utils/abnumber_.py](igfold/utils/abnumber_.py)

</details>



This section covers IgFold's integration with specialized antibody analysis tools, primarily the AbNumber library for antibody numbering and CDR identification, as well as PyRosetta-based metrics for structural analysis. These tools provide antibody-specific functionality beyond the core structure prediction capabilities.

For core structure prediction capabilities, see [IgFoldRunner API](#4.1). For general structure refinement options, see [Structure Refinement](#6.1).

## AbNumber Integration Architecture

IgFold integrates with the AbNumber library to provide standardized antibody numbering schemes, chain type identification, and CDR region analysis. The integration is primarily handled through utility functions that process both sequences and structures.

**AbNumber Processing Pipeline**

```mermaid
flowchart TD
    INPUT_SEQ["Antibody Sequence"] --> IS_HEAVY["is_heavy()"]
    INPUT_PDB["PDB Structure"] --> RECHAIN["rechain_pdb()"]
    
    IS_HEAVY --> CHAIN_OBJ["abnumber.Chain()"]
    RECHAIN --> PARSER["Bio.PDB.PDBParser"]
    
    CHAIN_OBJ --> CHAIN_TYPE["Heavy/Light Classification"]
    PARSER --> EXTRACT_SEQ["Extract Sequence from PDB"]
    
    EXTRACT_SEQ --> ABNUMBER_CHAIN["abnumber.Chain()"]
    ABNUMBER_CHAIN --> POSITIONS["positions.items()"]
    
    POSITIONS --> RENUMBER_PDB["renumber_pdb()"]
    POSITIONS --> TRUNCATE_SEQ["truncate_seq()"]
    
    RENUMBER_PDB --> NUMBERED_PDB["Renumbered PDB File"]
    TRUNCATE_SEQ --> CLEAN_SEQ["Cleaned Sequence"]
    
    NUMBERED_PDB --> PDBIO["Bio.PDB.PDBIO"]
    PDBIO --> OUTPUT_PDB["Output PDB"]
```

Sources: [igfold/utils/abnumber_.py:9-88]()

## Chain Type Identification

The `is_heavy()` function determines whether an antibody sequence corresponds to a heavy or light chain using AbNumber's classification system.

**Chain Identification Process**

```mermaid
flowchart LR
    SEQ["Input Sequence"] --> CHAIN_CREATE["Chain(seq, scheme='chothia')"]
    CHAIN_CREATE --> IS_HEAVY_CHECK["is_heavy_chain()"]
    IS_HEAVY_CHECK --> HEAVY_RESULT["True/False"]
    
    HEAVY_RESULT --> H_CHAIN["Heavy Chain"]
    HEAVY_RESULT --> L_CHAIN["Light Chain"]
```

The function uses the Chothia numbering scheme by default and leverages AbNumber's built-in heavy chain detection algorithms.

| Function | Purpose | Returns |
|----------|---------|---------|
| `is_heavy(seq)` | Classify chain type | Boolean (True=Heavy, False=Light) |
| `Chain(seq, scheme='chothia')` | Create AbNumber chain object | AbNumber Chain instance |
| `is_heavy_chain()` | AbNumber classification method | Boolean classification |

Sources: [igfold/utils/abnumber_.py:9-12]()

## PDB Structure Renumbering

The renumbering system provides two main capabilities: chain ID assignment and residue renumbering according to standard antibody numbering schemes.

**PDB Renumbering Workflow**

```mermaid
flowchart TD
    INPUT_PDB["Input PDB File"] --> CLEAN_PDB["clean_pdb()"]
    CLEAN_PDB --> PARSE_STRUCT["PDBParser.get_structure()"]
    
    PARSE_STRUCT --> ITER_CHAINS["Iterate Chains"]
    ITER_CHAINS --> EXTRACT_SEQ_CHAIN["Extract Chain Sequence"]
    
    EXTRACT_SEQ_CHAIN --> CREATE_ABNUMBER["Chain(seq, scheme)"]
    CREATE_ABNUMBER --> GET_POSITIONS["positions.items()"]
    
    GET_POSITIONS --> VALIDATE_LENGTH["Assert len(chain_res) == len(numbering)"]
    VALIDATE_LENGTH --> ITER_RESIDUES["Iterate Residues"]
    
    ITER_RESIDUES --> VALIDATE_AA["Validate Amino Acid Match"]
    VALIDATE_AA --> PARSE_POSITION["Parse Position & Insertion"]
    
    PARSE_POSITION --> UPDATE_ID["Update residue._id"]
    UPDATE_ID --> NEXT_RESIDUE["Next Residue"]
    NEXT_RESIDUE --> ITER_RESIDUES
    
    ITER_RESIDUES --> SAVE_STRUCT["PDBIO.save()"]
    SAVE_STRUCT --> OUTPUT_PDB["Renumbered PDB"]
```

**Chain Re-identification Process**

```mermaid
flowchart TD
    PDB_CHAINS["PDB Chain Objects"] --> EXTRACT_SEQ["seq1(residue.resname)"]
    EXTRACT_SEQ --> ABNUMBER_OBJ["abnumber.Chain()"]
    
    ABNUMBER_OBJ --> CHAIN_TYPE["is_heavy_chain()"]
    CHAIN_TYPE --> SET_ID_H["Set chain.id = 'H'"]
    CHAIN_TYPE --> SET_ID_L["Set chain.id = 'L'"]
    
    SET_ID_H --> HANDLE_CONFLICT["Handle ValueError"]
    SET_ID_L --> HANDLE_CONFLICT
    
    HANDLE_CONFLICT --> TEMP_ID["chain.id = 'H_' or 'L_'"]
    TEMP_ID --> CLEANUP["Remove '_' suffix"]
    CLEANUP --> FINAL_CHAINS["Final Chain IDs"]
```

| Function | Parameters | Purpose |
|----------|------------|---------|
| `rechain_pdb(pdb_file)` | PDB file path | Assigns H/L chain IDs |
| `renumber_pdb(in_pdb_file, out_pdb_file, scheme)` | Input PDB, output PDB, numbering scheme | Renumbers residues |
| `truncate_seq(seq, scheme)` | Sequence, numbering scheme | Truncates sequence to numbered positions |

Sources: [igfold/utils/abnumber_.py:15-88]()

## Sequence Processing Functions

The sequence processing utilities handle antibody-specific sequence manipulations that align with standard numbering conventions.

### Truncation Function

The `truncate_seq()` function processes sequences to include only positions that have valid AbNumber assignments:

```mermaid
flowchart LR
    INPUT_SEQ["Input Sequence"] --> CREATE_CHAIN["Chain(seq, scheme)"]
    CREATE_CHAIN --> GET_POSITIONS["positions.items()"]
    GET_POSITIONS --> EXTRACT_AA["Extract Amino Acids"]
    EXTRACT_AA --> JOIN_SEQ["''.join([r[1] for r in numbering])"]
    JOIN_SEQ --> CLEAN_SEQ["Truncated Sequence"]
```

This ensures that processed sequences contain only residues with valid numbering positions, removing any terminal extensions or non-standard regions.

Sources: [igfold/utils/abnumber_.py:83-88]()

## PyRosetta-based Antibody Analysis

The `ab_metrics.py` module provides advanced structural analysis capabilities using PyRosetta's antibody-specific tools.

**PyRosetta Antibody Analysis Pipeline**

```mermaid
flowchart TD
    POSE_INPUT["PyRosetta Pose"] --> ANTIBODY_INFO["AntibodyInfo(pose)"]
    
    ANTIBODY_INFO --> VH_VL_ORIENT["vl_vh_orientation_coords()"]
    ANTIBODY_INFO --> CDR_RMSD["cdr_backbone_rmsds()"]
    ANTIBODY_INFO --> CDR_CLUSTERS["setup_CDR_clusters()"]
    
    VH_VL_ORIENT --> ORIENT_METRICS["VL-VH Distance, Opening Angle, etc."]
    CDR_RMSD --> RMSD_METRICS["H1/H2/H3 and L1/L2/L3 RMSDs"]
    CDR_CLUSTERS --> CLUSTER_ASSIGN["CDR Cluster Assignments"]
    
    ORIENT_METRICS --> RESULTS_DICT["Results Dictionary"]
    RMSD_METRICS --> RESULTS_DICT
    CLUSTER_ASSIGN --> RESULTS_DICT
```

### Structural Metrics

| Function | Returns | Metrics |
|----------|---------|---------|
| `get_vh_vl_orientation(pose)` | Dictionary | VL-VH distance, opening angle, opposite angle, packing angle |
| `get_ab_metrics(pose1, pose2)` | Dictionary | OCD, FRH/FRL RMSD, H1/H2/H3 RMSD, L1/L2/L3 RMSD |
| `get_pose_cdr_clusters(pose)` | Dictionary | CDR cluster assignments (H1-H3, L1-L3) |

### CDR Analysis Details

```mermaid
flowchart LR
    CDR_ENUM["CDRNameEnum(1-6)"] --> GET_CLUSTER["get_CDR_cluster()"]
    GET_CLUSTER --> CLUSTER_RESULT["cluster.cluster()"]
    CLUSTER_RESULT --> CLUSTER_NAME["get_cluster_name()"]
    CLUSTER_NAME --> FINAL_CLUSTER["CDR Cluster Assignment"]
    
    MAPPING["clus_name = {1: 'h1', 2: 'h2', 3: 'h3', 4: 'l1', 5: 'l2', 6: 'l3'}"]
```

Sources: [igfold/utils/ab_metrics.py:1-60]()

## Integration with IgFold Pipeline

These antibody-specific tools integrate with IgFold's main prediction pipeline through optional post-processing steps and validation utilities.

**Pipeline Integration Points**

```mermaid
flowchart TD
    IGFOLD_PRED["IgFold Prediction"] --> PDB_OUTPUT["PDB Structure"]
    
    PDB_OUTPUT --> OPT_RECHAIN["Optional: rechain_pdb()"]
    PDB_OUTPUT --> OPT_RENUMBER["Optional: renumber_pdb()"]
    
    OPT_RECHAIN --> VALIDATION["Chain ID Validation"]
    OPT_RENUMBER --> STANDARD_NUM["Standard Numbering"]
    
    VALIDATION --> DOWNSTREAM["Downstream Analysis"]
    STANDARD_NUM --> DOWNSTREAM
    
    DOWNSTREAM --> PYROSETTA_ANALYSIS["Optional: PyRosetta Metrics"]
    PYROSETTA_ANALYSIS --> FINAL_RESULTS["Final Analysis Results"]
```

The integration typically occurs during the refinement phase, where structures can be automatically renumbered and validated before final output.

### Configuration Options

When using these tools with IgFold, several parameters control the antibody-specific processing:

| Parameter | Options | Purpose |
|-----------|---------|---------|
| `scheme` | 'chothia', 'kabat', 'imgt' | Numbering scheme for renumbering |
| `rechain` | Boolean | Whether to reassign chain IDs |
| `renumber` | Boolean | Whether to renumber residues |

Sources: [igfold/utils/abnumber_.py:37-88](), [igfold/utils/ab_metrics.py:1-60]()

---