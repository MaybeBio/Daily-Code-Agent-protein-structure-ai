# Evaluation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [configs/eval/default.yaml](configs/eval/default.yaml)
- [notebooks/docking_evaluation.ipynb](notebooks/docking_evaluation.ipynb)
- [omtra/data/graph/utils.py](omtra/data/graph/utils.py)
- [omtra/eval/evals.py](omtra/eval/evals.py)
- [omtra/eval/system.py](omtra/eval/system.py)
- [omtra/eval/utils.py](omtra/eval/utils.py)
- [omtra_pipelines/docking_eval/docking_eval.py](omtra_pipelines/docking_eval/docking_eval.py)
- [omtra_pipelines/docking_eval/gen_eval_cmds.py](omtra_pipelines/docking_eval/gen_eval_cmds.py)
- [omtra_pipelines/docking_eval/sampleblaster.py](omtra_pipelines/docking_eval/sampleblaster.py)
- [routines/sample.py](routines/sample.py)

</details>



This page describes how OMTRA evaluates generated molecules using both built-in metrics and comprehensive docking evaluation pipelines. For information on the sampling process that produces molecules to evaluate, see [Sampling and Inference](#8).

## Overview

OMTRA provides two complementary evaluation approaches:

1. **Built-in Metrics**: Fast, lightweight metrics computed during or immediately after sampling, including validity, stability, geometry, and basic structure-based metrics
2. **Docking Evaluation Pipeline**: Comprehensive evaluation using external tools (GNINA, PoseBusters, PoseCheck) for scoring generated poses in protein contexts

Both approaches operate on `SampledSystem` objects, which wrap DGL graphs containing generated molecules and provide methods to convert them to standard molecular formats.

```mermaid
graph TB
    subgraph "Generation"
        Model["OMTRA.sample()<br/>omtra/models/omtra.py"]
        SS["List[SampledSystem]"]
        Model --> SS
    end
    
    subgraph "Built-in Metrics"
        BuiltIn["get_eval(eval_name)<br/>omtra/eval/register.py"]
        ValidityFn["validity()<br/>omtra/eval/evals.py:38"]
        StabilityFn["stability()<br/>omtra/eval/evals.py:44"]
        GeometryFn["geometry()<br/>omtra/eval/evals.py:58"]
        
        SS --> BuiltIn
        BuiltIn --> ValidityFn
        BuiltIn --> StabilityFn
        BuiltIn --> GeometryFn
    end
    
    subgraph "Docking Evaluation"
        Pipeline["docking_eval.py<br/>omtra_pipelines/docking_eval"]
        PB["pb_valid()<br/>docking_eval.py:97"]
        GNINA["gnina()<br/>docking_eval.py:183"]
        PC["posecheck()<br/>docking_eval.py:198"]
        
        SS --> Pipeline
        Pipeline --> PB
        Pipeline --> GNINA
        Pipeline --> PC
    end
    
    subgraph "Output"
        Metrics["metrics.json"]
        CSV["eval_metrics.csv"]
    end
    
    BuiltIn --> Metrics
    Pipeline --> CSV
```

**Sources**: [omtra/eval/evals.py:1-329](), [omtra_pipelines/docking_eval/docking_eval.py:1-1400](), [routines/sample.py:483-498]()

## Built-in Metrics System

### Metric Registration and Execution

Built-in metrics are registered using the `@register_eval` decorator and configured in [configs/eval/default.yaml](). During sampling, metrics can be computed by passing `--metrics` flag to [routines/sample.py]().

```mermaid
graph LR
    Config["configs/eval/default.yaml"]
    Register["EVAL_REGISTRY<br/>omtra/eval/register.py"]
    GetEval["get_eval(name)<br/>returns callable"]
    Execute["metric_fn(sampled_systems)"]
    Results["Dict[str, float]"]
    
    Config -->|"task-specific<br/>metric list"| GetEval
    Register -->|"lookup"| GetEval
    GetEval --> Execute
    Execute --> Results
```

**Sources**: [omtra/eval/register.py:1-20](), [configs/eval/default.yaml:1-684](), [routines/sample.py:483-498]()

### Core Metric Categories

| Metric Category | Function | Purpose | Output Keys |
|----------------|----------|---------|-------------|
| **Validity** | `validity()` | RDKit sanitization success | `frac_valid_mols`, `frac_connected`, `avg_num_components` |
| **Stability** | `stability()` | Atom valency validation | `frac_atoms_stable`, `frac_mols_stable_valence` |
| **REOS/Rings** | `reos_and_rings()` | Drug-like filters, ring system checks | `flag_rate`, `ood_rate` |
| **Geometry** | `geometry()` | Bond/angle validity, clashes | `geometry_frac_valid_bonds`, `geometry_number_clashes` |
| **Flatness** | `flatness()` | Ring planarity | `flatness_max_distance_from_plane` |
| **RMSD** | `ligand_rmsd()` | Coordinate deviation from reference | `ligand_rmsd`, `ligand_kabsch_rmsd` |
| **Pharmacophore** | `pharm_match()` | Pharmacophore feature matching | `perfect_pharm_match`, `frac_true_pharms_matched` |

**Sources**: [omtra/eval/evals.py:37-329]()

### Validity Metric

The validity metric checks whether generated molecules can be successfully sanitized by RDKit and counts connected components.

```mermaid
graph TB
    Start["SampledSystem.get_rdkit_ligand()"]
    Sanitize["Chem.SanitizeMol(rdmol)"]
    Frags["Chem.rdmolops.GetMolFrags()"]
    Count["Count components<br/>Check connectivity"]
    
    Start --> Sanitize
    Sanitize -->|"Success"| Frags
    Sanitize -->|"AtomValenceException"| Error1["error_messages['AtomValence'] += 1"]
    Sanitize -->|"KekulizeException"| Error2["error_messages['Kekulize'] += 1"]
    Frags --> Count
    
    Count --> Results["frac_valid_mols<br/>avg_frag_frac<br/>frac_connected"]
```

**Implementation**:
- Iterates through `List[SampledSystem]`
- Converts each to RDKit molecule via `get_rdkit_ligand()`
- Attempts `Chem.SanitizeMol()` and catches exceptions
- Counts molecular fragments and tracks largest fragment fraction
- Reports aggregated statistics

**Sources**: [omtra/eval/utils.py:25-106]()

### Stability Metric

Validates atom valencies against a reference table of valid valencies per element and charge state.

```mermaid
graph TB
    Extract["extract_ligdata_from_graph()<br/>Get atom types, charges, bonds"]
    Valency["compute_valencies()<br/>Count bonds per atom"]
    Table["get_valid_valency_table()<br/>omtra_pipelines/pharmit_dataset/<br/>train_valency_table.yml"]
    Check["For each atom:<br/>valency in valid_valencies[element][charge]?"]
    
    Extract --> Valency
    Table --> Check
    Valency --> Check
    Check --> Results["frac_atoms_stable<br/>frac_mols_stable_valence"]
```

**Sources**: [omtra/eval/utils.py:109-192]()

### PoseBusters Integration

PoseBusters provides configurable validation suites for different scenarios:

| Config | Use Case | Reference Needed | Protein Needed |
|--------|----------|------------------|----------------|
| `mol` | Unconditional ligand generation | No | No |
| `dock` | De novo ligand design | No | Yes |
| `redock` | Ligand conformer generation | Yes (true ligand) | Yes |
| `complex` | Pocket validation | Yes (protein) | Yes |

```python
# Example from omtra/eval/evals.py:202-242
@register_eval("pb_valid_unconditional")
def pb_valid_unconditional(sampled_systems, params):
    pb_cfg_path = Path(omtra_root()) / 'omtra/eval/pb_config/default.yaml'
    buster = pb.PoseBusters(config=pb_cfg, **params)
    df_pb = buster.bust(valid_rdmols, None, None)
    # Returns aggregated pass/fail metrics
```

**Sources**: [omtra/eval/evals.py:202-329](), [omtra_pipelines/docking_eval/docking_eval.py:97-121]()

## Docking Evaluation Pipeline

The comprehensive evaluation pipeline in [omtra_pipelines/docking_eval/docking_eval.py]() combines sampling, external tool evaluation, and metric aggregation.

### Pipeline Architecture

```mermaid
graph TB
    subgraph "Input"
        Ckpt["--ckpt_path<br/>Model checkpoint"]
        Samples["--samples_dir<br/>Existing samples"]
        TaskArg["--task<br/>Task name"]
    end
    
    subgraph "Sample or Load"
        SampleFn["sample_system()<br/>docking_eval.py:537"]
        LoadFn["system_pairs_from_path()<br/>docking_eval.py:780"]
        WriteFn["write_system_pairs()<br/>docking_eval.py:661"]
    end
    
    subgraph "Metrics Computation"
        ComputeFn["compute_metrics()<br/>docking_eval.py:332"]
        
        PBMetric["pb_valid()<br/>PoseBusters validation"]
        GninaMetric["gnina()<br/>VINA/CNN scores"]
        PCMetric["posecheck()<br/>Strain, clashes, interactions"]
        RMSDMetric["rmsd()<br/>Ligand RMSD"]
        PharmMetric["compute_pharmacophore_match()<br/>Pharmacophore matching"]
        
        ComputeFn --> PBMetric
        ComputeFn --> GninaMetric
        ComputeFn --> PCMetric
        ComputeFn --> RMSDMetric
        ComputeFn --> PharmMetric
    end
    
    subgraph "Output"
        CSV["eval_metrics.csv<br/>Per-ligand metrics"]
    end
    
    Ckpt --> SampleFn
    Samples --> LoadFn
    TaskArg --> SampleFn
    TaskArg --> LoadFn
    
    SampleFn --> WriteFn
    WriteFn --> SystemPairs["system_pairs<br/>Dict[sys_id, pairs]"]
    LoadFn --> SystemPairs
    
    SystemPairs --> ComputeFn
    ComputeFn --> CSV
```

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:39-778]()

