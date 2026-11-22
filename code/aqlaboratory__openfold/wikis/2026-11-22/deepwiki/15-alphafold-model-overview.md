# AlphaFold Model Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [openfold/model/model.py](openfold/model/model.py)
- [openfold/model/template.py](openfold/model/template.py)
- [openfold/model/triangular_attention.py](openfold/model/triangular_attention.py)
- [openfold/utils/tensor_utils.py](openfold/utils/tensor_utils.py)

</details>



## Purpose and Scope

This page documents the high-level architecture of the `AlphaFold` class ([openfold/model/model.py:66-604]()), which serves as the main entry point for the OpenFold model. It explains the model's overall structure, the recycling mechanism, how different input modes are handled, and the data flow through the model from input features to predicted structures.

For configuration presets and hyperparameters, see [Configuration System](#5.1). For detailed explanations of specific components, see [Evoformer Stack](#5.3), [Structure Module](#5.4), [Primitives and Building Blocks](#5.5), and [Loss Functions](#5.6).

---

## AlphaFold Class Architecture

The `AlphaFold` class is a `nn.Module` that implements Algorithm 2 from the AlphaFold 2 paper with training support. It is initialized with a configuration object and instantiates all major model components.

### Core Components

```mermaid
graph TB
    subgraph AlphaFold["AlphaFold (model.py:66)"]
        CONFIG["config<br/>(globals + model)"]
        
        subgraph Embedders["Input Embedders"]
            INPUT_EMB["input_embedder<br/>InputEmbedder/InputEmbedderMultimer/<br/>PreembeddingEmbedder"]
            RECYCLE_EMB["recycling_embedder<br/>RecyclingEmbedder"]
            TEMPLATE_EMB["template_embedder<br/>TemplateEmbedder/TemplateEmbedderMultimer"]
            EXTRA_MSA_EMB["extra_msa_embedder<br/>ExtraMSAEmbedder"]
        end
        
        subgraph Processing["Main Processing"]
            EXTRA_STACK["extra_msa_stack<br/>ExtraMSAStack"]
            EVO["evoformer<br/>EvoformerStack"]
        end
        
        subgraph Output["Output Components"]
            STRUCT["structure_module<br/>StructureModule"]
            AUX["aux_heads<br/>AuxiliaryHeads"]
        end
    end
    
    CONFIG --> INPUT_EMB
    CONFIG --> RECYCLE_EMB
    CONFIG --> TEMPLATE_EMB
    CONFIG --> EXTRA_MSA_EMB
    CONFIG --> EXTRA_STACK
    CONFIG --> EVO
    CONFIG --> STRUCT
    CONFIG --> AUX
    
    INPUT_EMB --> EVO
    RECYCLE_EMB --> EVO
    TEMPLATE_EMB --> EVO
    EXTRA_MSA_EMB --> EXTRA_STACK
    EXTRA_STACK --> EVO
    EVO --> STRUCT
    STRUCT --> AUX
```

**Sources:** [openfold/model/model.py:66-136]()

The model's initialization ([openfold/model/model.py:73-135]()) conditionally instantiates components based on configuration flags:

| Component | Config Flag | Purpose |
|-----------|-------------|---------|
| `input_embedder` | Mode-dependent | Embeds sequence/MSA features into `m` and `z` representations |
| `recycling_embedder` | Always enabled | Processes outputs from previous iteration |
| `template_embedder` | `config.template.enabled` | Embeds structural templates |
| `extra_msa_embedder` | `config.extra_msa.enabled` | Embeds extra MSA sequences |
| `extra_msa_stack` | `config.extra_msa.enabled` | Processes extra MSA with pair representation |
| `evoformer` | Always enabled | Core MSA and pair representation processing |
| `structure_module` | Always enabled | Predicts 3D atomic coordinates |
| `aux_heads` | Always enabled | Predicts confidence metrics (pLDDT, PAE, etc.) |

### Input Embedder Modes

The model supports three input modes, selected during initialization:

```python
# Multimer mode
if self.globals.is_multimer:
    self.input_embedder = InputEmbedderMultimer(...)
    
# SoloSeq mode (ESM embeddings)
elif self.seqemb_mode:
    self.input_embedder = PreembeddingEmbedder(...)
    
# Standard monomer mode
else:
    self.input_embedder = InputEmbedder(...)
```

**Sources:** [openfold/model/model.py:88-101]()

---

## Recycling Mechanism

AlphaFold uses a recycling mechanism where the model runs multiple iterations, feeding outputs from one iteration as inputs to the next. This iterative refinement improves prediction quality.

### Recycling Loop Architecture

```mermaid
graph TB
    START["forward() entry<br/>batch with recycling dim"]
    INIT["Initialize prevs<br/>m_1_prev=None<br/>z_prev=None<br/>x_prev=None"]
    
    LOOP_START{"For cycle_no in<br/>range(num_iters)"}
    SELECT["Select features<br/>fetch_cur_batch(batch, cycle_no)"]
    
    GRAD_CHECK{"is_final_iter?"}
    ENABLE_GRAD["Enable gradients"]
    DISABLE_GRAD["Disable gradients"]
    
    ITERATION["iteration(feats, prevs)<br/>→ outputs, m_1_prev, z_prev, x_prev"]
    
    EARLY_STOP_CHECK{"early_stop?"}
    
    FINAL_CHECK{"is_final_iter?"}
    CLEANUP["Delete outputs<br/>Update prevs list"]
    CONTINUE["Continue to next cycle"]
    
    AUX["aux_heads(outputs)<br/>Add pLDDT, PAE, etc."]
    RETURN["Return outputs"]
    
    START --> INIT
    INIT --> LOOP_START
    LOOP_START -->|Yes| SELECT
    SELECT --> GRAD_CHECK
    GRAD_CHECK -->|Yes| ENABLE_GRAD
    GRAD_CHECK -->|No| DISABLE_GRAD
    ENABLE_GRAD --> ITERATION
    DISABLE_GRAD --> ITERATION
    
    ITERATION --> EARLY_STOP_CHECK
    EARLY_STOP_CHECK -->|Yes multimer| FINAL_CHECK
    EARLY_STOP_CHECK -->|No| FINAL_CHECK
    
    FINAL_CHECK -->|No| CLEANUP
    FINAL_CHECK -->|Yes| AUX
    CLEANUP --> CONTINUE
    CONTINUE --> LOOP_START
    LOOP_START -->|No| AUX
    AUX --> RETURN
```

**Sources:** [openfold/model/model.py:506-604]()

### Recycling Variables

Three tensors are recycled between iterations:

| Variable | Shape | Description |
|----------|-------|-------------|
| `m_1_prev` | `[*, N, C_m]` | First row of MSA representation from previous iteration |
| `z_prev` | `[*, N, N, C_z]` | Pair representation from previous iteration |
| `x_prev` | `[*, N, 37, 3]` | Atom37 positions from previous iteration |

On the first iteration, these are initialized to zeros ([openfold/model/model.py:270-287]()). For subsequent iterations, they contain the outputs from the previous cycle.

### Early Stopping for Multimer

In multimer mode, the model implements an early stopping criterion based on coordinate convergence ([openfold/model/model.py:186-212]()):

```python
def tolerance_reached(self, prev_pos, next_pos, mask, eps=1e-8) -> bool:
    # Compares CA-CA distance matrices between iterations
    # Returns True if change is below config.recycle_early_stop_tolerance
```

When tolerance is reached, recycling terminates early even if `num_iters` hasn't been exhausted ([openfold/model/model.py:478-479]()).

**Sources:** [openfold/model/model.py:186-212](), [openfold/model/model.py:563-594]()

---

## Single Iteration Data Flow

The `iteration()` method ([openfold/model/model.py:214-486]()) performs a single forward pass through the model. This is the core processing pipeline.

### Iteration Pipeline

```mermaid
graph TB
    START["iteration(feats, prevs)"]
    
    subgraph Init["Initialization"]
        DTYPE["Cast features to model dtype"]
        UNPACK["Unpack prevs<br/>m_1_prev, z_prev, x_prev = prevs.pop()"]
        INIT_CHECK{"Any prev is None?"}
        INIT_ZEROS["Initialize prevs to zeros"]
    end
    
    subgraph InputEmbed["Input Embedding"]
        INPUT_MODE{"Input mode?"}
        MULTIMER_EMB["InputEmbedderMultimer<br/>m, z = input_embedder(feats)"]
        SEQEMB_EMB["PreembeddingEmbedder<br/>m, z = input_embedder(target, idx, emb)"]
        STANDARD_EMB["InputEmbedder<br/>m, z = input_embedder(target, idx, msa)"]
    end
    
    subgraph Recycle["Recycling Embedding"]
        PSEUDO["pseudo_beta_fn(aatype, x_prev)"]
        RECYCLE_EMB["recycling_embedder<br/>m_1_prev_emb, z_prev_emb"]
        ADD_RECYCLE["m[0] += m_1_prev_emb<br/>z += z_prev_emb"]
    end
    
    subgraph Templates["Template Processing"]
        TEMPL_CHECK{"template.enabled?"}
        EMBED_TEMPL["embed_templates()<br/>→ template_embeds"]
        ADD_TEMPL_PAIR["z += template_pair_embedding"]
        ADD_TEMPL_SINGLE{"template_single?"}
        CAT_MSA["m = cat([m, template_single_embedding])"]
    end
    
    subgraph ExtraMSA["Extra MSA Processing"]
        EXTRA_CHECK{"extra_msa.enabled?"}
        BUILD_EXTRA["build_extra_msa_feat(feats)"]
        EXTRA_EMB["extra_msa_embedder(extra_msa_feat)"]
        EXTRA_STACK["extra_msa_stack(a, z)<br/>→ z updated"]
    end
    
    subgraph MainTrunk["Main Evoformer Trunk"]
        EVO["evoformer(m, z)<br/>→ m, z, s"]
        STORE["outputs['msa'] = m<br/>outputs['pair'] = z<br/>outputs['single'] = s"]
    end
    
    subgraph Structure["Structure Prediction"]
        SM["structure_module(outputs, aatype)<br/>→ outputs['sm']"]
        ATOM37["atom14_to_atom37()<br/>→ outputs['final_atom_positions']"]
    end
    
    RETURN["Return outputs,<br/>m_1_prev, z_prev, x_prev,<br/>early_stop"]
    
    START --> DTYPE
    DTYPE --> UNPACK
    UNPACK --> INIT_CHECK
    INIT_CHECK -->|Yes| INIT_ZEROS
    INIT_CHECK -->|No| INPUT_MODE
    INIT_ZEROS --> INPUT_MODE
    
    INPUT_MODE -->|is_multimer| MULTIMER_EMB
    INPUT_MODE -->|seqemb_mode| SEQEMB_EMB
    INPUT_MODE -->|standard| STANDARD_EMB
    
    MULTIMER_EMB --> PSEUDO
    SEQEMB_EMB --> PSEUDO
    STANDARD_EMB --> PSEUDO
    
    PSEUDO --> RECYCLE_EMB
    RECYCLE_EMB --> ADD_RECYCLE
    
    ADD_RECYCLE --> TEMPL_CHECK
    TEMPL_CHECK -->|Yes| EMBED_TEMPL
    TEMPL_CHECK -->|No| EXTRA_CHECK
    EMBED_TEMPL --> ADD_TEMPL_PAIR
    ADD_TEMPL_PAIR --> ADD_TEMPL_SINGLE
    ADD_TEMPL_SINGLE -->|Yes| CAT_MSA
    ADD_TEMPL_SINGLE -->|No| EXTRA_CHECK
    CAT_MSA --> EXTRA_CHECK
    
    EXTRA_CHECK -->|Yes| BUILD_EXTRA
    EXTRA_CHECK -->|No| EVO
    BUILD_EXTRA --> EXTRA_EMB
    EXTRA_EMB --> EXTRA_STACK
    EXTRA_STACK --> EVO
    
    EVO --> STORE
    STORE --> SM
    SM --> ATOM37
    ATOM37 --> RETURN
```

**Sources:** [openfold/model/model.py:214-486]()

### Key Data Structures

Throughout the iteration, the model maintains several key tensors:

| Tensor | Shape | Description |
|--------|-------|-------------|
| `m` | `[*, S_c, N, C_m]` | MSA representation (S_c clustered sequences) |
| `z` | `[*, N, N, C_z]` | Pair representation (residue-residue interactions) |
| `s` | `[*, N, C_s]` | Single representation (per-residue features) |
| `seq_mask` | `[*, N]` | Valid residue mask |
| `pair_mask` | `[*, N, N]` | Valid residue pair mask |
| `msa_mask` | `[*, S, N]` | Valid MSA position mask |

**Sources:** [openfold/model/model.py:224-238]()

---

## Input Embedding Modes

The model's initial embedding step varies based on the operating mode:

### Standard Monomer Mode

```python
m, z = self.input_embedder(
    feats["target_feat"],      # [*, N, C_tf] one-hot target sequence
    feats["residue_index"],    # [*, N] residue indices
    feats["msa_feat"],         # [*, S, N, C_msa] MSA features
    inplace_safe=inplace_safe,
)
```

- Uses `InputEmbedder` class
- Embeds target sequence and MSA into initial `m` and `z` representations
- `m` shape: `[*, S_c, N, C_m]` where S_c is number of clustered sequences
- `z` shape: `[*, N, N, C_z]`

**Sources:** [openfold/model/model.py:254-263]()

### Multimer Mode

```python
m, z = self.input_embedder(feats)
```

- Uses `InputEmbedderMultimer` class
- Processes multiple chains with `asym_id` for chain identification
- Includes additional features for inter-chain interactions
- Special handling in template embedding with `multichain_mask_2d`

**Sources:** [openfold/model/model.py:240-244](), [openfold/model/model.py:138-156]()

### SoloSeq Mode (ESM Embeddings)

```python
m, z = self.input_embedder(
    feats["target_feat"],
    feats["residue_index"],
    feats["seq_embedding"]     # [*, N, C_esm] pre-computed ESM-1b embeddings
)
```

- Uses `PreembeddingEmbedder` class
- Bypasses MSA generation by using pre-computed language model embeddings
- `m` shape: `[*, 1, N, C_m]` (only single sequence)
- Significantly faster inference but potentially lower accuracy

**Sources:** [openfold/model/model.py:245-253]()

---

## Template and Extra MSA Processing

### Template Embedding

When templates are enabled (`config.template.enabled`), the model embeds structural templates and merges them with the pair representation:

```mermaid
graph LR
    TEMPLATE_FEATS["template_aatype<br/>template_all_atom_positions<br/>template_all_atom_mask<br/>template_pseudo_beta<br/>template_mask"]
    
    EMBED["embed_templates()<br/>(method on AlphaFold)"]
    
    TEMPLATE_PAIR["template_pair_embedding<br/>[*, N, N, C_z]"]
    TEMPLATE_SINGLE["template_single_embedding<br/>[*, S_t, N, C_m]"]
    
    Z_UPDATE["z += template_pair_embedding"]
    M_UPDATE["m = cat([m, template_single_embedding])"]
    
    TEMPLATE_FEATS --> EMBED
    EMBED --> TEMPLATE_PAIR
    EMBED --> TEMPLATE_SINGLE
    TEMPLATE_PAIR --> Z_UPDATE
    TEMPLATE_SINGLE --> M_UPDATE
```

**Sources:** [openfold/model/model.py:324-366]()

The `embed_templates()` method ([openfold/model/model.py:137-184]()) has three modes:

1. **Standard**: Processes all templates together
2. **Offload** (`template_config.offload_templates`): Processes templates one-by-one with CPU offloading for memory efficiency ([openfold/model/template.py:490-600]())
3. **Average** (`template_config.average_templates`): Processes templates in groups and averages embeddings ([openfold/model/template.py:603-715]())

### Extra MSA Processing

When enabled (`config.extra_msa.enabled`), extra MSA sequences are processed separately to update the pair representation:

```python
# Build extra MSA features
extra_msa_feat = build_extra_msa_feat(feats).to(dtype=z.dtype)

# Embed extra MSA
a = self.extra_msa_embedder(extra_msa_feat)

# Process through extra MSA stack
z = self.extra_msa_stack(
    a, z,
    msa_mask=feats["extra_msa_mask"].to(dtype=m.dtype),
    chunk_size=self.globals.chunk_size,
    ...
)
```

The extra MSA is processed separately from the clustered MSA to handle larger numbers of sequences without increasing memory proportionally. The `ExtraMSAStack` updates only the pair representation `z`, not the MSA representation `m`.

**Sources:** [openfold/model/model.py:368-411]()

---

## Structure Prediction and Output

After the Evoformer processes `m` and `z`, the model predicts 3D structure:

### Structure Module Pipeline

```mermaid
graph TB
    EVO_OUT["Evoformer outputs:<br/>m [*, S, N, C_m]<br/>z [*, N, N, C_z]<br/>s [*, N, C_s]"]
    
    SM_INPUT["outputs dict with<br/>'msa', 'pair', 'single'"]
    
    SM["structure_module<br/>(StructureModule)"]
    
    SM_OUTPUT["outputs['sm'] dict:<br/>- positions [8, *, N, 14, 3]<br/>- frames [8, *, N]<br/>- angles [*, N, 7, 2]<br/>etc."]
    
    ATOM37["atom14_to_atom37<br/>(convert to full atom repr)"]
    
    FINAL_POS["outputs['final_atom_positions']<br/>[*, N, 37, 3]"]
    
    AUX_HEADS["aux_heads<br/>(AuxiliaryHeads)"]
    
    CONFIDENCE["Confidence metrics:<br/>- plddt [*, N, 50]<br/>- predicted_aligned_error [*, N, N, 64]<br/>- predicted_tm_score [*]<br/>etc."]
    
    EVO_OUT --> SM_INPUT
    SM_INPUT --> SM
    SM --> SM_OUTPUT
    SM_OUTPUT --> ATOM37
    ATOM37 --> FINAL_POS
    
    SM_OUTPUT --> AUX_HEADS
    EVO_OUT --> AUX_HEADS
    AUX_HEADS --> CONFIDENCE
```

**Sources:** [openfold/model/model.py:449-468](), [openfold/model/model.py:601-603]()

### Structure Module Output

The `structure_module` returns a dictionary containing:

- `positions`: Atom14 coordinates at each of 8 IPA iterations `[8, *, N, 14, 3]`
- `frames`: Rigid transformations (backbone frames) `[8, *, N]`
- `angles`: Torsion angles `[*, N, 7, 2]` (sin/cos representation)
- `sidechains`: Side-chain frames
- Various violation and loss terms

**Sources:** [openfold/model/model.py:456-467]()

### Auxiliary Heads

The `aux_heads` module adds confidence and error prediction outputs:

- `plddt`: Per-residue confidence (predicted LDDT) `[*, N, 50]` (binned distribution)
- `predicted_aligned_error`: Inter-residue error prediction `[*, N, N, 64]`
- `predicted_tm_score`: Template modeling score prediction `[*]`
- `distogram`: Distance distribution prediction
- `experimentally_resolved`: Mask prediction for resolved regions

**Sources:** [openfold/model/model.py:601-603]()

---

## Memory Optimization Features

The model includes several memory optimization strategies controlled by global configuration flags:

### Offload Inference Mode

When `globals.offload_inference` is enabled, the model offloads intermediate tensors to CPU:

```python
if self.globals.offload_inference and inplace_safe:
    m = m.cpu()
    z = z.cpu()
    
# ... process recycling embedder on GPU ...

if self.globals.offload_inference and inplace_safe:
    m = m.to(m_1_prev_emb.device)
    z = z.to(z_prev.device)
```

The extra MSA stack and Evoformer have special `_forward_offload()` methods that accept CPU tensors and manage GPU transfers internally ([openfold/model/model.py:378-395](), [openfold/model/model.py:417-431]()).

**Sources:** [openfold/model/model.py:294-311](), [openfold/model/model.py:378-431]()

### In-place Operations

The `inplace_safe` flag controls whether operations can modify tensors in-place:

```python
inplace_safe = not (self.training or torch.is_grad_enabled())
```

When `inplace_safe=True` (during inference without gradients), the model uses in-place operations to reduce memory allocations. This flag is passed to all sub-modules.

**Sources:** [openfold/model/model.py:233](), [openfold/model/model.py:262-263]()

### Activation Checkpointing Control

The model can dynamically enable/disable activation checkpointing:

```python
def _disable_activation_checkpointing(self):
    self.template_embedder.template_pair_stack.blocks_per_ckpt = None
    self.evoformer.blocks_per_ckpt = None
    for b in self.extra_msa_stack.blocks:
        b.ckpt = False

def _enable_activation_checkpointing(self):
    # Restore checkpoint settings from config
    ...
```

This allows inference to run without checkpointing overhead while training uses checkpointing to save memory.

**Sources:** [openfold/model/model.py:488-504]()

### Gradient Management

During the recycling loop, gradients are only enabled for the final iteration:

```python
is_final_iter = cycle_no == (num_iters - 1) or early_stop
with torch.set_grad_enabled(is_grad_enabled and is_final_iter):
    # ... run iteration ...
```

This prevents gradient accumulation across recycling iterations, saving memory and computation.

**Sources:** [openfold/model/model.py:573-594]()

---

## Summary

The `AlphaFold` class orchestrates the entire model architecture:

1. **Input Embedding**: Converts raw features to `m` (MSA) and `z` (pair) representations using mode-specific embedders
2. **Recycling**: Iteratively refines predictions by feeding previous outputs as inputs
3. **Template Processing**: Optionally incorporates structural templates into the pair representation
4. **Extra MSA**: Processes additional sequences to enhance pair features
5. **Evoformer**: Core processing of MSA and pair representations through 48 blocks
6. **Structure Module**: Predicts 3D atomic coordinates using geometric reasoning
7. **Auxiliary Heads**: Adds confidence metrics and error predictions

The model supports three operating modes (monomer, multimer, SoloSeq) and includes extensive memory optimizations (offloading, in-place operations, checkpointing) to enable both training and inference on proteins of varying lengths.

**Sources:** [openfold/model/model.py:66-604]()

---