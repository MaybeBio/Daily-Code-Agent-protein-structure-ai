

The SaprotHub framework implements a sophisticated transformer-based architecture that leverages both ESM (Evolutionary Scale Modeling) and ProtT5 transformer models for protein analysis. This architecture provides a unified foundation for various protein prediction tasks while supporting advanced parameter-efficient fine-tuning techniques.

## Core Architecture Components

### Model Hierarchy and Base Classes

The framework is built upon a well-structured hierarchy with `AbstractModel` serving as the foundational class that extends PyTorch Lightning [saprot/model/abstract_model.py](saprot/model/abstract_model.py#L12-L405). This abstract base defines the essential interface for all models, including methods for model initialization, forward propagation, metric handling, and checkpoint management. Two primary concrete implementations extend this foundation:

- **SaprotBaseModel**: Utilizes ESM transformer architecture for structure-aware protein representation
- **ProtT5BaseModel**: Implements ProtT5 transformer for sequence-based protein analysis

Both base models share common patterns but differ in their underlying transformer architectures and tokenization strategies.

### ESM-Based Architecture (Saprot)

The SaprotBaseModel implements ESM-based transformers with sophisticated structure integration capabilities [saprot/model/saprot/base.py](saprot/model/saprot/base.py#L21-L453):

```python
class SaprotBaseModel(AbstractModel):
    """
    ESM base model. It cannot be used directly but provides model initialization for downstream tasks.
    """
```

The model initialization process dynamically selects appropriate transformer architectures based on task requirements:

- **Classification Tasks**: Utilizes `AutoModelForSequenceClassification` for multi-class protein predictions
- **Token Classification**: Implements sequence-level labeling capabilities
- **Regression Tasks**: Supports continuous value prediction

The ESM architecture excels at capturing both sequence and structural information through its attention mechanisms, making it particularly suitable for structure-aware protein analysis.

### ProtT5-Based Architecture

The ProtT5BaseModel leverages the T5 encoder-decoder architecture adapted specifically for protein sequences [saprot/model/protT5/base.py](saprot/model/protT5/base.py#L27-L393):

```python
class ProtT5BaseModel(AbstractModel):
    """
    T5 base model. It cannot be used directly but provides model initialization for downstream tasks.
    """
```

ProtT5 uses the `T5Tokenizer` and `T5EncoderModel` components, providing robust sequence understanding capabilities. The architecture is particularly effective for tasks requiring deep sequence comprehension and can be extended with custom classification heads for specific protein prediction tasks.

## Parameter-Efficient Fine-Tuning with LoRA

Both architectures implement advanced Low-Rank Adaptation (LoRA) techniques for efficient fine-tuning, enabling parameter-efficient adaptation to specific tasks while preserving the knowledge captured in pre-trained weights.

### LoRA Configuration and Management

The framework supports sophisticated LoRA configurations with multiple adapter management [saprot/model/saprot/base.py](saprot/model/saprot/base.py#L74-L120):

```python
lora_config = {
    "task_type": "SEQ_CLS",
    "target_modules": ["query", "key", "value", "intermediate.dense", "output.dense"],
    "modules_to_save": ["classifier"],
    "inference_mode": False,
    "r": getattr(self.lora_kwargs, "r", 8),
    "lora_dropout": getattr(self.lora_kwargs, "lora_dropout", 0.0),
    "lora_alpha": getattr(self.lora_kwargs, "lora_alpha", 16),
}
```

For ProtT5 models, the target modules are specifically tailored to the T5 architecture [saprot/model/protT5/base.py](saprot/model/protT5/base.py#L79-L125):

```python
"target_modules": ["SelfAttention.q", "SelfAttention.k", "SelfAttention.v", "SelfAttention.o", 
                   "EncDecAttention.q", "EncDecAttention.k", "EncDecAttention.v", "EncDecAttention.o"]
```

### Multi-Adapter Support

The framework supports loading and managing multiple LoRA adapters simultaneously, enabling:

- **Transfer Learning**: Loading pre-trained adapters for specific domains
- **Multi-Task Learning**: Maintaining separate adapters for different tasks
- **Adapter Composition**: Combining multiple adapters for enhanced performance

## Hidden State Extraction and Representation

Both architectures provide sophisticated methods for extracting and processing transformer hidden states, enabling flexible feature extraction for various downstream applications.

### Hidden State Processing

The `get_hidden_states_from_dict` method demonstrates the sophisticated approach to representation learning [saprot/model/saprot/base.py](saprot/model/saprot/base.py#L257-L290):

```python
def get_hidden_states_from_dict(self, inputs: dict, reduction: str = None) -> list:
    """
    Get hidden representations from input dict
    
    Args:
        inputs: A dictionary of inputs containing ["input_ids", "attention_mask", "token_type_ids"]
        reduction: Whether to reduce the hidden states ("mean" for averaging over sequence length)
    
    Returns:
        hidden_states: List of tensors with shape [L, D] where L is sequence length and D is hidden dimension
    """
```

This method intelligently handles EOS token detection and provides flexible reduction strategies for different use cases, supporting both token-level and sequence-level representations.

## Structure Integration Capabilities

A key innovation in the Saprot architecture is the seamless integration of structural information into transformer representations through bias features.

### Structure-Aware Attention

The `add_bias_feature` method enables structure integration by adding coordinate-derived features to attention mechanisms [saprot/model/saprot/base.py](saprot/model/saprot/base.py#L327-L336):

```python
def add_bias_feature(self, inputs, coords: List[Dict]) -> torch.Tensor:
    """
    Add structure information as biases to attention map. This function is used to add structure information
    to the model as Evoformer does.
    
    Args:
        inputs: Input dictionary with ["input_ids", "attention_mask", "token_type_ids"]
        coords: Coordinates of backbone atoms with keys ["N", "CA", "C", "O"]
    
    Returns:
        pair_feature: Tensor of shape [B, L, L, 407] representing RBF of distance(400) + angle(7)
    """
```

This approach enables the transformer to incorporate 3D structural information directly into its attention mechanisms, significantly enhancing the model's ability to understand protein structure-function relationships.

## Task-Specific Implementations

The framework provides specialized implementations for various protein prediction tasks, each tailored to leverage the transformer architecture effectively.

### Classification Models

Classification implementations demonstrate the practical application of the transformer architecture [saprot/model/saprot/saprot_classification_model.py](saprot/model/saprot/saprot_classification_model.py#L10-L82):

```python
class SaprotClassificationModel(SaprotBaseModel):
    def forward(self, inputs, coords=None):
        if coords is not None:
            inputs = self.add_bias_feature(inputs, coords)
        
        if self.freeze_backbone:
            # Extract and process hidden states for frozen backbone
            repr = torch.stack(self.get_hidden_states_from_dict(inputs, reduction="mean"))
            x = self.model.classifier.dropout(repr)
            x = self.model.classifier.dense(x)
            x = torch.tanh(x)
            x = self.model.classifier.dropout(x)
            logits = self.model.classifier.out_proj(x)
        else:
            logits = self.model(**inputs).logits
        
        return logits
```

The ProtT5 classification model follows similar patterns but is adapted to the T5 architecture [saprot/model/protT5/protT5_classification_model.py](saprot/model/protT5/protT5_classification_model.py#L10-L106):

```python
class ProtT5ClassificationModel(ProtT5BaseModel):
    def forward(self, inputs, coords=None):
        if coords is not None:
            inputs = self.add_bias_feature(inputs, coords)
        
        if self.freeze_backbone:
            # Similar processing for frozen backbone
            repr = torch.stack(self.get_hidden_states_from_dict(inputs, reduction="mean"))
            # ... classifier processing
        else:
            outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
            repr = outputs.last_hidden_state[:, 1: -1].mean(dim=1)
            logits = self.model.classifier(repr)
        
        return logits
```

## Architecture Comparison

| Feature | ESM-Based (Saprot) | ProtT5-Based |
|---------|-------------------|--------------|
| **Base Architecture** | ESM Transformer | T5 Encoder |
| **Tokenizer** | AutoTokenizer | T5Tokenizer |
| **LoRA Target Modules** | query, key, value, intermediate.dense, output.dense | SelfAttention.*, EncDecAttention.* |
| **Structure Integration** | Native support via bias features | Supported via bias features |
| **Hidden State Access** | outputs["hidden_states"][-1] | outputs.last_hidden_state |
| **Best For** | Structure-aware tasks, complex protein representations | Sequence analysis, transfer learning |

## Next Steps

To deepen your understanding of the SaprotHub architecture:

1. **[Structure-Aware Protein Representation](6-structure-aware-protein-representation)** - Explore how structural information is processed and integrated
2. **[Pre-training and Fine-tuning Strategies](8-pre-training-and-fine-tuning-strategies)** - Learn about training methodologies and optimization approaches
3. **[Zero-shot Mutational Effect Prediction](9-zero-shot-mutational-effect-prediction)** - Discover practical applications of the transformer architecture

The transformer-based architecture in SaprotHub represents a sophisticated approach to protein analysis, combining state-of-the-art transformer models with structure-aware processing and efficient fine-tuning techniques. This foundation enables powerful protein prediction capabilities across diverse biological applications.