### System Pairs Structure

The pipeline organizes generated ligands and proteins into `system_pairs`, a nested dictionary structure:

```python
system_pairs = {
    'sys_0_gt': {
        'pair_0': {
            'gen_ligs': List[Chem.Mol],           # Generated ligands
            'gen_ligs_file': Path,                # SDF file path
            'gen_ligs_ids': List[str],            # Ligand identifiers
            'gen_prot_file': Path,                # Generated/reference protein PDB
            'gen_prot_id': str,                   # Protein identifier
            'true_lig': Chem.Mol,                 # Ground truth ligand
            'true_lig_file': Path,                # Ground truth SDF
            'true_prot_file': Path,               # Ground truth protein PDB
            'true_prot_id': str,                  # True protein identifier
            'true_pharm': Dict,                   # Pharmacophore data (if applicable)
        }
    }
}
```

For tasks generating protein structure, each replicate gets its own pair. For fixed protein tasks, all replicates share one pair.

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:661-777]()

### GNINA Evaluation

GNINA provides docking scores using both classical VINA scoring and CNN-based scoring functions.

```mermaid
graph LR
    Input["lig_file: SDF<br/>prot_file: PDB"]
    ScoreOnly["gnina --score_only"]
    Minimize["gnina --minimize"]
    
    Scores["minimizedAffinity<br/>CNNscore<br/>CNNaffinity<br/>CNNaffinity_variance"]
    MinScores["vina_min"]
    
    Input --> ScoreOnly
    Input --> Minimize
    
    ScoreOnly --> Scores
    Minimize --> MinScores
```

