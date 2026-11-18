# Machine Learning Systems

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/aiqm1.py](mlatom/aiqm1.py)
- [mlatom/aiqm2.py](mlatom/aiqm2.py)
- [mlatom/al.py](mlatom/al.py)
- [mlatom/al_utils.py](mlatom/al_utils.py)
- [mlatom/interfaces/torchani_interface.py](mlatom/interfaces/torchani_interface.py)
- [mlatom/model_cls.py](mlatom/model_cls.py)

</details>



This page documents MLatom's machine learning capabilities, including active learning workflows, neural network models, and AI-enhanced quantum mechanical methods. The ML systems provide automated model training, uncertainty quantification, and hybrid AI-QM approaches for molecular simulations.

For quantum chemistry interfaces that these ML models can interface with, see [Quantum Chemistry Interfaces](#6). For core data structures used by ML models, see [Data Structures](#2.1). For the overall model framework architecture, see [Model Framework](#2.2).

## Architecture Overview

The machine learning systems in MLatom are built around several core components that work together to provide comprehensive ML-driven molecular modeling capabilities.

**ML System Architecture**
```mermaid
graph TB
    subgraph "Active Learning System"
        AL["al<br/>(al.py)"]
        SAMPLERS["Sampling Strategies<br/>(al_utils.py)"]
        UQ["Uncertainty Quantification"]
    end
    
    subgraph "Neural Network Models"
        ANI["ani<br/>(torchani_interface.py)"]
        TORCHANI["TorchANI Interface"]
        MODELS["Pre-trained Models<br/>(ANI-1x, ANI-2x, etc.)"]
    end
    
    subgraph "AI-Enhanced Methods"
        AIQM1["aiqm1<br/>(aiqm1.py)"]
        AIQM2["aiqm2<br/>(aiqm2.py)"]
        COMPOSITION["Model Tree Composition"]
    end
    
    subgraph "Base Framework"
        ML_MODEL["ml_model<br/>(model_cls.py)"]
        MODEL_TREE["model_tree_node<br/>(model_cls.py)"]
        HYPEROPT["Hyperparameter Optimization"]
    end
    
    AL --> SAMPLERS
    AL --> ANI
    AL --> UQ
    
    ANI --> TORCHANI
    ANI --> MODELS
    
    AIQM1 --> ANI
    AIQM1 --> COMPOSITION
    AIQM2 --> ANI
    AIQM2 --> COMPOSITION
    
    COMPOSITION --> MODEL_TREE
    ANI --> ML_MODEL
    AL --> ML_MODEL
    ML_MODEL --> HYPEROPT
```

Sources: [mlatom/al.py](), [mlatom/interfaces/torchani_interface.py](), [mlatom/aiqm1.py](), [mlatom/aiqm2.py](), [mlatom/model_cls.py]()

## Active Learning System

The active learning system automates the iterative process of training ML models, sampling new points based on uncertainty, and retraining models with expanded datasets.

### Core Active Learning Workflow

The main active learning class `al` orchestrates the entire workflow:

| Component | Class/Function | Description |
|-----------|----------------|-------------|
| Main Controller | `al` | Manages the complete active learning cycle |
| Samplers | `Sampler` | Various sampling strategies for new points |
| Model Trainers | `ml_model_trainer` | Handles ML model training |
| Uncertainty Quantification | `uq` methods | Evaluates model uncertainty |

**Active Learning Process Flow**
```mermaid
flowchart TD
    START["Start Active Learning"] --> INIT["Initial Data Sampling<br/>get_initial_data_pool()"]
    INIT --> LABEL1["Label Initial Points<br/>label_points()"]
    LABEL1 --> TRAIN["Train ML Model<br/>create_ml_model()"]
    TRAIN --> SAMPLE["Sample New Points<br/>use_ml_model()"]
    SAMPLE --> UNCERTAIN{"Points Above<br/>UQ Threshold?"}
    UNCERTAIN -->|Yes| LABEL2["Label New Points<br/>label_points()"]
    UNCERTAIN -->|No| CONVERGED["AL Converged"]
    LABEL2 --> UPDATE["Update Training Set"]
    UPDATE --> RETRAIN["Retrain Model<br/>create_ml_model()"]
    RETRAIN --> SAMPLE
    
    subgraph "Sampling Methods"
        WIGNER["Wigner Sampling"]
        MD["Molecular Dynamics"]
        GEOMOPT["Geometry Optimization"]
        NAMD["Surface Hopping MD"]
    end
    
    SAMPLE --> WIGNER
    SAMPLE --> MD  
    SAMPLE --> GEOMOPT
    SAMPLE --> NAMD
```

Sources: [mlatom/al.py:355-403](), [mlatom/al.py:414-584](), [mlatom/al_utils.py:8-757]()

### Sampling Strategies

The `Sampler` class provides multiple strategies for generating candidate points:

| Sampler | Method | Use Case |
|---------|--------|----------|
| `wigner` | Quantum harmonic oscillator sampling | Initial conditions generation |
| `md` | Molecular dynamics trajectories | Dynamic sampling |
| `batch_md` | Parallel MD trajectories | High-throughput sampling |
| `geomopt` | Geometry optimization paths | Transition state searches |
| `lzsh` | Landau-Zener surface hopping | Nonadiabatic dynamics |

The samplers are implemented with a common interface in [mlatom/al_utils.py:34-35]():

```python
def sample(self,**kwargs):
    return self.sampler_function(**kwargs)
```

Sources: [mlatom/al_utils.py:8-33](), [mlatom/al_utils.py:83-123](), [mlatom/al_utils.py:167-243]()

## Neural Network Models

The neural network models are primarily based on the ANI (Accurate Neural Network Interatomic potentials) architecture, interfaced through TorchANI.

### ANI Model Implementation

The `ani` class provides a complete interface to TorchANI for training and prediction:

**ANI Model Architecture**
```mermaid
graph TB
    subgraph "ANI Model Components"
        AEV["AEV Computer<br/>Atomic Environment Vectors"]
        NN["Neural Networks<br/>Species-specific networks"]
        ENERGY["Energy Prediction"]
        FORCES["Force Calculation<br/>-∇E"]
    end
    
    subgraph "Model Variants"
        ANI1X["ANI-1x<br/>Pre-trained"]
        ANI1CCX["ANI-1ccx<br/>Coupled-cluster trained"]
        ANI2X["ANI-2x<br/>Extended training"]
        CUSTOM["Custom Models<br/>User-trained"]
    end
    
    subgraph "Training Infrastructure"
        HYPERPARAMS["Hyperparameters<br/>Learning rates, batch size"]
        OPTIMIZERS["Optimizers<br/>AdamW + SGD"]
        SCHEDULERS["LR Schedulers<br/>ReduceLROnPlateau"]
    end
    
    AEV --> NN
    NN --> ENERGY
    ENERGY --> FORCES
    
    HYPERPARAMS --> OPTIMIZERS
    OPTIMIZERS --> SCHEDULERS
```

Sources: [mlatom/interfaces/torchani_interface.py:86-139](), [mlatom/interfaces/torchani_interface.py:277-305]()

### Key Features

The ANI implementation includes:

- **Hyperparameter Management**: Comprehensive hyperparameter system with optimization support [mlatom/interfaces/torchani_interface.py:99-127]()
- **Multi-GPU Support**: CUDA device management and batch processing [mlatom/interfaces/torchani_interface.py:140-159]()
- **Energy and Force Training**: Joint training on energies and gradients [mlatom/interfaces/torchani_interface.py:495-520]()
- **Model Loading/Saving**: Checkpoint management and model persistence [mlatom/interfaces/torchani_interface.py:175-276]()

### Training Process

The training process supports validation monitoring and early stopping:

```python
# Key training parameters from hyperparameters
batch_size = 8
max_epochs = 1000000
learning_rate = 0.001
early_stopping_learning_rate = 1.0E-5
force_coefficient = 0.1
```

Sources: [mlatom/interfaces/torchani_interface.py:308-544]()

## AI-Enhanced Quantum Methods

The AI-enhanced methods combine neural networks with quantum mechanical corrections to achieve high accuracy for molecular properties.

### AIQM1 Method

AIQM1 combines ANI neural networks with quantum mechanical corrections:

**AIQM1 Composition Structure**
```mermaid
graph TB
    subgraph "AIQM1 Components"
        ANI_NN["8 ANI Neural Networks<br/>ani_nns_in_aiqm1"]
        ATOMIC_SHIFT["Atomic Energy Shifts<br/>atomic_energy_shift"]
        ODM2["ODM2* Method<br/>Quantum corrections"]
        D4["D4 Dispersion<br/>wb97x functional"]
    end
    
    subgraph "Model Tree Structure"
        ROOT["aiqm1_model<br/>model_tree_node"]
        AVG["Average Operation<br/>operator='average'"]
        SUM["Sum Operation<br/>operator='sum'"]
    end
    
    ANI_NN --> AVG
    AVG --> SUM
    ATOMIC_SHIFT --> SUM
    ODM2 --> SUM
    D4 --> SUM
    SUM --> ROOT
    
    subgraph "Supported Methods"
        AIQM1_BASE["AIQM1<br/>Base method"]
        AIQM1_DFT["AIQM1@DFT<br/>DFT reference"]
        AIQM1_DFTS["AIQM1@DFT*<br/>No dispersion"]
    end
```

Sources: [mlatom/aiqm1.py:48-66](), [mlatom/aiqm1.py:171-276]()

### AIQM2 Method

AIQM2 uses GFN2-xTB* as the base quantum method:

| Component | Purpose | Implementation |
|-----------|---------|----------------|
| `gfn2xtbstar` | Base quantum method | GFN2-xTB* interface |
| `aiqm2_nn` | ML corrections | 8 ANI models averaged |
| `d4wb97x` | Dispersion corrections | D4 with wb97x functional |

The model composition follows the same tree structure as AIQM1 but with different base methods [mlatom/aiqm2.py:122-164]().

### Model Tree Composition

Both AIQM methods use the `model_tree_node` system for composing multiple models:

```python
# Example composition operators
operator='predict'    # Apply model prediction
operator='average'     # Average multiple predictions  
operator='sum'        # Sum contributions
operator='weighted_sum' # Weighted combination
```

This allows flexible combination of different theoretical methods and ML models [mlatom/model_cls.py:953-1077]().

Sources: [mlatom/aiqm1.py:15-132](), [mlatom/aiqm2.py:5-165](), [mlatom/model_cls.py:953-1135]()

## Model Framework and Base Classes

The ML system is built on a hierarchy of base classes that provide common functionality:

**Model Class Hierarchy**
```mermaid
graph TB
    MODEL["model<br/>(model_cls.py)"] --> ML_MODEL["ml_model<br/>Training capabilities"]
    MODEL --> TORCH_MODEL["torch_model<br/>PyTorch integration"]
    MODEL --> METHOD_MODEL["method_model<br/>QM method interface"]
    
    TORCH_MODEL --> TORCHANI_MODEL["torchani_model<br/>TorchANI specific"]
    
    ML_MODEL --> ANI_CLASS["ani<br/>(torchani_interface.py)"]
    TORCHANI_MODEL --> ANI_CLASS
    TORCHANI_MODEL --> AIQM1_CLASS["aiqm1<br/>(aiqm1.py)"]
    METHOD_MODEL --> AIQM1_CLASS
    METHOD_MODEL --> AIQM2_CLASS["aiqm2<br/>(aiqm2.py)"]
    
    MODEL --> DOWNLOADABLE["downloadable_model<br/>Auto-download models"]
    DOWNLOADABLE --> AIQM1_CLASS
    DOWNLOADABLE --> AIQM2_CLASS
```

### Key Base Class Features

| Base Class | Key Features | File Reference |
|------------|--------------|----------------|
| `model` | Thread management, prediction interface | [model_cls.py:20-131]() |
| `ml_model` | Training, validation, hyperparameter optimization | [model_cls.py:336-847]() |
| `torch_model` | PyTorch thread configuration | [model_cls.py:132-144]() |
| `downloadable_model` | Automatic model downloading | [model_cls.py:201-334]() |

### Hyperparameter System

The framework includes a sophisticated hyperparameter management system:

```python
class hyperparameters(UserDict):
    # Auto-converts values to hyperparameter objects
    # Supports optimization spaces: 'linear', 'log'
    # Includes validation and type casting
```

Hyperparameter optimization supports multiple algorithms including grid search, TPE (Tree-structured Parzen Estimator), and scipy optimizers [mlatom/model_cls.py:602-721]().

Sources: [mlatom/model_cls.py:20-952](), [mlatom/model_cls.py:849-951]()

---