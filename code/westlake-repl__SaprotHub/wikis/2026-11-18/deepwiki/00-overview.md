# Overview

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [Figure/wechat_group.jpg](Figure/wechat_group.jpg)
- [README.md](README.md)
- [colab/SaprotHub.ipynb](colab/SaprotHub.ipynb)
- [colab/not_use_only_for_dev.ipynb](colab/not_use_only_for_dev.ipynb)
- [local_server/jupyter_notebook_config.py](local_server/jupyter_notebook_config.py)
- [saprot/utils/foldseek_util.py](saprot/utils/foldseek_util.py)

</details>



SaprotHub is a framework designed to democratize protein language model (PLM) training and usage for biologists without requiring extensive machine learning expertise. It provides user-friendly interfaces and tools that enable researchers to train, fine-tune, share, and collaborate on protein language models for various biological prediction tasks.

For more detailed information about specific concepts introduced here, see [Key Concepts and Terminology](#1.1).

## System Architecture

SaprotHub integrates several components that work together to provide a seamless experience for biologists working with protein language models.

### High-Level Architecture

```mermaid
graph TD
    User["Biologist/Researcher"] --> |"Interacts with"| Colab["Google Colab"]
    User --> |"or"| LocalServer["Local Server"]
    
    Colab --> |"Runs"| ColabSaprot["ColabSaprot Interface"]
    LocalServer --> |"Runs"| ColabSaprot
    
    subgraph "Interfaces"
        ColabSaprot --> |"Primary"| SaprotNotebook["SaprotHub Notebook"]
        ColabSaprot --> |"Specialized"| ColabProtT5["ColabProtT5"]
        ColabSaprot --> |"Specialized"| ColabProTrek["ColabProTrek"]
    end
    
    subgraph "Model Training"
        SaprotNotebook --> TrainPipeline["Training Pipeline"]
        
        TrainPipeline --> |"Utilizes"| PLM["Protein Language Models"]
        TrainPipeline --> |"Uses"| PEFT["Parameter-Efficient Fine-Tuning"]
        TrainPipeline --> |"Creates"| Adapters["Task-specific Adapters"]
    end
    
    subgraph "Data Flow"
        SaprotNotebook --> DataInput["Data Input Methods"]
        DataInput --> |"Process"| LMDB["LMDB Datasets"]
        LMDB --> TrainingPipeline["Training Pipeline"]
    end
    
    subgraph "Model Sharing"
        Adapters --> HFHub["HuggingFace Hub"]
        HFHub --> |"Download models"| SaprotNotebook
    end
```

Sources:
- [README.md:1-10]()
- [colab/SaprotHub.ipynb:1-37]()

## Core Components

### ColabSaprot Interface

The ColabSaprot interface is the primary way researchers interact with SaprotHub. It provides a user-friendly environment in Google Colab or local servers for protein language model tasks.

#### Supported Input Types

| Input Type | Description |
|------------|-------------|
| Single AA Sequence | Amino acid sequence input |
| Single SA Sequence | Structure-aware sequence input |
| Single UniProt ID | UniProt database identifier |
| Single PDB/CIF Structure | 3D protein structure file |
| Multiple AA/SA Sequences | Batch processing of sequences |
| Pair Sequences | For protein-protein interaction tasks |
| SaprotHub Dataset | Pre-processed datasets from the hub |

Sources:
- [colab/SaprotHub.ipynb:45-60]()
- [colab/SaprotHub.ipynb:250-329]()

### Model Architecture

SaprotHub implements a hierarchical model structure organized by task type:

```mermaid
classDiagram
    AbstractModel <|-- SaprotBaseModel
    AbstractModel <|-- ProtT5BaseModel
    
    SaprotBaseModel <|-- SaprotClassificationModel
    SaprotBaseModel <|-- SaprotRegressionModel
    SaprotBaseModel <|-- SaprotTokenClassificationModel
    SaprotBaseModel <|-- SaprotPairClassificationModel
    SaprotBaseModel <|-- SaprotPairRegressionModel
    
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
    }
    
    class SaprotBaseModel {
        +task: str
        +config_path: str
        +_init_lora()
        +get_hidden_states_from_dict()
        +get_hidden_states_from_seqs()
    }
    
    class ProtT5BaseModel {
        +task: str
        +config_path: str
        +_init_lora()
        +get_hidden_states_from_dict()
    }
```

The task types in SaprotHub's model hierarchy include:

| Task Type | Model Suffix | Description |
|-----------|--------------|-------------|
| `classification` | `SaprotClassificationModel` | Protein-level classification tasks (e.g., function prediction) |
| `regression` | `SaprotRegressionModel` | Protein-level regression tasks (e.g., stability prediction) |
| `token_classification` | `SaprotTokenClassificationModel` | Residue-level classification tasks (e.g., secondary structure) |
| `pair_classification` | `SaprotPairClassificationModel` | Protein-protein interaction classification |
| `pair_regression` | `SaprotPairRegressionModel` | Protein-protein interaction regression |

Sources:
- [colab/SaprotHub.ipynb:290-311]()

### Data Processing Pipeline

The data processing pipeline is responsible for converting various input formats into structured datasets for model training.

```mermaid
flowchart TD
    Input["User Input Data"] --> DataType{"Data Type?"}
    
    DataType -->|"AA Sequence"| AASeq["Amino Acid Sequence"]
    DataType -->|"SA Sequence"| SASeq["Structure-Aware Sequence"]
    DataType -->|"UniProt ID"| UniProt["UniProt Identifier"]
    DataType -->|"PDB/CIF Structure"| PDBStruct["Protein Structure"]
    DataType -->|"Multiple Sequences"| MultiSeq["Multiple Sequences CSV"]
    DataType -->|"Multiple Structures"| MultiStruct["Multiple Structures CSV"]
    
    AASeq --> Process["Data Processing"]
    SASeq --> Process
    UniProt --> |"Download Structure"| AlphaFold["AlphaFold DB"]
    AlphaFold --> Process
    PDBStruct --> |"Extract Chain"| Process
    MultiSeq --> Process
    MultiStruct --> Process
    
    Process --> |"Structure Extraction"| Foldseek["Foldseek Utility"]
    Process --> Tokenization["Sequence Tokenization"]
    
    Foldseek --> SAConversion["Convert to SA Sequence"]
    Tokenization --> Encoding["Model Encoding"]
    SAConversion --> Encoding
    
    Encoding --> LMDB["LMDB Database"]
    LMDB --> TrainingPipeline["Training Pipeline"]
```

Key steps in the data processing pipeline:

1. **Input Processing**: Handles various data formats including AA sequences, SA sequences, UniProt IDs, and PDB/CIF files
2. **Structure Extraction**: Uses Foldseek to extract structural information from 3D protein structures
3. **Data Conversion**: Transforms inputs into formats suitable for model training
4. **LMDB Storage**: Stores processed data in LMDB format for efficient access during training

Sources:
- [colab/SaprotHub.ipynb:574-627]()
- [saprot/utils/foldseek_util.py:12-87]()

### Training Pipeline with LoRA

SaprotHub uses Low-Rank Adaptation (LoRA) for efficient fine-tuning of protein language models.

```mermaid
graph TB
    PretrainedModel["Pre-trained Protein Language Model"] --> ModelChoice{"Model Type"}
    ModelChoice -->|"SaProt"| SaprotBaseModel["SaProt Base Model"]
    ModelChoice -->|"ProtT5"| ProtT5Model["ProtT5 Base Model"]
    
    SaprotBaseModel --> LoRA["LoRA Adapter Integration"]
    ProtT5Model --> LoRA
    
    LoRA --> TaskAdapter{"Task-specific Adapter"}
    TaskAdapter -->|"Classification"| ClsAdapter["Classification Adapter"]
    TaskAdapter -->|"Regression"| RegAdapter["Regression Adapter"]
    TaskAdapter -->|"Token Classification"| TokenAdapter["Token Classification Adapter"]
    TaskAdapter -->|"Pair Tasks"| PairAdapter["Pair Tasks Adapter"]
    
    ClsAdapter --> FinetuneProcess["Fine-tuning Process"]
    RegAdapter --> FinetuneProcess
    TokenAdapter --> FinetuneProcess
    PairAdapter --> FinetuneProcess
    
    FinetuneProcess --> SaveAdapter["Save Adapter"]
    SaveAdapter --> |"Upload"| HuggingFace["HuggingFace Hub"]
    SaveAdapter --> |"Local Storage"| LocalAdapter["Local Adapter"]
    
    HuggingFace --> |"Download for inference"| Inference["Model Inference"]
    LocalAdapter --> Inference
```

The LoRA approach offers several advantages:

1. **Parameter-Efficient Fine-Tuning**: Only trains a small number of parameters rather than the entire model
2. **Reduced Memory Requirements**: Enables training on hardware with limited resources
3. **Easy Sharing**: Small adapter files (typically <10MB) instead of full models
4. **Flexible Deployment**: Adapters can be swapped without reloading the base model

Sources:
- [colab/SaprotHub.ipynb:347-456]()

## Deployment Options

SaprotHub can be deployed in two main environments:

```mermaid
flowchart TB
    User["Researcher/Biologist"] --> DeployChoice{"Deployment Choice"}
    
    DeployChoice -->|"Cloud Option"| Colab["Google Colab"]
    DeployChoice -->|"Local Option"| LocalServer["Local Server"]
    
    subgraph "Google Colab Deployment"
        Colab --> |"Open"| SaprotNotebook["SaprotHub.ipynb"]
        SaprotNotebook --> |"Select"| GPUType["GPU Type: T4/L4/A100"]
        SaprotNotebook --> |"Run"| Installation["Install Dependencies"]
        Installation --> ColabRun["Run SaprotHub"]
    end
    
    subgraph "Local Server Deployment"
        LocalServer --> |"OS Type?"| OSChoice{"OS Type"}
        OSChoice -->|"Linux"| LinuxSetup["bash install.sh"]
        OSChoice -->|"Windows"| WindowsSetup["Docker Deployment"]
        
        LinuxSetup --> RunServer["bash run.sh"]
        WindowsSetup --> RunServer
        
        RunServer --> JupyterServer["Jupyter Server"]
        JupyterServer --> |"Connect"| ColabInterface["Colab Interface"]
        JupyterServer --> |"Port 12315"| Token["Token: SaprotHub"]
    end
    
    ColabRun --> ModelTraining["Model Training/Prediction"]
    ColabInterface --> ModelTraining
```

### Google Colab Deployment

The Google Colab deployment is the simplest option for most users:

1. Open the SaprotHub notebook in Google Colab
2. Select an appropriate GPU type based on your needs:
   - T4 GPU (Free): For basic tasks and smaller models
   - L4 GPU (Colab Pro): For larger models with more memory
   - A100 GPU (Colab Pro): For training large models with highest performance
3. Run the installation cell
4. Use the interactive interface

### Local Server Deployment

For those who prefer local deployment or need more control:

1. Clone the SaprotHub repository
2. Install dependencies using the provided scripts:
   - Linux: Use `install.sh` and `run.sh`
   - Windows: Deploy through Docker
3. Access the Jupyter server on port 12315 with token "SaprotHub"
4. Connect to the ColabSaprot interface

Sources:
- [README.md:26-27]()
- [local_server/jupyter_notebook_config.py:930-939]()
- [colab/not_use_only_for_dev.ipynb:41-49]()

## Community Model Sharing

SaprotHub facilitates community collaboration through the Open Protein Modeling Consortium (OPMC), a collaborative initiative aimed at democratizing protein language models.

Key features of the community sharing approach:

1. **HuggingFace Integration**: Models trained in SaprotHub can be directly uploaded to HuggingFace
2. **Adapter-Based Sharing**: Small, task-specific adapters instead of full models
3. **Cross-Institution Collaboration**: Researchers from different institutions can build on each other's models
4. **Specialized Interfaces**: Support for multiple protein language models through specialized interfaces

The OPMC currently includes several tools:
- ColabSaprot (AA+3Di sequences)
- ColabProTrek (sequence-structure alignment)
- ColabProtT5 (amino acid sequences)
- ColabMETL (mutational effect transfer learning)
- Other specialized protein modeling tools (Evolla, Pinal, ProTrek)

Sources:
- [README.md:30-43]()
- [README.md:175-178]()

## Summary

SaprotHub provides a comprehensive framework for democratizing protein language models through:

1. **User-Friendly Interfaces**: Making sophisticated models accessible to biologists
2. **Efficient Fine-Tuning**: Using LoRA to enable training on limited resources
3. **Flexible Data Processing**: Supporting various protein data formats
4. **Collaborative Ecosystem**: Facilitating model sharing and collaboration
5. **Multiple Deployment Options**: Supporting both cloud and local deployment

For more details on specific components, see the related pages on the [ColabSaprot Interface](#2), [Model Architecture](#3), [Data Processing](#4), [Training Pipeline](#5), and [Deployment Options](#6).

---