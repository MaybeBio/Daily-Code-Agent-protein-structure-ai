

Autoregressive generation in FoldingDiff represents an alternative approach to protein structure generation that sequentially predicts backbone angles one residue at a time, rather than using the diffusion-based denoising process. This method leverages causal language modeling principles adapted for protein geometry prediction.

## Architecture Overview

The autoregressive generation system is built around two core components: the `BertForAutoregressive` model and the `AutoregressiveCausalDataset` data preparation pipeline. Unlike the diffusion approach that adds and removes noise across timesteps, autoregressive generation treats protein backbone generation as a sequential prediction problem where each angle set depends only on previously generated angles.

### Model Architecture

The autoregressive model extends the base BERT architecture with modifications for protein angle prediction:

```python
class BertForAutoregressiveBase(BertForDiffusionBase):
    """
    Overrides the previous model's forward function to not handle noise or timesteps
    """
```

The key architectural differences from the diffusion model include:

- **No timestep handling**: The forward pass removes timestep encoding entirely, focusing purely on sequence position information
- **Length embedding**: Reuses the time embedding mechanism to encode sequence lengths, providing context about the target protein length [foldingdiff/modelling.py#L818-L821](foldingdiff/modelling.py#L818-L821)
- **Causal attention masking**: Implements strict left-to-right attention patterns to enforce autoregressive constraints

### Data Processing Pipeline

The autoregressive training uses the `AutoregressiveCausalDataset` wrapper to convert standard angle datasets into causal language modeling format:

```python
def __getitem__(self, index: int):
    """Get the ith item with a randomly chosen sub-mask"""
    # Sample a causal length uniformly between 1 and original length
    causal_len = torch.randint(low=1, high=orig_len, size=(1,)).item()
    
    # Create causal mask for left-to-right attention
    causal_attn_mask = torch.zeros_like(return_dict["attn_mask"])
    causal_attn_mask[:causal_len] = 1.0
    
    # Target is the next angle at position causal_len
    return_dict["causal_target"] = return_dict[self.dset_key][causal_len]
    return_dict["causal_idx"] = causal_len
```

This approach randomly truncates sequences during training, forcing the model to learn to predict the next angle set given varying amounts of context [foldingdiff/datasets.py#L650-L680](foldingdiff/datasets.py#L650-L680).

## Generation Process

### Sequential Sampling

The autoregressive generation process uses the `sample()` method to generate complete protein backbones from initial seed angles:

```python
@torch.no_grad()
def sample(
    self,
    seed_angles: torch.Tensor,
    seq_lengths: torch.Tensor,
    num_seed: int = 2,
    pbar: bool = True,
) -> List[torch.Tensor]:
```

The generation follows this iterative process:

1. **Initialization**: Start with seed angles (typically first 2 residues) [foldingdiff/modelling.py#L864-L877](foldingdiff/modelling.py#L864-L877)
2. **Iterative prediction**: For each position from `num_seed` to `max(seq_lengths)`:
   - Create attention mask covering generated positions
   - Predict next angle set using current context
   - Append prediction to generated sequence
3. **Angle wrapping**: Ensure all generated angles remain within valid ranges [-π, π]

### Causal Attention Mechanism

The attention mechanism enforces autoregressive constraints through careful mask construction:

```python
# Create causal attention mask during generation
attention_mask[:, :i] = 1.0  # Only attend to positions <= current
```

This ensures that angle predictions at position `i` can only depend on angles at positions `0` through `i-1`, maintaining the causal property essential for sequential generation [foldingdiff/modelling.py#L882-L886](foldingdiff/modelling.py#L882-L886).

## Training Configuration

### Loss Function

The autoregressive model uses angular-aware loss functions adapted for sequential prediction:

```python
def _get_loss(self, batch) -> torch.Tensor:
    # Get predictions for all positions
    preds = self.forward(
        batch["angles"],
        attention_mask=batch["causal_attn_mask"],
        seq_lengths=batch["lengths"],
        position_ids=batch["position_ids"],
    )
    
    # Extract prediction at causal position and compare with target
    l = self.loss(
        preds[torch.arange(batch["lengths"].shape[0]), batch["causal_idx"]],
        batch["causal_target"],
    )
```

The loss is computed only at the randomly sampled causal positions, making training efficient while providing comprehensive coverage of the sequence space [foldingdiff/modelling.py#L921-L932](foldingdiff/modelling.py#L921-L932).

### Training Pipeline

The `BertForAutoregressive` class wraps the base model in a PyTorch Lightning module with:

- **Standard training/validation loops**: Using the causal loss computation
- **Learning rate scheduling**: Support for various scheduler strategies
- **Regularization**: L2 regularization and angular loss functions

## Comparison with Diffusion Generation

| Aspect | Autoregressive | Diffusion |
|--------|----------------|-----------|
| Generation Method | Sequential prediction | Iterative denoising |
| Training Objective | Next-angle prediction | Noise prediction |
| Generation Speed | Linear in sequence length | Linear in timesteps |
| Parallelism | Limited (sequential) | High (parallel denoising) |
| Quality Control | Per-angle constraints | Global noise schedule |

> [!TIP]
> The autoregressive approach is particularly useful for controlled generation scenarios where you want to influence the generation process step-by-step, or when computational resources are limited and you need faster generation for shorter sequences.

## Integration with Existing Pipeline

The autoregressive generation system is designed to integrate seamlessly with the existing FoldingDiff infrastructure:

- **Dataset compatibility**: Works with all angle datasets through the wrapper pattern
- **Coordinate conversion**: Uses the same angle-to-coordinate conversion systems as diffusion models
- **Evaluation metrics**: Compatible with SCTM, TM-score, and other evaluation methods
- **Visualization**: Integrates with existing plotting and analysis tools

The modular design allows you to switch between autoregressive and diffusion generation depending on your specific requirements, while maintaining consistent data formats and evaluation pipelines.

## Next Steps

For practical implementation of autoregressive generation:

1. **Model Training**: Use the `[Lightning Training Pipeline](13-lightning-training-pipeline)` with autoregressive configuration
2. **Dataset Preparation**: Wrap your angle datasets with `AutoregressiveCausalDataset`
3. **Generation**: Use the `sample()` method with appropriate seed angles
4. **Evaluation**: Apply `[Self-Consistency TM Score](18-self-consistency-tm-score-calculation)` and other metrics
5. **Visualization**: Utilize `[Visualization and Analysis Tools](17-visualization-and-analysis-tools)` for result analysis

The autoregressive approach provides a complementary method to diffusion-based generation, offering different trade-offs in terms of generation quality, speed, and controllability.