**Implementation Details**:
- Uses pre-built GNINA binary at `omtra_root()/gnina.1.3.2`
- Runs `--score_only` for fast scoring without optimization
- Runs `--minimize` for energy-minimized affinity prediction
- Parses scores from output SDF file properties
- Wrapped with timeout (default 2700s) via `run_with_timeout()`

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:124-195]()

### PoseCheck Integration

PoseCheck computes strain energy, steric clashes, and protein-ligand interactions.

```mermaid
graph TB
    Init["PoseCheck()"]
    LoadProt["pc.load_protein_from_pdb(prot_file)<br/>Runs reduce for H atoms"]
    LoadLig["pc.load_ligands_from_mols(ligs)"]
    
    Clash["pc.calculate_clashes()"]
    Strain["pc.calculate_strain_energy()"]
    Interact["pc.calculate_interactions()"]
    
    InterTypes["HBAcceptor, HBDonor<br/>Hydrophobic, PiStacking"]
    Recovery["interaction_recovery<br/>Compare to true ligand"]
    
    Init --> LoadProt
    LoadProt --> LoadLig
    LoadLig --> Clash
    LoadLig --> Strain
    LoadLig --> Interact
    
    Interact --> InterTypes
    Interact --> Recovery
```

**Key Metrics**:
- `clashes`: Steric clash count
- `strain`: Strain energy (kcal/mol)
- `HBAcceptor`, `HBDonor`, `Hydrophobic`, `PiStacking`: Interaction counts normalized by ligand atom count
- `interaction_recovery`: Fraction of true interactions recovered by generated ligand

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:198-245]()

