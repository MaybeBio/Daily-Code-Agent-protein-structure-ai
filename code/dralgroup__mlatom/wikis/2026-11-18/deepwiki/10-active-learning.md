# Active Learning

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/al.py](mlatom/al.py)
- [mlatom/al_utils.py](mlatom/al_utils.py)

</details>



This page documents the active learning system in MLatom, which provides automated iterative machine learning workflows for molecular simulations. The system adaptively samples molecular configurations, trains ML models, and identifies regions of chemical space requiring more data.

For information about the underlying ML models used in active learning, see [Neural Network Models](#4.2). For simulation methods that active learning can employ, see [Molecular Dynamics](#5.2) and [Advanced Dynamics](#5.3).

## System Architecture

The active learning system is built around several key components that work together to create an iterative learning workflow:

### Active Learning Workflow

```mermaid
flowchart TD
    Start["`**Start AL Procedure**
    al class initialization`"] --> InitSample["`**Initial Data Sampling**
    get_initial_data_pool()`"]
    
    InitSample --> InitLabel["`**Label Initial Points**
    reference_method.predict()`"]
    
    InitLabel --> IterStart["`**Begin AL Iteration**
    iteration loop`"]
    
    IterStart --> LabelNew["`**Label New Points**
    label_points()`"]
    
    LabelNew --> TrainModel["`**Train ML Models**
    create_ml_model()`"]
    
    TrainModel --> UseMod["`**Use ML Model**
    use_ml_model()`"]
    
    UseMod --> Sample["`**Sample New Points**
    sampler.sample()`"]
    
    Sample --> UQ["`**Uncertainty Quantification**
    mol.uncertain check`"]
    
    UQ --> CheckConv{"`**Check Convergence**
    min_new_points threshold`"}
    
    CheckConv -->|Not Converged| IterStart
    CheckConv -->|Converged| End["`**AL Converged**
    Final model ready`"]
    
    UQ --> CheckMax{"`**Max Iterations**
    max_iterations check`"}
    CheckMax -->|Exceeded| End
    CheckMax -->|Continue| IterStart
```

Sources: [mlatom/al.py:355-403]()

### Core Classes and Relationships

```mermaid
classDiagram
    class al {
        +String job_name
        +reference_method
        +Sampler initdata_sampler
        +Sampler sampler
        +ml_model model
        +Integer iteration
        +Boolean converged
        +main()
        +get_initial_data_pool()
        +label_points()
        +create_ml_model()
        +use_ml_model()
    }
    
    class Sampler {
        +sampler_function
        +sample(**kwargs)
        +wigner()
        +molecular_dynamics()
        +batch_molecular_dynamics()
        +geometry_optimization()
        +surface_hopping_molecular_dynamics()
    }
    
    class ml_model {
        +main_model
        +aux_model
        +uq_threshold
        +train(molecular_database)
        +predict(molecular_database)
        +threshold_metric()
    }
    
    class ml_model_trainer {
        +String ml_model_type
        +Dict hyperparameters
        +main_model_trainer()
        +aux_model_trainer()
    }
    
    al --> Sampler : uses for sampling
    al --> ml_model : creates and uses
    ml_model --> ml_model_trainer : trained by
    Sampler --> molecular_database : produces
    ml_model --> molecular_database : predicts on
```

Sources: [mlatom/al.py:16-315](), [mlatom/al_utils.py:8-35](), [mlatom/al_utils.py:1207-1388](), [mlatom/al_utils.py:1001-1037]()

## Active Learning Process

### Initialization and Configuration

The `al` class is initialized with extensive configuration options that control every aspect of the active learning workflow:

| Parameter Category | Key Parameters | Description |
|-------------------|----------------|-------------|
| **Job Control** | `job_name`, `max_iterations` | Basic job settings and termination conditions |
| **Reference Method** | `reference_method` | High-accuracy method for labeling data |
| **Initial Sampling** | `initdata_sampler`, `initial_points_refinement` | Strategy for generating initial training data |
| **ML Models** | `ml_model_type`, `device`, `property_to_learn` | ML model configuration |
| **Active Sampling** | `sampler`, `new_points`, `min_new_points` | Strategy for sampling new uncertain points |
| **Convergence** | `min_new_points`, `max_iterations` | Criteria for stopping the AL procedure |

Sources: [mlatom/al.py:20-49](), [mlatom/al.py:50-315]()

### Initial Data Pool Generation

The system supports multiple strategies for generating initial training data:

```mermaid
flowchart LR
    InitGen["`**Initial Data Generation**
    get_initial_data_pool()`"] --> Strategy{"`**Refinement Strategy**
    initial_points_refinement`"}
    
    Strategy -->|cross-validation| CV["`**Cross Validation**
    get_initial_data_pool_cross_validation()`"]
    Strategy -->|validation| Val["`**Validation**
    get_initial_data_pool_cross_validation()`"]
    Strategy -->|one-shot| OneShot["`**One Shot**
    get_initial_data_pool_one_shot()`"]
    
    CV --> CVLoop["`**CV Loop**
    init_cross_validation()`"]
    Val --> ValLoop["`**Validation Loop**
    init_validation()`"]
    
    CVLoop --> Check["`**Learning Curve Check**
    Linear regression analysis`"]
    ValLoop --> Check
    OneShot --> Sample["`**Single Sample**
    initdata_sampler.sample()`"]
    
    Check --> Converge{"`**Improvement Check**
    RMSE threshold or curve fit`"}
    Sample --> Label["`**Label Points**
    reference_method.predict()`"]
    
    Converge -->|Continue| CVLoop
    Converge -->|Stop| Label
```

Sources: [mlatom/al.py:414-432](), [mlatom/al.py:436-511](), [mlatom/al.py:570-585]()

## Sampling Strategies

The `Sampler` class provides multiple strategies for generating molecular configurations:

### Available Sampling Methods

| Sampler Type | Function | Use Case |
|--------------|----------|----------|
| **wigner** | `wigner()` | Quantum harmonic oscillator sampling around equilibrium |
| **md** | `molecular_dynamics()` | Classical MD trajectories with uncertainty stopping |
| **batch_md** | `batch_molecular_dynamics()` | Parallel MD trajectories |
| **geomopt** | `geometry_optimization()` | Geometry optimization with uncertainty checking |
| **lzsh** | `surface_hopping_molecular_dynamics()` | Surface hopping for multi-state systems |
| **random** | `random()` | Random displacement from reference geometry |
| **fixed** | `fixed()` | Use pre-defined molecular configurations |

Sources: [mlatom/al_utils.py:8-33]()

### Molecular Dynamics Sampling

```mermaid
flowchart TD
    InitCond["`**Initial Conditions**
    initcond_sampler.sample()`"] --> SetupMD["`**Setup MD**
    md or md_parallel`"]
    
    SetupMD --> RunTraj["`**Run Trajectories**
    ml_model propagation`"]
    
    RunTraj --> CheckUQ["`**Check Uncertainty**
    internal_stop_function()`"]
    
    CheckUQ --> Uncertain{"`**mol.uncertain**
    UQ threshold check`"}
    
    Uncertain -->|True| AddPoint["`**Add to Database**
    moldb.append(mol)`"]
    Uncertain -->|False| Continue["`**Continue MD**
    Next time step`"]
    
    Continue --> CheckTime{"`**Max Time?**
    maximum_propagation_time`"}
    CheckTime -->|No| CheckUQ
    CheckTime -->|Yes| FinishTraj["`**Trajectory Complete**
    Store final results`"]
    
    AddPoint --> FinishTraj
```

Sources: [mlatom/al_utils.py:167-243](), [mlatom/al_utils.py:246-321]()

## Machine Learning Models

### Dual Model Architecture

The active learning system employs a dual model architecture for uncertainty quantification:

```mermaid
graph TD
    TrainData["`**Training Database**
    molecular_database`"] --> Split["`**Train/Val Split**
    90%/10% split`"]
    
    Split --> MainTrain["`**Main Model Training**
    Energy + Gradients`"]
    Split --> AuxTrain["`**Auxiliary Model Training**
    Energy only`"]
    
    MainTrain --> MainModel["`**main_model**
    Full property prediction`"]
    AuxTrain --> AuxModel["`**aux_model**
    Energy-only prediction`"]
    
    MainModel --> Predict["`**Prediction**
    mol.energy, mol.energy_gradients`"]
    AuxModel --> Predict2["`**Prediction**
    mol.aux_energy`"]
    
    Predict --> UQCalc["`**UQ Calculation**
    mol.uq = |energy - aux_energy|`"]
    Predict2 --> UQCalc
    
    UQCalc --> Threshold{"`**Threshold Check**
    mol.uq > uq_threshold`"}
    
    Threshold -->|True| Uncertain["`**mol.uncertain = True**
    Needs labeling`"]
    Threshold -->|False| Certain["`**mol.uncertain = False**
    Confident prediction`"]
```

Sources: [mlatom/al_utils.py:1261-1360](), [mlatom/al_utils.py:1362-1379]()

### Supported Model Types

The system supports multiple ML model architectures:

| Model Type | Class | Capabilities |
|------------|-------|--------------|
| **KREG** | `models.kreg` | Kernel ridge regression with hyperparameter optimization |
| **ANI** | `models.ani` | Neural network potentials with TorchANI |
| **MACE** | `models.mace` | Message-passing neural networks |
| **MSANI** | `models.msani` | Multi-state ANI for excited states |

Sources: [mlatom/al_utils.py:1039-1079](), [mlatom/al_utils.py:1081-1113](), [mlatom/al_utils.py:1115-1149]()

## Uncertainty Quantification

### Threshold Determination

The system automatically determines uncertainty thresholds using statistical metrics:

```mermaid
flowchart LR
    ValSet["`**Validation Set**
    10% of training data`"] --> Predict["`**Model Predictions**
    main_model and aux_model`"]
    
    Predict --> CalcUQ["`**Calculate UQ**
    |energy - aux_energy|`"]
    
    CalcUQ --> Metric["`**Threshold Metric**
    threshold_metric()`"]
    
    Metric --> M3MAD["`**M + 3×MAD**
    Median + 3×MAD`"]
    Metric --> Max["`**Maximum**
    max(absdevs)`"]
    
    M3MAD --> SetThresh["`**Set Threshold**
    uq_threshold`"]
    Max --> SetThresh
    
    SetThresh --> UpdateAL["`**Update AL Info**
    al_info['uq_threshold']`"]
```

Sources: [mlatom/al_utils.py:1389-1404](), [mlatom/al_utils.py:1347-1354]()

### Multi-State Uncertainty

For multi-state systems (NAMD), uncertainty is checked across multiple electronic states:

```mermaid
flowchart TD
    MultiState["`**Multi-State System**
    nstates > 1`"] --> CalcUQ["`**Calculate UQ per State**
    uq[i] = |energy[i] - aux_energy[i]|`"]
    
    CalcUQ --> CheckCurrent["`**Check Current State**
    uq[current_state] > threshold[current_state]`"]
    
    CheckCurrent --> CheckAdjacent["`**Check Adjacent States**
    uq[adjacent] > threshold[adjacent]`"]
    
    CheckAdjacent --> Decision{"`**Any Uncertain?**
    check_flag`"}
    
    Decision -->|True| Uncertain["`**mol.uncertain = True**
    Needs labeling`"]
    Decision -->|False| Certain["`**mol.uncertain = False**
    Confident prediction`"]
```

Sources: [mlatom/al_utils.py:1771-1793]()

## Integration with Simulations

The active learning system integrates seamlessly with various simulation methods to enable automated discovery of important molecular configurations. The uncertainty-based stopping criteria ensure that simulations are terminated when the ML model becomes unreliable, triggering the addition of new training data.

Sources: [mlatom/al.py:1-10](), [mlatom/al_utils.py:1-7]()

---