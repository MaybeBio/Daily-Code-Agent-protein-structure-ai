# Training OpenFold

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfold/data/data_modules.py](openfold/data/data_modules.py)
- [openfold/utils/loss.py](openfold/utils/loss.py)
- [train_openfold.py](train_openfold.py)

</details>



## Purpose and Scope

This document provides an overview of the training system in OpenFold. It describes the main training script, PyTorch Lightning integration, training workflow, and key components involved in training AlphaFold-style models. 

For detailed information about specific training subsystems, see:
- Training pipeline internals: [Training Pipeline](#4.1)
- Data loading and filtering: [Data Loading and Filtering](#4.2)
- Memory optimization strategies: [Memory Optimization for Training](#4.3)
- Model architecture details: [Model Architecture](#5)
- Loss function implementations: [Loss Functions](#5.6)

---

## Training Entry Point

The main training script is [train_openfold.py](), which orchestrates all training operations using PyTorch Lightning. This script handles command-line argument parsing, model initialization, data loading, distributed training configuration, and checkpoint management.

**Sources:** [train_openfold.py:1-703]()

### Command-Line Arguments

The training script accepts several categories of arguments:

| Category | Key Arguments | Description |
|----------|--------------|-------------|
| **Data Paths** | `train_data_dir`, `train_alignment_dir`, `template_mmcif_dir` | Locations of training structures, MSAs, and templates |
| **Output** | `output_dir`, `experiment_name` | Where to save checkpoints and logs |
| **Configuration** | `config_preset`, `experiment_config_json` | Model configuration selection and overrides |
| **Training Control** | `max_epochs`, `train_epoch_len`, `seed` | Training duration and reproducibility |
| **Distributed** | `gpus`, `num_nodes`, `deepspeed_config_path` | Multi-GPU and multi-node settings |
| **Validation** | `val_data_dir`, `val_alignment_dir` | Validation dataset locations |
| **Checkpointing** | `resume_from_ckpt`, `checkpoint_every_epoch` | Checkpoint loading and saving |
| **Logging** | `wandb`, `wandb_project`, `log_lr` | Experiment tracking |

**Sources:** [train_openfold.py:470-688]()

### Basic Training Command

```bash
python train_openfold.py \
    /path/to/train_mmcifs/ \
    /path/to/train_alignments/ \
    /path/to/template_mmcifs/ \
    /path/to/output/ \
    2021-01-01 \
    --config_preset initial_training \
    --gpus 8 \
    --max_epochs 100 \
    --seed 42
```

**Sources:** [train_openfold.py:469-703]()

---

## PyTorch Lightning Integration

OpenFold uses PyTorch Lightning to abstract distributed training, checkpointing, and logging. The core wrapper is the `OpenFoldWrapper` class, which inherits from `pl.LightningModule`.

### OpenFoldWrapper Class

```mermaid
graph TB
    subgraph "OpenFoldWrapper (pl.LightningModule)"
        CONFIG["config: ConfigDict<br/>Model configuration"]
        MODEL["model: AlphaFold<br/>Core neural network"]
        LOSS["loss: AlphaFoldLoss<br/>Loss computation"]
        EMA["ema: ExponentialMovingAverage<br/>Weight smoothing"]
    end
    
    subgraph "Lightning Hooks"
        TRAIN["training_step(batch, batch_idx)<br/>Forward + loss computation"]
        VAL["validation_step(batch, batch_idx)<br/>Evaluate with EMA weights"]
        OPTIM["configure_optimizers()<br/>Adam + AlphaFoldLRScheduler"]
        BEFORE_ZERO["on_before_zero_grad()<br/>Update EMA"]
        SAVE["on_save_checkpoint()<br/>Store EMA state"]
        LOAD["on_load_checkpoint()<br/>Restore EMA state"]
    end
    
    CONFIG --> MODEL
    CONFIG --> LOSS
    MODEL --> EMA
    
    TRAIN --> MODEL
    TRAIN --> LOSS
    VAL --> MODEL
    VAL --> LOSS
    BEFORE_ZERO --> EMA
    SAVE --> EMA
    LOAD --> EMA
```

**Sources:** [train_openfold.py:45-270]()

### Key Methods

| Method | Purpose | Key Operations |
|--------|---------|----------------|
| `__init__(config)` | Initialize wrapper | Create model, loss, and EMA instances |
| `forward(batch)` | Model inference | Delegates to `self.model(batch)` |
| `training_step(batch, batch_idx)` | Single training iteration | Forward pass, loss computation, multimer permutation alignment |
| `validation_step(batch, batch_idx)` | Single validation iteration | Load EMA weights, forward pass, compute metrics |
| `on_before_zero_grad()` | Pre-optimizer hook | Update EMA with current model weights |
| `configure_optimizers()` | Setup optimization | Create Adam optimizer and AlphaFoldLRScheduler |
| `on_save_checkpoint()` | Checkpoint hook | Save EMA state dict |
| `on_load_checkpoint()` | Load checkpoint hook | Restore EMA state dict |

**Sources:** [train_openfold.py:45-270]()

---

## Training Workflow

The complete training workflow involves data preparation, model forward passes with recycling, loss computation, gradient updates, and validation.

### High-Level Training Loop

```mermaid
graph TB
    subgraph "Data Pipeline"
        DATASET["OpenFoldDataset<br/>Stochastic filtering"]
        DATALOADER["OpenFoldDataLoader<br/>Batch properties"]
        BATCH["Feature Batch<br/>with recycling dimension"]
    end
    
    subgraph "Model Execution"
        FORWARD["Model Forward Pass<br/>AlphaFold(batch)"]
        RECYCLE["Recycling Loop<br/>max_recycling_iters"]
        OUTPUT["Model Outputs<br/>structures, logits"]
    end
    
    subgraph "Loss and Optimization"
        MULTIMER_ALIGN["multi_chain_permutation_align<br/>(if multimer)"]
        LOSS_COMP["AlphaFoldLoss<br/>FAPE + LDDT + violations"]
        BREAKDOWN["Loss Breakdown<br/>Individual components"]
        BACKWARD["Backward Pass<br/>Gradient computation"]
        EMA_UPDATE["EMA Update<br/>on_before_zero_grad()"]
        OPTIM["Optimizer Step<br/>Adam + LR schedule"]
    end
    
    subgraph "Validation"
        VAL_LOAD["Load EMA Weights<br/>cached_weights swap"]
        VAL_FORWARD["Forward Pass<br/>No gradients"]
        VAL_METRICS["Validation Metrics<br/>lddt_ca, drmsd_ca, gdt"]
        VAL_RESTORE["Restore Training Weights<br/>cached_weights swap back"]
    end
    
    DATASET --> DATALOADER
    DATALOADER --> BATCH
    BATCH --> FORWARD
    FORWARD --> RECYCLE
    RECYCLE --> OUTPUT
    
    OUTPUT --> MULTIMER_ALIGN
    MULTIMER_ALIGN --> LOSS_COMP
    LOSS_COMP --> BREAKDOWN
    BREAKDOWN --> BACKWARD
    BACKWARD --> EMA_UPDATE
    EMA_UPDATE --> OPTIM
    
    VAL_LOAD --> VAL_FORWARD
    VAL_FORWARD --> VAL_METRICS
    VAL_METRICS --> VAL_RESTORE
```

**Sources:** [train_openfold.py:97-216]()

### Training Step Details

The `training_step` method implements the following sequence:

1. **EMA Device Check**: Ensure EMA is on the same device as the batch
2. **Extract Ground Truth**: Pop `gt_features` from batch if present
3. **Forward Pass**: Execute `self.model(batch)` with recycling
4. **Remove Recycling Dimension**: Use only the final recycling iteration for loss
5. **Multimer Alignment** (if applicable): Permute chains to minimize loss via `multi_chain_permutation_align`
6. **Loss Computation**: Calculate all loss components via `self.loss(outputs, batch)`
7. **Logging**: Log all loss components and metrics

**Sources:** [train_openfold.py:97-122]()

### Validation Step Details

The `validation_step` differs from training in several ways:

1. **EMA Weight Loading**: Swap to EMA weights at validation start
2. **No Clamped FAPE**: Set `batch["use_clamped_fape"] = 0.0`
3. **Additional Metrics**: Compute superimposition-based metrics (GDT-TS, GDT-HA, alignment RMSD)
4. **Weight Restoration**: Return to training weights after validation epoch

**Sources:** [train_openfold.py:127-162]()

---

## Configuration System

Training behavior is controlled through model configuration presets defined in `openfold.config.model_config`.

### Available Presets

| Preset | Purpose | Key Differences |
|--------|---------|-----------------|
| `initial_training` | Train from scratch | Standard configuration for full training |
| `finetuning` | Fine-tune pretrained model | May use different loss weights or data augmentation |
| `model_1` | AlphaFold2 Model 1 architecture | Specific architectural choices |
| `model_1_multimer` | Multimer Model 1 | Multi-chain specific settings |
| `model_1_ptm` | Model 1 with pTM head | Includes predicted TM-score head |

**Sources:** [train_openfold.py:291-295]()

### Custom Configuration Override

You can override any configuration parameter using a JSON file:

```bash
python train_openfold.py ... \
    --config_preset initial_training \
    --experiment_config_json custom_config.json
```

The JSON file should contain a flattened dictionary of configuration paths:

```json
{
  "model.evoformer_stack.no_blocks": 48,
  "loss.fape.weight": 0.5,
  "data.train.max_template_hits": 4
}
```

**Sources:** [train_openfold.py:296-299]()

---

## Key Training Components

### Data Loading System

Training data is loaded through the `OpenFoldDataModule` (monomer) or `OpenFoldMultimerDataModule` (multimer), which implements stochastic filtering and dataset mixing.

```mermaid
graph LR
    TRAIN_DS["Train Dataset<br/>PDB mmCIFs"]
    DISTILL_DS["Distillation Dataset<br/>PDB files (optional)"]
    FILTER["Stochastic Filter<br/>Resolution, cluster size, length"]
    MIXED["OpenFoldDataset<br/>Mixed with probabilities"]
    LOADER["OpenFoldDataLoader<br/>Recycling properties"]
    
    TRAIN_DS --> FILTER
    DISTILL_DS --> FILTER
    FILTER --> MIXED
    MIXED --> LOADER
```

For detailed information, see [Data Loading and Filtering](#4.2).

**Sources:** [train_openfold.py:342-356](), [openfold/data/data_modules.py:848-1060]()

### Loss Computation

The `AlphaFoldLoss` class aggregates multiple loss components with configurable weights:

| Loss Component | Purpose | Key Parameters |
|----------------|---------|----------------|
| `fape` | Frame Aligned Point Error | Backbone and sidechain structure accuracy |
| `plddt_loss` | pLDDT prediction | Per-residue confidence prediction |
| `distogram` | Distance prediction | Inter-residue distance distribution |
| `masked_msa` | MSA reconstruction | BERT-style masked MSA prediction |
| `supervised_chi` | Torsion angle prediction | Side-chain dihedral angles |
| `violation` | Structural violations | Bond lengths, angles, clashes |
| `tm` (optional) | TM-score prediction | Template modeling score |
| `chain_center_of_mass` (optional) | Multimer COM loss | Inter-chain positioning |

The final loss is scaled by the square root of the minimum of the crop size and sequence length.

For implementation details, see [Loss Functions](#5.6).

**Sources:** [openfold/utils/loss.py:1685-1794]()

### Exponential Moving Average (EMA)

The training process maintains an EMA of model weights, which are used during validation. This provides more stable predictions and better generalization.

```mermaid
graph TB
    TRAIN_WEIGHTS["Training Weights<br/>model.parameters()"]
    EMA_WEIGHTS["EMA Weights<br/>ema.state_dict()"]
    UPDATE["EMA Update<br/>on_before_zero_grad()"]
    VAL["Validation<br/>Use EMA weights"]
    CACHE["Cached Weights<br/>Temporary storage"]
    
    TRAIN_WEIGHTS --> UPDATE
    UPDATE --> EMA_WEIGHTS
    EMA_WEIGHTS --> VAL
    TRAIN_WEIGHTS --> CACHE
    CACHE --> TRAIN_WEIGHTS
```

**Sources:** [train_openfold.py:54-56](), [train_openfold.py:124-161]()

### Optimizer and Learning Rate Schedule

The training uses Adam optimizer with a custom learning rate schedule (`AlphaFoldLRScheduler`) that implements the schedule described in the AlphaFold2 paper.

**Sources:** [train_openfold.py:217-245]()

---

## Distributed Training Support

OpenFold supports multiple distributed training strategies through PyTorch Lightning.

### Training Strategies

```mermaid
graph TB
    subgraph "Single GPU"
        SINGLE["strategy=None<br/>Single GPU training"]
    end
    
    subgraph "Multi-GPU (Same Node)"
        DDP["DDPStrategy<br/>Data-parallel training"]
    end
    
    subgraph "Multi-GPU/Multi-Node"
        DS["DeepSpeedStrategy<br/>Zero optimization"]
        MPI["MPIEnvironment<br/>MPI-based launch"]
    end
    
    SINGLE --> DDP
    DDP --> DS
    DS --> MPI
```

**Sources:** [train_openfold.py:415-428]()

### DeepSpeed Integration

When using DeepSpeed, provide a configuration file:

```bash
python train_openfold.py ... \
    --deepspeed_config_path deepspeed_config.json \
    --precision bf16
```

The DeepSpeed optimizer configuration overrides the standard Adam optimizer settings. For memory optimization details, see [Memory Optimization for Training](#4.3).

**Sources:** [train_openfold.py:416-422]()

### Multi-Node Training

For multi-node training, use the MPI plugin:

```bash
mpirun -np 16 python train_openfold.py ... \
    --mpi_plugin \
    --num_nodes 2 \
    --gpus 8 \
    --seed 42
```

**Note:** A seed must be specified for distributed training to ensure reproducibility across workers.

**Sources:** [train_openfold.py:415](), [train_openfold.py:691-694]()

---

## Checkpointing and Resumption

### Checkpoint Content

Checkpoints saved by PyTorch Lightning include:
- Model state dict (`state_dict`)
- Optimizer state
- Learning rate scheduler state
- Global training step
- EMA state dict (via `on_save_checkpoint`)

**Sources:** [train_openfold.py:254-255]()

### Resuming Training

To resume from a checkpoint:

```bash
python train_openfold.py ... \
    --resume_from_ckpt /path/to/checkpoint.ckpt
```

This restores the full training state including optimizer, scheduler, and EMA.

**Sources:** [train_openfold.py:303-331]()

### Loading Pretrained Weights Only

To initialize from pretrained weights without resuming training state:

```bash
python train_openfold.py ... \
    --resume_from_ckpt /path/to/checkpoint.ckpt \
    --resume_model_weights_only true
```

**Sources:** [train_openfold.py:303-322]()

### Loading JAX Parameters

To initialize from original AlphaFold2 JAX parameters:

```bash
python train_openfold.py ... \
    --resume_from_jax_params /path/to/params.npz
```

**Sources:** [train_openfold.py:333-336](), [train_openfold.py:260-269]()

---

## Logging and Monitoring

### Weights & Biases Integration

Enable W&B logging for experiment tracking:

```bash
python train_openfold.py ... \
    --wandb \
    --wandb_project my_project \
    --wandb_entity my_entity \
    --experiment_name my_experiment
```

The wrapper automatically logs:
- All loss components (per step and per epoch)
- Validation metrics (lddt_ca, drmsd_ca, gdt_ts, gdt_ha)
- Learning rate (if `--log_lr` enabled)

**Sources:** [train_openfold.py:393-413](), [train_openfold.py:65-95]()

### Performance Logging

Track training throughput and performance metrics:

```bash
python train_openfold.py ... \
    --log_performance true
```

This saves performance data to `output_dir/performance_log.json`.

**Sources:** [train_openfold.py:379-385]()

### Early Stopping

Enable early stopping based on validation metrics:

```bash
python train_openfold.py ... \
    --early_stopping true \
    --patience 3 \
    --min_delta 0.001
```

This monitors `val/lddt_ca` and stops training if it doesn't improve for `patience` epochs.

**Sources:** [train_openfold.py:367-377]()

---

## Training for Multimer

Multimer training requires specialized data handling and loss components. The key differences are:

1. **Data Module**: Use `OpenFoldMultimerDataModule` instead of `OpenFoldDataModule`
2. **Config Preset**: Use a multimer-specific preset (e.g., `model_1_multimer`)
3. **Chain Permutation**: Automatically align chain permutations during training
4. **Additional Losses**: Chain center-of-mass loss, inter-chain metrics

```bash
python train_openfold.py ... \
    --config_preset model_1_multimer \
    --train_mmcif_data_cache_path /path/to/mmcif_cache.json
```

The multimer data cache is generated by `scripts/generate_mmcif_cache.py` and contains chain information for each structure.

**Sources:** [train_openfold.py:342-353](), [train_openfold.py:109-112]()

---

## Validation Metrics

During validation, the following metrics are computed:

| Metric | Description | Computation |
|--------|-------------|-------------|
| `lddt_ca` | Local Distance Difference Test (Cα only) | Distance-based accuracy within 15Å cutoff |
| `drmsd_ca` | Distance Root Mean Square Deviation (Cα) | RMSD of inter-residue distances |
| `gdt_ts` | Global Distance Test - Total Score | Fraction of residues within 1,2,4,8Å after superimposition |
| `gdt_ha` | Global Distance Test - High Accuracy | Fraction of residues within 0.5,1,2,4Å after superimposition |
| `alignment_rmsd` | Alignment RMSD | RMSD after optimal superimposition |

**Sources:** [train_openfold.py:163-215]()

---