### Timeout and Error Handling

All metric functions are wrapped with `run_with_timeout()` to prevent hanging:

```python
def run_with_timeout(func, *args, timeout, **kwargs):
    """Run function in separate process with timeout."""
    q = mp.Queue()
    p = mp.Process(target=target, args=(q, *args), kwargs=kwargs)
    p.start()
    p.join(timeout)
    
    if p.is_alive():
        p.terminate()
        p.join()
        return None  # Timeout occurred
    
    return q.get()  # Return result or exception
```

If a batch fails, the pipeline attempts to evaluate ligands individually to maximize coverage.

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:295-318](), [omtra_pipelines/docking_eval/docking_eval.py:395-419]()

### Pharmacophore Matching

Evaluates whether generated ligands reproduce pharmacophore features from reference ligands.

```mermaid
graph TB
    GenLig["Generated ligand"]
    TruePharm["True pharmacophore<br/>coords, types_idx"]
    
    Extract["get_pharmacophores(gen_lig)<br/>Extract features"]
    Dist["cdist(true_coords, gen_coords)<br/>Pairwise distances"]
    Type["same_type_mask<br/>Match feature types"]
    
    Match["matching = (d < threshold) & same_type"]
    Perfect["perfect_pharm_match<br/>All true pharms matched?"]
    Frac["frac_true_pharms_matched<br/>Fraction matched"]
    
    GenLig --> Extract
    TruePharm --> Dist
    Extract --> Dist
    Extract --> Type
    TruePharm --> Type
    
    Dist --> Match
    Type --> Match
    Match --> Perfect
    Match --> Frac
```

**Parameters**:
- `threshold`: Distance threshold in Angstroms (default 1.0)

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:255-292]()

## SampledSystem Class

The `SampledSystem` class is the core data structure for evaluation, wrapping DGL graphs and providing conversion methods.

### Class Overview

```mermaid
graph TB
    subgraph "Input"
        Graph["DGLHeteroGraph<br/>Generated structure"]
        Task["Task<br/>Defines modalities"]
        Traj["traj: Dict[str, Tensor]<br/>Optional trajectory"]
    end
    
    subgraph "SampledSystem"
        Init["__init__()<br/>omtra/eval/system.py:43"]
        Decode["decode_conda()<br/>Expand condensed types"]
    end
    
    subgraph "Conversion Methods"
        RDKit["get_rdkit_ligand()<br/>→ Chem.Mol"]
        RDKitProt["get_rdkit_protein()<br/>→ Chem.Mol"]
        Biotite["get_protein_array()<br/>→ struc.AtomArray"]
        RefLig["get_rdkit_ref_ligand()<br/>→ Chem.Mol (ground truth)"]
    end
    
    subgraph "Write Methods"
        WriteLig["write_ligand(path)<br/>Write SDF"]
        WriteProt["write_protein(path)<br/>Write CIF/PDB"]
        WritePharm["write_pharmacophore(path)<br/>Write XYZ"]
    end
    
    Graph --> Init
    Task --> Init
    Traj --> Init
    
    Init --> Decode
    Decode --> RDKit
    Decode --> RDKitProt
    Decode --> Biotite
    Decode --> RefLig
    
    RDKit --> WriteLig
    Biotite --> WriteProt
```

**Sources**: [omtra/eval/system.py:38-95]()

### RDKit Molecule Construction

The conversion from DGL graph to RDKit molecule follows this pipeline:

