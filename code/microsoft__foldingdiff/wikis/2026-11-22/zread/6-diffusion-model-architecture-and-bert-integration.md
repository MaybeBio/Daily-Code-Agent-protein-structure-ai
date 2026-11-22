

The FoldingDiff framework implements a sophisticated diffusion model architecture that leverages BERT's transformer backbone for protein structure generation. This architecture combines the power of diffusion processes with the sequence modeling capabilities of transformers to predict protein backbone angles through a denoising approach.

## Core Architecture Components

### BERT-Based Diffusion Model

The primary model architecture is built upon the `BertForDiffusion` class, which extends both `BertPreTrainedModel` and `pl.LightningModule` to integrate HuggingFace's BERT implementation with PyTorch Lightning for training orchestration [foldingdiff/modelling.py#L487-L490].

The model's initialization reveals the key architectural decisions:

```python
def __init__(
    self,
    config,
    ft_is_angular: List[bool] = [False, True, True, True],  # Feature type indicators
    time_encoding: TIME_ENCODING = "gaussian_fourier",  # Time embedding strategy
    decoder: DECODER_HEAD = "mlp",  # Output decoder type
) -> None:
```

This configuration shows the model processes 4 features where the first is non-angular (likely sequence position) and the remaining three are angular features (phi, psi, omega angles) [foldingdiff/modelling.py#L242].

### Input Processing Pipeline

The forward pass demonstrates the model's sophisticated processing pipeline:

1. **Input Projection**: Low-dimensional angle inputs are projected to the hidden dimension using `inputs_to_hidden_dim` [foldingdiff/modelling.py#L267-L269]
2. **BERT Embeddings**: Standard BERT positional and token embeddings are applied [foldingdiff/modelling.py#L270]
3. **Time Encoding Integration**: Diffusion timestep information is encoded and added to the embeddings [foldingdiff/modelling.py#L471-L472]
4. **Transformer Processing**: The BERT encoder processes the time-augmented embeddings [foldingdiff/modelling.py#L473-L480]
5. **Angle Prediction**: A specialized decoder predicts the denoised angles [foldingdiff/modelling.py#L483]

## Time Encoding Mechanisms

The diffusion process requires sophisticated time encoding to inform the model about the noise level at each timestep. Two primary encoding strategies are implemented:

### Gaussian Fourier Projection

The default time encoding uses Gaussian random features, following score-based model best practices [foldingdiff/modelling.py#L42-L71]:

```python
class GaussianFourierProjection(nn.Module):
    def __init__(self, embed_dim: int, scale: float = 2 * torch.pi):
        w = torch.randn(embed_dim // 2) * scale
        self.register_buffer("W", w)  # Fixed during optimization
```

This approach randomly samples weights during initialization and keeps them fixed, providing a rich representation of temporal information through sinusoidal projections at different frequencies.

### Sinusoidal Position Embeddings

An alternative sinusoidal encoding is also available, using the classic transformer positional encoding approach [foldingdiff/modelling.py#L74-L93]. This method provides a deterministic time representation based on geometric progression of frequencies.

## Angle Prediction Architecture

The model employs a specialized `AnglesPredictor` head that follows BERT's masked language modeling pattern [foldingdiff/modelling.py#L173-L208]:

```python
d_model -> dense -> d_model -> activation -> layernorm -> dense -> d_output
```

This two-layer architecture with intermediate layer normalization ensures stable prediction of angular values while maintaining compatibility with BERT's pretraining objectives.

## Model Configuration and Variants

The framework supports multiple model configurations through JSON files. The mini model configuration reveals typical hyperparameters [config_jsons/mini_model.json]:

- **Transformer Architecture**: 6 layers, 192 hidden size, 6 attention heads
- **Diffusion Parameters**: 250 timesteps, cosine variance schedule
- **Training Configuration**: Learning rate 5e-5, smooth L1 loss, batch size 128

### Autoregressive Variant

Beyond diffusion, the framework implements an autoregressive variant through `BertForAutoregressive` that predicts next angles given current angles, enabling sequential protein generation [foldingdiff/modelling.py#L896-L901].

## Integration with Protein Structure

The architecture is specifically designed for protein angle prediction, with careful consideration of angular data properties:

1. **Angular Loss Functions**: Specialized loss functions handle the circular nature of angular data
2. **Feature Type Awareness**: The model tracks which features are angular vs. non-angular for appropriate processing
3. **Coordinate Conversion**: Integration with NERF (Natural Extension Reference Frame) for angle-to-coordinate conversion [foldingdiff/nerf.py]

## Training Pipeline Integration

The Lightning module integration provides comprehensive training infrastructure [foldingdiff/modelling.py#L487]:

- **Loss Computation**: Multi-feature loss calculation with angular considerations
- **Optimization**: Configurable optimizers and learning rate schedules
- **Validation**: Comprehensive validation metrics and logging
- **Checkpointing**: Model saving and loading capabilities

This architecture represents a sophisticated fusion of diffusion models and transformer technology, specifically adapted for the challenges of protein structure generation while maintaining flexibility for different experimental configurations and research objectives.