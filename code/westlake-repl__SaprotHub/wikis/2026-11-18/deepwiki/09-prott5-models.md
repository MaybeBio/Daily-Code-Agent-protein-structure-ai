# ProtT5 Models

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [saprot/model/protT5/base.py](saprot/model/protT5/base.py)
- [saprot/model/protT5/protT5_classification_model.py](saprot/model/protT5/protT5_classification_model.py)
- [saprot/model/protT5/protT5_regression_model.py](saprot/model/protT5/protT5_regression_model.py)
- [saprot/model/protT5/protT5_token_classification_model.py](saprot/model/protT5/protT5_token_classification_model.py)

</details>



This page documents the ProtT5 models in SaprotHub, focusing on their architecture, implementation, and usage. ProtT5 models are based on the T5 encoder transformer architecture, specifically designed for protein sequence analysis tasks. For information about SaProt models, see [SaProt Base Model](#3.1).

## Overview

ProtT5 models use transformer-based neural networks to learn protein sequence representations. The models leverage the T5 encoder architecture and can be fine-tuned for various downstream tasks using parameter-efficient techniques like LoRA (Low-Rank Adaptation).

```mermaid
classDiagram
    AbstractModel <|-- ProtT5BaseModel
    ProtT5BaseModel <|-- ProtT5ClassificationModel
    ProtT5BaseModel <|-- ProtT5RegressionModel
    ProtT5BaseModel <|-- ProtT5TokenClassificationModel
    
    class AbstractModel {
        +initialize_model()
        +forward()
        +loss_func()
        +training_step()
        +validation_step()
        +test_step()
        +load_checkpoint()
        +save_checkpoint()
    }
    
    class ProtT5BaseModel {
        +task: str
        +config_path: str
        +freeze_backbone: bool
        +gradient_checkpointing: bool
        +lora_kwargs: dict
        +initialize_model()
        +_init_lora()
        +get_hidden_states_from_dict()
        +add_bias_feature()
        +save_checkpoint()
    }
    
    class ProtT5ClassificationModel {
        +num_labels: int
        +initialize_model()
        +forward()
        +loss_func()
        +initialize_metrics()
    }
    
    class ProtT5RegressionModel {
        +test_result_path: str
        +initialize_model()
        +forward()
        +loss_func()
        +initialize_metrics()
    }
    
    class ProtT5TokenClassificationModel {
        +num_labels: int
        +initialize_model()
        +forward()
        +loss_func()
        +initialize_metrics()
        +compute_mcc()
    }
```

Sources: [saprot/model/protT5/base.py:27-393](), [saprot/model/protT5/protT5_classification_model.py:10-106](), [saprot/model/protT5/protT5_regression_model.py:9-126](), [saprot/model/protT5/protT5_token_classification_model.py:10-166]()

## ProtT5BaseModel

`ProtT5BaseModel` serves as the foundation for all ProtT5 models in SaprotHub. It cannot be used directly but provides essential functionality for downstream task-specific models.

### Initialization

The base model is initialized with several key parameters:

```python
def __init__(self,
             task: str,
             config_path: str,
             extra_config: dict = None,
             load_pretrained: bool = False,
             freeze_backbone: bool = False,
             gradient_checkpointing: bool = False,
             lora_kwargs: dict = None,
             **kwargs):
```

- `task`: Specifies the task type ('classification', 'token_classification', 'regression', 'lm', or 'base')
- `config_path`: Path to the HuggingFace configuration file for the T5 model
- `extra_config`: Additional configuration parameters
- `load_pretrained`: Whether to load pretrained weights
- `freeze_backbone`: Whether to freeze the encoder backbone
- `gradient_checkpointing`: Whether to enable gradient checkpointing (for memory efficiency)
- `lora_kwargs`: Configuration for LoRA parameter-efficient fine-tuning

Sources: [saprot/model/protT5/base.py:27-76]()

### Model Initialization

The model initialization process:

1. Sets up the T5 tokenizer based on the provided config path
2. Initializes the appropriate model based on the task type
3. Applies additional configuration as needed

```mermaid
flowchart TD
    Start["initialize_model()"] --> LoadTokenizer["Load T5Tokenizer"]
    LoadTokenizer --> LoadConfig["Load T5Config"]
    LoadConfig --> TaskCheck{"Task Type?"}
    
    TaskCheck -->|"classification"| CLSModel["T5ForSequenceClassification"]
    TaskCheck -->|"token_classification"| TokenModel["T5ForTokenClassification"]
    TaskCheck -->|"regression"| RegModel["T5ForSequenceClassification\nwith num_labels=1"]
    
    CLSModel --> InitClassifier["Initialize classifier head"]
    TokenModel --> InitClassifier
    RegModel --> InitClassifier
    
    subgraph "Classifier Head Structure"
        InitClassifier --> Linear1["Linear(hidden_size, hidden_size)"]
        Linear1 --> ReLU["ReLU activation"]
        ReLU --> Linear2["Linear(hidden_size, num_labels)"]
    end
```

Sources: [saprot/model/protT5/base.py:182-260]()

### LoRA Integration

The base model supports LoRA for parameter-efficient fine-tuning:

1. Configures LoRA adapters for specific modules (attention components)
2. Supports multiple LoRA adapters for ensemble prediction
3. Handles adapter saving and loading

Key LoRA parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| r | 8 | LoRA rank (lower values = fewer parameters) |
| lora_dropout | 0.0 | Dropout rate for LoRA layers |
| lora_alpha | 16 | LoRA scaling factor |

Sources: [saprot/model/protT5/base.py:79-181]()

### Feature Extraction

The model provides methods to extract features from protein sequences:

```python
def get_hidden_states_from_dict(self, inputs: dict, reduction: str = None) -> list:
```

This method processes input token IDs and attention masks to extract hidden representations from the model. If `reduction="mean"`, it averages the representations across the sequence length.

Sources: [saprot/model/protT5/base.py:264-296]()

### Structural Information Integration

The model can incorporate structural information through:

```python
def add_bias_feature(self, inputs, coords: List[Dict]) -> torch.Tensor:
```

This method adds structure information as biases to attention maps, similar to how Evoformer works. It uses backbone atom coordinates (N, CA, C, O) to compute pair features.

Sources: [saprot/model/protT5/base.py:334-347]()

## Task-Specific Models

SaprotHub provides three specialized ProtT5 models for different tasks:

### 1. ProtT5ClassificationModel

For sequence-level classification tasks.

```mermaid
flowchart LR
    Input["Protein Sequence"] --> Tokenize["T5 Tokenizer"]
    Tokenize --> T5Encoder["T5 Encoder"]
    T5Encoder --> PoolMean["Mean Pooling"]
    PoolMean --> Classifier["Classification Head"]
    Classifier --> Output["Class Probabilities"]
```

Key features:
- Takes `num_labels` to specify the number of classes
- Uses mean pooling to aggregate sequence representations
- Uses cross-entropy loss
- Tracks accuracy metrics

Implementation details:
- The classifier head consists of two linear layers with a ReLU activation
- Supports optional structure-aware features through the `coords` parameter

Sources: [saprot/model/protT5/protT5_classification_model.py:10-106]()

### 2. ProtT5RegressionModel

For sequence-level regression tasks.

```mermaid
flowchart LR
    Input["Protein Sequence"] --> Tokenize["T5 Tokenizer"]
    Tokenize --> T5Encoder["T5 Encoder"]
    T5Encoder --> PoolMean["Mean Pooling"]
    PoolMean --> Regressor["Regression Head"]
    Regressor --> Output["Continuous Value"]
```

Key features:
- Uses mean squared error loss
- Tracks multiple metrics: MSE, Spearman correlation, R², Pearson correlation
- Can save test results to a specified path

The model uses the same architecture as the classification model but with a single output unit and different loss function and metrics.

Sources: [saprot/model/protT5/protT5_regression_model.py:9-126]()

### 3. ProtT5TokenClassificationModel

For residue-level (token-level) classification tasks.

```mermaid
flowchart LR
    Input["Protein Sequence"] --> Tokenize["T5 Tokenizer"]
    Tokenize --> T5Encoder["T5 Encoder"]
    T5Encoder --> PerToken["Per-Token Representations"]
    PerToken --> Classifier["Token Classification Head"]
    Classifier --> Output["Per-Residue Classifications"]
```

Key features:
- Predicts a class for each amino acid (token) in the sequence
- Uses cross-entropy loss (ignoring padding tokens)
- Computes Matthews Correlation Coefficient (MCC) in addition to accuracy
- Supports structure-aware features through the `coords` parameter

Unlike the sequence-level models, this model doesn't perform pooling, preserving token-level representations for prediction.

Sources: [saprot/model/protT5/protT5_token_classification_model.py:10-166]()

## Forward Pass Data Flow

The following diagram illustrates the data flow during a forward pass through a ProtT5 model:

```mermaid
flowchart TD
    InputDict["Input Dictionary\n(input_ids, attention_mask)"] --> StructCheck{"Has Structure\nCoordinates?"}
    
    StructCheck -->|"Yes"| AddBias["Add Structural Bias Features"]
    StructCheck -->|"No"| FreezeCheck
    
    AddBias --> FreezeCheck{"Backbone\nFrozen?"}
    
    FreezeCheck -->|"Yes"| GetHidden["Get Hidden States\nwith Reduction"]
    FreezeCheck -->|"No"| ModelForward["Model Forward Pass"]
    
    GetHidden --> ClassifierDrop["Classifier Dropout"]
    ClassifierDrop --> ClassifierDense["Classifier Dense Layer"]
    ClassifierDense --> Tanh["Tanh Activation"]
    Tanh --> ClassifierDrop2["Classifier Dropout"]
    ClassifierDrop2 --> OutProj["Output Projection"]
    
    ModelForward --> LastHidden["Extract Last Hidden State"]
    LastHidden --> TaskCheck{"Task Type?"}
    
    TaskCheck -->|"Classification\nRegression"| MeanPool["Mean Pooling"]
    TaskCheck -->|"Token\nClassification"| NoPool["No Pooling"]
    
    MeanPool --> ClassHead["Classification/Regression Head"]
    NoPool --> TokenHead["Token Classification Head"]
    
    ClassHead --> Logits["Output Logits"]
    TokenHead --> Logits
    OutProj --> Logits
```

Sources: [saprot/model/protT5/protT5_classification_model.py:36-60](), [saprot/model/protT5/protT5_regression_model.py:39-63](), [saprot/model/protT5/protT5_token_classification_model.py:48-70]()

## Integration with SaprotHub

ProtT5 models are registered through the model interface system and can be accessed through:

1. The main SaprotHub notebook interface
2. The specialized ColabProtT5 interface

The models use the `@register_model` decorator to make them available to the SaprotHub system.

## Usage Considerations

When using ProtT5 models, consider the following:

| Aspect | Notes |
|--------|-------|
| Memory Usage | ProtT5 models can be large; consider using gradient checkpointing or LoRA for efficiency |
| Tokenization | Uses T5 tokenizer which handles amino acid sequences differently than language models |
| Task Selection | Choose the appropriate model (Classification, Regression, TokenClassification) based on task |
| Structural Data | Consider adding structural information using the `add_bias_feature` method for potentially improved performance |
| Fine-tuning | LoRA adapters provide parameter-efficient fine-tuning with fewer resources |

## Metrics Visualization

ProtT5 models include built-in visualization of validation metrics using matplotlib through Google Colab widgets. This allows real-time monitoring of training progress.

The `plot_valid_metrics_curve` method creates visualizations for all tracked metrics over training steps.

Sources: [saprot/model/protT5/base.py:366-392]()

---