```mermaid
graph TB
    Extract["extract_ligdata_from_graph()<br/>omtra/eval/system.py:491"]
    
    Positions["positions: Tensor<br/>Atom coordinates"]
    AtomTypes["atom_types: List[str]<br/>Element symbols"]
    Charges["atom_charges: List[int]<br/>Formal charges"]
    Bonds["bond_types: Tensor<br/>bond_src_idxs<br/>bond_dst_idxs"]
    
    Build["build_molecule()<br/>omtra/eval/system.py:605"]
    
    AddAtoms["For each atom:<br/>mol.AddAtom(Chem.Atom(type))<br/>Set formal charge"]
    AddBonds["For each bond:<br/>mol.AddBond(src, dst, type)"]
    SetCoords["conf = Chem.Conformer()<br/>Set atom positions"]
    
    Extract --> Positions
    Extract --> AtomTypes
    Extract --> Charges
    Extract --> Bonds
    
    Positions --> Build
    AtomTypes --> Build
    Charges --> Build
    Bonds --> Build
    
    Build --> AddAtoms
    Build --> AddBonds
    Build --> SetCoords
    
    SetCoords --> RDMol["Chem.Mol"]
```

**Key Steps**:
1. Extract features from graph with suffix `_1` (generated) or `_1_true` (reference)
2. Handle fake atoms (type `Sn`) and masked atoms (type `Se`) if present
3. Filter to upper triangle of adjacency matrix to avoid duplicate bonds
4. Convert atom/bond type indices to RDKit types using constant maps
5. Create RDKit molecule, add atoms with charges, add bonds, set conformer

**Sources**: [omtra/eval/system.py:400-644]()

### Protein Array Construction

Biotite `AtomArray` objects are used for protein structures:

```python
def get_protein_array(self, g=None, reference=False, include_bonds=True):
    # Extract data from graph
    coords, atom_names, elements, res_ids, res_names, chain_ids, hetero = \
        self.extract_protdata_from_graph(g=g, reference=reference)
    
    # Build AtomArray
    arr = self.build_atom_array(
        coords=coords,
        atom_name=atom_names,
        element=elements,
        res_id=res_ids,
        res_name=res_names,
        chain_id=chain_ids,
        hetero=hetero,
        include_bonds=include_bonds
    )
    return arr
```

**Features**:
- Maps protein atom types using `protein_atom_type_map` and `protein_element_map`
- Maps residue types using `residue_map`
- Preserves chain IDs and residue numbering
- Bonds inferred via `struc.connect_via_distances()` if not provided
- Cached for efficiency when used repeatedly

**Sources**: [omtra/eval/system.py:373-398]()

### Trajectory Reconstruction

For visualization, trajectories can be reconstructed by placing each timestep's features on a dummy graph:

```mermaid
graph TB
    TrajDict["traj: Dict[str, Tensor]<br/>Modality trajectories<br/>Shape: [n_timesteps, ...]"]
    Dummy["g_dummy = copy_graph(self.g)"]
    
    Loop["For frame_idx in range(n_timesteps)"]
    Place["For each modality:<br/>g_dummy.nodes[ntype].data[feat] = traj[modality][frame_idx]"]
    
    Extract["extract_ligdata_from_graph(g_dummy)"]
    BuildMol["build_molecule()"]
    
    TrajDict --> Loop
    Dummy --> Loop
    Loop --> Place
    Place --> Extract
    Extract --> BuildMol
    
    BuildMol --> TrajMols["traj_mols[lig/prot/pharm]<br/>List of molecules per frame"]
```

**Sources**: [omtra/eval/system.py:646-707]()

## Evaluation Configuration

### Task-Specific Metrics

[configs/eval/default.yaml]() defines which metrics run for each task:

```yaml
rigid_docking_condensed:
  - stability:
      train: true
      params: {}
  - reos_and_rings:
      train: true
      params: {}
  - flatness:
      train: true
      params:
        threshold_flatness: 0.1
  - intermolecular_distance:
      train: true
      params:
        clash_cutoff: 0.05
  - ligand_rmsd:
      train: true
      params:
        rmsd_threshold: 2.0
  - volume_overlap:
      train: true
      params:
        clash_cutoff: 0.05
  - pb_valid_unconditional:
      train: true
      params:
        max_workers: 0
```

Each metric specifies:
- `train`: Whether to compute during training (for logging to wandb)
- `params`: Parameters passed to the metric function

**Sources**: [configs/eval/default.yaml:1-684]()

### Metric Execution During Sampling

When `--metrics` flag is passed to [routines/sample.py]():

