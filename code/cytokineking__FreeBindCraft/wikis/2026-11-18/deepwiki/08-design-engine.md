# Design Engine

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [functions/colabdesign_utils.py](functions/colabdesign_utils.py)

</details>



The Design Engine is the core component of FreeBindCraft that orchestrates protein binder design through AlphaFold2 hallucination and MPNN sequence optimization. This system leverages ColabDesign to generate novel protein binders that can bind to specified target proteins at defined hotspot regions.

This document covers the hallucination pipeline, design algorithms, loss functions, and MPNN integration. For structure analysis and validation of generated designs, see [Structure Analysis](#3.2). For PyRosetta-free alternatives to structure processing, see [PyRosetta-Free Alternatives](#4.1).

## Core Design Pipeline

The design engine follows a multi-stage pipeline that transforms a target protein structure into optimized binder designs:

### Design Pipeline Flow

```mermaid
flowchart TD
    A["Target PDB + Settings"] --> B["binder_hallucination()"]
    B --> C["mk_afdesign_model()"]
    C --> D["prep_inputs()"]
    D --> E{"Design Algorithm"}
    
    E --> F["2stage: design_pssm_semigreedy()"]
    E --> G["3stage: design_3stage()"]  
    E --> H["4stage: Multi-stage Pipeline"]
    E --> I["greedy: design_semigreedy()"]
    E --> J["mcmc: _design_mcmc()"]
    
    F --> K["save_pdb()"]
    G --> K
    H --> K
    I --> K
    J --> K
    
    K --> L["Quality Validation"]
    L --> M{"Pass Checks?"}
    M -->|No| N["Trajectory Rejected"]
    M -->|Yes| O["mpnn_gen_sequence()"]
    
    O --> P["predict_binder_complex()"]
    P --> Q["predict_binder_alone()"]
    Q --> R["Final Design Output"]
```

**Sources:** [functions/colabdesign_utils.py:23-255]()

### Binder Hallucination Process

The `binder_hallucination` function serves as the entry point for design generation, implementing the following workflow:

1. **Model Initialization**: Creates an AlphaFold2 design model using ColabDesign
2. **Input Preparation**: Processes target PDB, chain selection, and hotspot residues
3. **Loss Function Configuration**: Sets up custom loss functions and weights
4. **Design Algorithm Execution**: Runs the selected optimization algorithm
5. **Quality Assessment**: Validates the generated trajectory for clashes and confidence

```mermaid
graph TD
    A["binder_hallucination()"] --> B["clear_mem()"]
    B --> C["mk_afdesign_model()"]
    C --> D["prep_inputs()"]
    
    D --> E["Configure Loss Weights"]
    E --> F["pae: weights_pae_intra"]
    E --> G["plddt: weights_plddt"] 
    E --> H["i_pae: weights_pae_inter"]
    E --> I["con: weights_con_intra"]
    E --> J["i_con: weights_con_inter"]
    
    F --> K["Add Custom Losses"]
    G --> K
    H --> K
    I --> K
    J --> K
    
    K --> L["add_helix_loss()"]
    K --> M["add_rg_loss()"]
    K --> N["add_i_ptm_loss()"]
    K --> O["add_termini_distance_loss()"]
    
    L --> P["Execute Design Algorithm"]
    M --> P
    N --> P
    O --> P
```

**Sources:** [functions/colabdesign_utils.py:23-72](), [functions/colabdesign_utils.py:201-234]()

## Design Algorithms

The design engine supports five distinct optimization algorithms, each with different trade-offs between speed and quality:

| Algorithm | Function | Description | Use Case |
|-----------|----------|-------------|----------|
| `2stage` | `design_pssm_semigreedy()` | Gradient descent + PSSM biased sampling | Fast prototyping |
| `3stage` | `design_3stage()` | Logits → Softmax → One-hot encoding | Balanced approach |
| `4stage` | Multi-stage pipeline | Comprehensive 4-step optimization | High-quality results |
| `greedy` | `design_semigreedy()` | Random mutations decreasing loss | Simple optimization |
| `mcmc` | `_design_mcmc()` | Monte Carlo mutation sampling | Exploration-focused |

**Sources:** [functions/colabdesign_utils.py:78-192]()

### Four-Stage Algorithm Detail

The most sophisticated algorithm implements a comprehensive optimization pipeline:

```mermaid
flowchart TD
    A["Stage 1: Initial Logits"] --> B["design_logits(50 iters)"]
    B --> C["get_best_plddt()"]
    C --> D{"pLDDT > 0.65?"}
    
    D -->|No| E["Update Failure: Trajectory_logits_pLDDT"]
    D -->|Yes| F["Beta Structure Assessment"]
    
    F --> G["calc_ss_percentage()"]
    G --> H{"Beta > 15%?"}
    H -->|Yes| I["Optimize Settings for Beta"]
    H -->|No| J["Continue Standard Path"]
    I --> J
    
    J --> K["Additional Logits Optimization"]
    K --> L["Stage 2: Softmax Optimization"]
    L --> M["design_soft()"]
    M --> N{"Softmax pLDDT > 0.65?"}
    
    N -->|No| O["Update Failure: Trajectory_softmax_pLDDT"]
    N -->|Yes| P["Stage 3: One-hot Optimization"]
    P --> Q["design_hard()"]
    Q --> R{"One-hot pLDDT > 0.65?"}
    
    R -->|No| S["Update Failure: Trajectory_one-hot_pLDDT"]
    R -->|Yes| T["Stage 4: PSSM Semigreedy"]
    T --> U["design_pssm_semigreedy()"]
```

**Sources:** [functions/colabdesign_utils.py:100-192]()

## Loss Functions

The design engine incorporates multiple custom loss functions to guide the optimization process:

### Standard Loss Functions

| Loss Type | Weight Parameter | Purpose |
|-----------|------------------|---------|
| PAE Intra | `weights_pae_intra` | Internal structure confidence |
| PAE Inter | `weights_pae_inter` | Interface confidence |
| pLDDT | `weights_plddt` | Per-residue confidence |
| Contacts Intra | `weights_con_intra` | Internal contacts |
| Contacts Inter | `weights_con_inter` | Interface contacts |

**Sources:** [functions/colabdesign_utils.py:46-56]()

### Custom Loss Functions

The system includes specialized loss functions for specific design objectives:

```mermaid
graph TD
    A["Custom Loss Functions"] --> B["add_rg_loss()"]
    A --> C["add_i_ptm_loss()"]
    A --> D["add_helix_loss()"]
    A --> E["add_termini_distance_loss()"]
    
    B --> F["Radius of Gyration Control"]
    C --> G["Interface pTM Optimization"]
    D --> H["Secondary Structure Control"]
    E --> I["Cyclization Constraint"]
    
    F --> J["rg = 2.38 * N^0.365"]
    G --> K["1 - get_ptm(interface=True)"]
    H --> L["i+3 Contact Preference"]
    I --> M["N-C Terminus Distance < 7Å"]
```

**Sources:** [functions/colabdesign_utils.py:392-472]()

## MPNN Integration

After successful hallucination, the system uses ProteinMPNN to generate diverse sequences that maintain the designed structure:

### MPNN Sequence Generation

```mermaid
flowchart TD
    A["mpnn_gen_sequence()"] --> B["clear_mem()"]
    B --> C["mk_mpnn_model()"]
    C --> D["prep_inputs()"]
    
    D --> E{"mpnn_fix_interface?"}
    E -->|Yes| F["fixed_positions = 'A,' + interface_residues"]
    E -->|No| G["fixed_positions = 'A'"]
    
    F --> H["model.sample()"]
    G --> H
    H --> I["Return MPNN Sequences"]
    
    subgraph "MPNN Parameters"
        J["backbone_noise"]
        K["sampling_temp"] 
        L["num_seqs"]
        M["batch"]
    end
    
    C --> J
    H --> K
    H --> L
    H --> M
```

**Sources:** [functions/colabdesign_utils.py:362-386]()

## Structure Prediction and Validation

The design engine predicts both binder-target complexes and isolated binder structures to assess design quality:

### Prediction Pipeline

| Function | Purpose | Output |
|----------|---------|---------|
| `predict_binder_complex()` | Complex structure prediction | pLDDT, pTM, i_pTM, pAE, i_pAE |
| `predict_binder_alone()` | Isolated binder prediction | Binder confidence metrics |

### Complex Prediction Process

```mermaid
graph TD
    A["predict_binder_complex()"] --> B["Clean Sequence"]
    B --> C{"For each prediction_model"}
    C --> D["model.predict()"]
    D --> E["model.save_pdb()"]
    E --> F["Extract Metrics"]
    
    F --> G["pLDDT, pTM, i_pTM"]
    F --> H["pAE, i_pAE"] 
    
    G --> I["Apply AF2 Filters"]
    H --> I
    I --> J{"Pass Filters?"}
    J -->|Yes| K["pr_relax()"]
    J -->|No| L["Remove PDB"]
    
    subgraph "Filter Conditions"
        M["model_pLDDT >= threshold"]
        N["model_pTM >= threshold"]
        O["model_i_pTM >= threshold"]
        P["model_pAE <= threshold"]
        Q["model_i_pAE <= threshold"]
    end
    
    I --> M
    I --> N
    I --> O
    I --> P
    I --> Q
```

**Sources:** [functions/colabdesign_utils.py:257-327](), [functions/colabdesign_utils.py:329-360]()

## Quality Control and Validation

The design engine implements multiple quality control checkpoints:

### Trajectory Validation Criteria

| Check | Function | Threshold | Failure Type |
|-------|----------|-----------|--------------|
| CA Clashes | `calculate_clash_score()` | > 0 clashes | `Trajectory_Clashes` |
| Final pLDDT | `get_best_plddt()` | < 0.7 | `Trajectory_final_pLDDT` |
| Interface Contacts | `hotspot_residues()` | < 3 contacts | `Trajectory_Contacts` |

**Sources:** [functions/colabdesign_utils.py:201-234]()

### Output Generation

Upon successful validation, the system generates comprehensive output:

- **Trajectory PDB**: Final hallucinated structure
- **Design Plots**: Loss function trajectories for each metric
- **Animation**: HTML visualization of design trajectory
- **Pickle Files**: Complete design state for analysis

**Sources:** [functions/colabdesign_utils.py:241-254](), [functions/colabdesign_utils.py:474-501]()

---