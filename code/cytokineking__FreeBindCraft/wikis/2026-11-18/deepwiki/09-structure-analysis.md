# Structure Analysis

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [functions/biopython_utils.py](functions/biopython_utils.py)

</details>



This document covers the Biopython-based structure analysis components that provide PyRosetta-free alternatives for analyzing protein structures in FreeBindCraft. The structure analysis system handles secondary structure calculation, interface detection, structural alignment, RMSD computation, clash detection, and sequence validation.

For PyRosetta-based structure analysis, see [PyRosetta Integration](#4). For post-processing analysis tools, see [Analysis & Validation](#6).

## Overview

The structure analysis system in FreeBindCraft provides comprehensive protein structure analysis capabilities using open-source tools, primarily Biopython. This system serves as the PyRosetta-free alternative for structural calculations required during the protein design pipeline.

**Core Structure Analysis Components**
```mermaid
graph TB
    subgraph "biopython_utils.py"
        DSSP["safe_dssp_calculation()<br/>DSSP Secondary Structure"]
        SS["calc_ss_percentage()<br/>Secondary Structure Analysis"]
        INT["hotspot_residues()<br/>Interface Detection"]
        ALIGN["biopython_align_pdbs()<br/>Structure Alignment"]
        RMSD["biopython_unaligned_rmsd()<br/>RMSD Calculation"]
        CLASH["calculate_clash_score()<br/>Clash Detection"]
        SEQ["validate_design_sequence()<br/>Sequence Validation"]
        CACHE["_dssp_cache<br/>DSSP Result Caching"]
    end
    
    subgraph "External Dependencies"
        BIO["Bio.PDB<br/>Structure Parsing"]
        SCIPY["scipy.spatial.cKDTree<br/>Spatial Queries"]
        DSSP_BIN["dssp/mkdssp Binary<br/>Secondary Structure"]
        NUMPY["numpy<br/>Coordinate Arrays"]
    end
    
    subgraph "Integration Points"
        PIPELINE["bindcraft.py<br/>Main Pipeline"]
        ALT["pr_alternative_utils.py<br/>PyRosetta Alternatives"]
    end
    
    DSSP --> CACHE
    SS --> DSSP
    SS --> INT
    INT --> SCIPY
    ALIGN --> BIO
    RMSD --> BIO
    CLASH --> SCIPY
    SEQ --> BIO
    
    PIPELINE --> SS
    PIPELINE --> ALIGN
    PIPELINE --> RMSD
    ALT --> CLASH
    ALT --> SEQ
    
    DSSP --> DSSP_BIN
    ALIGN --> NUMPY
    RMSD --> NUMPY
```

Sources: [functions/biopython_utils.py:1-497]()

## Secondary Structure Analysis

The secondary structure analysis system uses DSSP (Dictionary of Secondary Structure of Proteins) to calculate helix, sheet, and loop percentages for protein designs. The system includes robust error handling, caching, and fallback mechanisms.

### DSSP Calculation with Caching

The `safe_dssp_calculation` function provides reliable DSSP computation with automatic retries and result caching:

| Feature | Implementation | Purpose |
|---------|----------------|---------|
| **Caching** | `_dssp_cache` global dictionary | Avoid redundant DSSP calculations |
| **Retry Logic** | 3 attempts with different DSSP executables | Handle binary execution failures |
| **Fallback Paths** | Tries configured path, then `mkdssp`, then `dssp` | Maximize compatibility across systems |
| **Memory Management** | Explicit cleanup with `gc.collect()` | Prevent memory leaks |

**DSSP Calculation Flow**
```mermaid
flowchart TD
    A["safe_dssp_calculation()"] --> B{"Check _dssp_cache"}
    B -->|"Cache Hit"| C["Return Cached Result"]
    B -->|"Cache Miss"| D["Make Executable"]
    D --> E["Try Configured dssp_path"]
    E -->|"Success"| F["Cache & Return DSSP"]
    E -->|"Fail"| G["Try mkdssp Binary"]
    G -->|"Success"| F
    G -->|"Fail"| H["Try dssp Binary"] 
    H -->|"Success"| F
    H -->|"Fail"| I["Retry (max 3)"]
    I --> J["Cache None & Return"]
    
    CLEAR["clear_dssp_cache()"] --> K["Clear _dssp_cache<br/>gc.collect()"]
```

Sources: [functions/biopython_utils.py:22-88]()

### Secondary Structure Percentage Calculation

The `calc_ss_percentage` function computes comprehensive secondary structure metrics including interface-specific analysis:

**Calculated Metrics:**
- Overall helix, sheet, and loop percentages
- Interface-specific helix, sheet, and loop percentages  
- Interface pLDDT (confidence scores)
- Secondary structure pLDDT

**Secondary Structure Classification:**
- **Helix**: DSSP codes 'H', 'G', 'I' 
- **Sheet**: DSSP code 'E'
- **Loop**: All other codes

```mermaid
graph TB
    subgraph "calc_ss_percentage() Workflow"
        A["Parse PDB Structure"] --> B["Calculate DSSP"]
        B --> C["Get Interface Residues<br/>hotspot_residues()"]
        C --> D["Iterate Chain Residues"]
        
        D --> E{"Residue in DSSP?"}
        E -->|"Yes"| F["Classify SS Type<br/>H,G,I → helix<br/>E → sheet<br/>other → loop"]
        E -->|"No"| G["Skip Residue"]
        
        F --> H["Count SS Types<br/>ss_counts"]
        H --> I{"Interface Residue?"}
        I -->|"Yes"| J["Count Interface SS<br/>ss_interface_counts<br/>Collect pLDDT"]
        I -->|"No"| K["Continue"]
        
        J --> L["Calculate Percentages<br/>calculate_percentages()"]
        K --> L
        G --> D
        
        L --> M["Return: helix%, sheet%, loop%,<br/>i_helix%, i_sheet%, i_loop%,<br/>i_plddt, ss_plddt"]
    end
```

Sources: [functions/biopython_utils.py:249-318]()

## Interface Detection and Analysis

The interface detection system identifies residues that participate in protein-protein interactions based on spatial proximity. This analysis is crucial for evaluating binding interfaces in designed proteins.

### Hotspot Residue Identification

The `hotspot_residues` function uses spatial queries to identify interface residues:

**Algorithm:**
1. Extract atoms from binder chain and target chain A
2. Build KDTrees for efficient spatial queries
3. Find atom pairs within distance cutoff (default 4.0 Å)
4. Map interacting atoms back to residues
5. Return residue positions with single-letter amino acid codes

```mermaid
graph LR
    subgraph "hotspot_residues() Process"
        A["Target Chain A<br/>unfold_entities()"] --> B["Build target_tree<br/>cKDTree()"]
        C["Binder Chain B<br/>unfold_entities()"] --> D["Build binder_tree<br/>cKDTree()"]
        
        B --> E["Query Ball Tree<br/>atom_distance_cutoff=4.0"]
        D --> E
        
        E --> F["Process Atom Pairs"]
        F --> G["Map to Residues<br/>three_to_one_map"]
        G --> H["Return Dict:<br/>{res_num: aa_code}"]
    end
    
    subgraph "Three-Letter to One-Letter Conversion"
        I["three_to_one_map"] --> J["ALA → A<br/>CYS → C<br/>ASP → D<br/>...etc"]
    end
```

Sources: [functions/biopython_utils.py:211-247](), [functions/biopython_utils.py:204-209]()

## Structure Alignment and RMSD Calculation

The structure alignment system provides PyRosetta-free alternatives for structural superposition and RMSD calculation using Biopython's Superimposer class.

### Structure Alignment Functions

| Function | Purpose | Key Features |
|----------|---------|-------------|
| `biopython_align_pdbs` | Chain-specific alignment | Single chain alignment with file overwrite |
| `biopython_align_all_ca` | Whole-structure alignment | All C-alpha atoms, multi-chain support |
| `biopython_unaligned_rmsd` | RMSD without alignment | Direct coordinate comparison |
| `target_pdb_rmsd` | Trajectory vs target RMSD | Specific for design validation |

**Structure Alignment Workflow**
```mermaid
flowchart TD
    A["biopython_align_pdbs()"] --> B["Parse Reference & Align PDBs<br/>PDBParser()"]
    B --> C["Extract Specified Chains<br/>reference_chain_id, align_chain_id"]
    C --> D["Collect CA Atoms<br/>is_aa() filter"]
    D --> E["Trim to min_length<br/>Ensure equal atom sets"]
    E --> F["Create Superimposer<br/>set_atoms()"]
    F --> G["Apply Transformation<br/>sup.apply()"]
    G --> H["Save Aligned Structure<br/>PDBIO.save()"]
    H --> I["Clean PDB File<br/>clean_pdb()"]
    
    J["biopython_align_all_ca()"] --> K["Parse Both Structures"]
    K --> L["Collect All CA Atoms<br/>All chains, all models"]
    L --> M["Superimpose & Save<br/>Same as above"]
```

Sources: [functions/biopython_utils.py:322-378](), [functions/biopython_utils.py:433-497]()

### RMSD Calculation

The `biopython_unaligned_rmsd` function calculates root-mean-square deviation without performing structural alignment:

**RMSD Formula Implementation:**
```
RMSD = √(Σ(ref_coord - align_coord)² / N)
```

The function extracts C-alpha atoms from specified chains and computes direct coordinate differences.

Sources: [functions/biopython_utils.py:380-431]()

## Clash Detection

The clash detection system identifies steric clashes in protein structures using spatial proximity analysis. This is essential for validating the geometric quality of designed structures.

### Clash Score Calculation

The `calculate_clash_score` function implements a KDTree-based approach to identify atom pairs that are too close:

**Parameters:**
- `threshold`: Distance cutoff for clash detection (default 2.4 Å)
- `only_ca`: Option to check only C-alpha clashes for speed

**Filtering Logic:**
1. Exclude hydrogen atoms
2. Skip intra-residue contacts
3. Skip sequential residues in same chain
4. For sidechain clashes, only consider inter-chain contacts

```mermaid
graph TB
    A["calculate_clash_score()"] --> B["Parse PDB Structure<br/>PDBParser()"]
    B --> C["Extract Atoms & Coordinates<br/>Skip H atoms"]
    C --> D["Build cKDTree<br/>Spatial Index"]
    D --> E["Query Pairs<br/>threshold distance"]
    E --> F["Filter Valid Clashes"]
    
    subgraph "Filtering Rules"
        F --> G["Same residue?<br/>EXCLUDE"]
        F --> H["Sequential residues<br/>same chain?<br/>EXCLUDE"]
        F --> I["Sidechain mode &<br/>same chain?<br/>EXCLUDE"]
        F --> J["VALID CLASH"]
    end
    
    J --> K["Return Clash Count"]
```

Sources: [functions/biopython_utils.py:161-202]()

## Sequence Validation

The sequence validation system analyzes designed protein sequences for various quality metrics including disallowed amino acids, molecular properties, and structural issues.

### Design Sequence Analysis

The `validate_design_sequence` function performs comprehensive sequence analysis:

**Validation Checks:**
1. **Clash Detection**: Structural integrity after relaxation
2. **Restricted Amino Acids**: User-defined forbidden residues  
3. **Absorption Properties**: UV absorption for experimental detection

**Molecular Property Calculations:**
- Extinction coefficient (reduced and oxidized forms)
- Molecular weight
- Absorption value per 1% solution

```mermaid
flowchart TD
    A["validate_design_sequence()"] --> B["Initialize note_array"]
    B --> C{"num_clashes > 0?"}
    C -->|"Yes"| D["Add clash warning<br/>'Relaxed structure contains clashes'"]
    C -->|"No"| E["Check omit_AAs"]
    
    D --> E
    E --> F{"Restricted AAs present?"}
    F -->|"Yes"| G["Add AA restriction notes<br/>'Contains: X!'"]
    F -->|"No"| H["ProteinAnalysis()<br/>Bio.SeqUtils.ProtParam"]
    
    G --> H
    H --> I["Calculate Properties<br/>extinction_coefficient<br/>molecular_weight"]
    I --> J["Calculate Absorption<br/>extinction / MW * 0.01"]
    J --> K{"Absorption ≤ 2?"}
    K -->|"Yes"| L["Suggest Tryptophan<br/>'consider adding tryptophan'"]
    K -->|"No"| M["Join notes & return"]
    L --> M
```

Sources: [functions/biopython_utils.py:90-120]()

## Integration with Design Pipeline

The structure analysis components integrate seamlessly with the main FreeBindCraft pipeline, providing PyRosetta-free alternatives for critical structural calculations.

**Pipeline Integration Points**
```mermaid
graph TB
    subgraph "Main Pipeline (bindcraft.py)"
        MAIN["Main Design Loop"]
        FILTER["Apply Filters"]
        VALIDATE["Structure Validation"]
    end
    
    subgraph "Structure Analysis (biopython_utils.py)"
        SS_CALC["calc_ss_percentage()<br/>Secondary Structure"]
        HOTSPOT["hotspot_residues()<br/>Interface Detection"]
        ALIGN["biopython_align_pdbs()<br/>Structure Alignment"]
        RMSD_CALC["biopython_unaligned_rmsd()<br/>RMSD Calculation"]
        SEQ_VAL["validate_design_sequence()<br/>Sequence Analysis"]
    end
    
    subgraph "Alternative Utils (pr_alternative_utils.py)"
        CLASH_CHECK["calculate_clash_score()<br/>Clash Detection"]
        TARGET_RMSD["target_pdb_rmsd()<br/>Trajectory RMSD"]
    end
    
    MAIN --> SS_CALC
    MAIN --> ALIGN
    FILTER --> RMSD_CALC
    VALIDATE --> SEQ_VAL
    
    SS_CALC --> HOTSPOT
    VALIDATE --> CLASH_CHECK
    VALIDATE --> TARGET_RMSD
    
    style SS_CALC fill:#fff3e0
    style HOTSPOT fill:#fff3e0  
    style ALIGN fill:#fff3e0
    style RMSD_CALC fill:#fff3e0
    style SEQ_VAL fill:#fff3e0
```

**Key Integration Features:**
- **Caching System**: DSSP results cached globally to avoid recalculation
- **Error Handling**: Robust fallback mechanisms for binary dependencies
- **Memory Management**: Explicit garbage collection for large structure processing
- **File Operations**: Automatic PDB cleaning and validation after operations

Sources: [functions/biopython_utils.py:1-497]()

---