```python
if args.metrics:
    default_eval_cfg = OmegaConf.load('configs/eval/default.yaml')
    
    metrics = {}
    for eval_entry in default_eval_cfg[task_name]:
        for eval_name, config in eval_entry.items():
            eval_fn = get_eval(eval_name)
            metrics.update(eval_fn(sampled_systems, config.get("params", {})))
    
    # Write metrics to JSON
    metrics_file = output_dir / f"{task_name}_metrics.json"
    with open(metrics_file, 'w') as f:
        json.dump(metrics, f)
```

**Sources**: [routines/sample.py:483-498]()

## Orchestration Scripts

### gen_eval_cmds.py

Generates docking evaluation commands from YAML configuration files:

```yaml
# Example config
- model_dir: /path/to/model
  tasks:
    - rigid_docking_condensed
    - fixed_protein_ligand_denovo_condensed
  n_samples: 100
  n_replicates: 10
  dataset: plinder
  split: test
```

**Command generation logic**:
1. Find best checkpoint via `find_best_checkpoint()` (prefers `last.ckpt`)
2. For each (model, task) pair, generate docking_eval.py command
3. Optionally batch into chunks if `batch_size` specified
4. Write commands to file for parallel execution

**Sources**: [omtra_pipelines/docking_eval/gen_eval_cmds.py:1-357]()

### sampleblaster.py

Chunks large evaluation jobs for parallel execution:

```mermaid
graph LR
    CSV["plinder_eval_sys_idxs.csv<br/>1,4,7,10,13,..."]
    Chunk["chunk_indices()<br/>chunk_size=10"]
    
    Files["chunk_000.csv: 1,4,7,10,13,16,19,22,25,28<br/>chunk_001.csv: 31,34,37,40,43,46,49,52,55,58<br/>..."]
    
    Commands["For each chunk × n_replicates:<br/>python docking_eval.py<br/>--sys_idx_file=chunk_XXX.csv<br/>--n_replicates=1<br/>--output_dir=chunk_XXX_rep_Y"]
    
    CSV --> Chunk
    Chunk --> Files
    Files --> Commands
```

**Usage**:
```bash
python sampleblaster.py \
    --input_csv plinder_eval_sys_idxs.csv \
    --chunk_size 10 \
    --n_replicates 5 \
    --ckpt_path /path/to/checkpoint.ckpt \
    --task rigid_docking_condensed
```

**Outputs**:
- `chunks/chunk_XXX.csv`: Chunked system index files
- `eval_commands.txt`: All commands to run
- One command per (chunk, replicate) pair for parallel execution

**Sources**: [omtra_pipelines/docking_eval/sampleblaster.py:1-236]()

## Metrics Output Format

### Built-in Metrics JSON

```json
{
  "frac_valid_mols": 0.95,
  "frac_connected": 0.92,
  "avg_frag_frac": 0.98,
  "frac_atoms_stable": 0.94,
  "frac_mols_stable_valence": 0.89,
  "flag_rate": 0.12,
  "ood_rate": 0.03,
  "geometry_frac_valid_bonds": 0.96,
  "ligand_rmsd": 1.23
}
```

**Sources**: [routines/sample.py:493-497]()

### Docking Evaluation CSV

Output from docking_eval.py has one row per generated ligand:

| Column | Description |
|--------|-------------|
| `sys_id` | System identifier (e.g., `sys_0_gt`) |
| `protein_id` | Protein identifier |
| `gen_ligand_id` | Generated ligand identifier |
| `RDKit_valid` | RDKit sanitization success |
| `pb_*` | PoseBusters metrics |
| `minimizedAffinity` | VINA score |
| `CNNscore`, `CNNaffinity` | GNINA CNN scores |
| `vina_min` | VINA score after minimization |
| `clashes`, `strain` | PoseCheck metrics |
| `HBAcceptor`, `HBDonor`, etc. | Interaction counts |
| `interaction_recovery` | Interaction recovery fraction |
| `rmsd` | RMSD to ground truth |
| `perfect_pharm_match` | All pharmacophores matched |

Additionally, `*_true` columns contain metrics for ground truth ligands when applicable.

**Sources**: [omtra_pipelines/docking_eval/docking_eval.py:346-533]()

---