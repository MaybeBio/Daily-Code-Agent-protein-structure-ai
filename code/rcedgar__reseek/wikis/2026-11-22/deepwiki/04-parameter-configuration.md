# Parameter Configuration

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/dssparams.cpp](src/dssparams.cpp)
- [src/dssparams.h](src/dssparams.h)
- [src/namedparams.cpp](src/namedparams.cpp)

</details>



This document covers the parameter configuration system in reseek, specifically the `DSSParams` class and its role in controlling the behavior of the core alignment engine. The parameter system provides three algorithm modes with different speed-accuracy tradeoffs, configurable feature weights, gap penalties, and filtering thresholds.

For information about the alignment algorithms themselves, see [DSSAligner Class](#3.1). For command-line options and usage, see [Commands and Options](#6.1).

## DSSParams Class Overview

The `DSSParams` class serves as the central configuration hub for the alignment engine. It manages algorithm mode selection, feature weights, scoring matrices, gap penalties, and various filtering parameters that control the speed-accuracy tradeoff of the search process.

```mermaid
graph TB
    subgraph "Parameter Configuration System"
        DSSParams["DSSParams<br/>Central Configuration"]
        AlgoMode["Algorithm Mode Selection<br/>Fast/Sensitive/VerySensitive"]
        FeatureWeights["Feature Weights<br/>8 Default Features"]
        GapPenalties["Gap Penalties<br/>Open/Extend"]
        FilterParams["Filter Parameters<br/>Omega, MKFL, HSP Thresholds"]
    end
    
    subgraph "Input Sources"
        CommandLine["Command Line Options<br/>-fast, -sensitive, -verysensitive"]
        TSVFile["TSV Parameter Files<br/>FromTsv()"]
        ParamString["Parameter Strings<br/>FromParamStr()"]
        Defaults["Default Values<br/>SetDefaults()"]
    end
    
    subgraph "Output Targets"
        Aligner["DSSAligner<br/>Uses scoring matrices"]
        Filters["MuFilter/PostMuFilter<br/>Uses thresholds"]
        Scorer["Scoring System<br/>Uses feature weights"]
    end
    
    CommandLine --> AlgoMode
    TSVFile --> DSSParams
    ParamString --> DSSParams
    Defaults --> DSSParams
    
    DSSParams --> AlgoMode
    DSSParams --> FeatureWeights
    DSSParams --> GapPenalties
    DSSParams --> FilterParams
    
    AlgoMode --> Aligner
    FeatureWeights --> Scorer
    GapPenalties --> Aligner
    FilterParams --> Filters
```

Sources: [src/dssparams.h:27-118](), [src/dssparams.cpp:44-110]()

## Algorithm Modes

The system provides three predefined algorithm modes that balance speed and sensitivity by adjusting filtering parameters:

| Mode | Speed | Sensitivity | Omega | OmegaFwd | MKFL | Use Case |
|------|-------|-------------|-------|----------|------|----------|
| **Fast** | Highest | Lowest | 22 | 50 | 500 | Large-scale screening |
| **Sensitive** | Medium | Medium | 12 | 20 | 600 | Balanced searches |
| **VerySensitive** | Lowest | Highest | 0 | 0 | 99999 | Exhaustive searches |

```mermaid
graph TB
    subgraph "Algorithm Mode Selection"
        DecideMode["DECIDE_MODE<br/>Configuration Strategy"]
        CommandCheck["GetAlgoModeFromCommandLine()<br/>Check -fast, -sensitive, -verysensitive"]
        ModeSet["SetDSSParams()<br/>Apply mode-specific parameters"]
    end
    
    subgraph "Decision Modes"
        AlwaysFast["DM_AlwaysFast<br/>Force fast mode"]
        AlwaysSens["DM_AlwaysSensitive<br/>Force sensitive mode"]
        AlwaysVery["DM_AlwaysVerysensitive<br/>Force very sensitive mode"]
        UseCmdLine["DM_UseCommandLineOption<br/>Require explicit flag"]
        DefaultFast["DM_DefaultFast<br/>Default to fast if no flag"]
        DefaultSens["DM_DefaultSensitive<br/>Default to sensitive if no flag"]
    end
    
    subgraph "Parameter Values"
        FastParams["Fast Mode<br/>Omega=22, MKFL=500<br/>MinHSPScore=50"]
        SensParams["Sensitive Mode<br/>Omega=12, MKFL=600<br/>MinHSPScore=50"]
        VeryParams["VerySensitive Mode<br/>Omega=0, MKFL=99999<br/>MinHSPScore=0"]
    end
    
    DecideMode --> AlwaysFast
    DecideMode --> AlwaysSens
    DecideMode --> AlwaysVery
    DecideMode --> UseCmdLine
    DecideMode --> DefaultFast
    DecideMode --> DefaultSens
    
    AlwaysFast --> FastParams
    AlwaysSens --> SensParams
    AlwaysVery --> VeryParams
    UseCmdLine --> CommandCheck
    DefaultFast --> CommandCheck
    DefaultSens --> CommandCheck
    
    CommandCheck --> ModeSet
    ModeSet --> FastParams
    ModeSet --> SensParams
    ModeSet --> VeryParams
```

Sources: [src/dssparams.cpp:16-84](), [src/dssparams.h:8-25]()

## Parameter Configuration Methods

The `DSSParams` class provides multiple methods for configuring parameters:

### Command-Line Parameter Override

After setting the algorithm mode, individual parameters can be overridden using command-line options:

```mermaid
graph LR
    subgraph "Parameter Override Flow"
        BaseMode["Algorithm Mode<br/>Base Parameters"]
        CmdLineCheck["Command Line Options<br/>optset_* flags"]
        Override["Parameter Override<br/>Direct assignment"]
        Validation["Parameter Validation<br/>Gap penalty checks"]
    end
    
    subgraph "Common Overrides"
        Omega["--omega<br/>Pre-filter threshold"]
        GapOpen["--gapopen<br/>Gap opening penalty"]
        GapExt["--gapext<br/>Gap extension penalty"]
        MinFwd["--minfwdscore<br/>Minimum forward score"]
        MKFL["--mkfl<br/>Max k-mer filter length"]
    end
    
    BaseMode --> CmdLineCheck
    CmdLineCheck --> Override
    Override --> Validation
    
    Omega --> Override
    GapOpen --> Override
    GapExt --> Override
    MinFwd --> Override
    MKFL --> Override
```

Sources: [src/dssparams.cpp:92-110]()

### TSV File Loading

Parameters can be loaded from tab-separated value files containing parameter name-value pairs:

```mermaid
graph TB
    subgraph "TSV Parameter Loading"
        TSVFile["Parameter TSV File<br/>Name\\tValue format"]
        Reader["FromTsv()<br/>File parsing"]
        Parser["Line Processing<br/>Split on tabs"]
        Setter["SetParam()<br/>Apply values"]
    end
    
    subgraph "Parameter Types"
        FloatParams["Float Parameters<br/>Weights, penalties"]
        IntParams["Integer Parameters<br/>Thresholds, counts"]
        FeatureWeights["Feature Weights<br/>AppendIfWeight=true"]
    end
    
    TSVFile --> Reader
    Reader --> Parser
    Parser --> Setter
    
    Setter --> FloatParams
    Setter --> IntParams
    Setter --> FeatureWeights
```

Sources: [src/dssparams.cpp:112-127]()

## Feature Weights and Scoring

The system uses weighted combinations of structural features for alignment scoring:

### Default Feature Set

The default configuration includes 8 features with optimized weights:

| Feature | Weight | Description |
|---------|--------|-------------|
| `FEATURE_AA` | 0.398145 | Amino acid sequence similarity |
| `FEATURE_NENDist` | 0.129367 | N-terminus to C-terminus distance |
| `FEATURE_Conf` | 0.202354 | Conformational similarity |
| `FEATURE_NENConf` | 0.149383 | N-terminus to C-terminus conformational similarity |
| `FEATURE_RENDist` | 0.0937677 | Relative distance features |
| `FEATURE_DstNxtHlx` | 0.00475462 | Distance to next helix |
| `FEATURE_StrandDens` | 0.0183853 | Beta strand density |
| `FEATURE_NormDens` | 0.00384384 | Normalized density |

### Scoring Matrix Generation

```mermaid
graph TB
    subgraph "Scoring Matrix System"
        Features["Feature Vector<br/>m_Features"]
        Weights["Weight Vector<br/>m_Weights"]
        BaseMatrix["Base Scoring Matrices<br/>g_ScoreMxs2"]
        WeightedMatrix["Weighted Scoring Matrices<br/>m_ScoreMxs"]
    end
    
    subgraph "Matrix Operations"
        InitMx["InitScoreMxs()<br/>Allocate matrices"]
        ApplyWeights["ApplyWeights()<br/>Apply feature weights"]
        Normalize["NormalizeWeights()<br/>Normalize to sum=1"]
    end
    
    Features --> InitMx
    Weights --> InitMx
    BaseMatrix --> ApplyWeights
    Weights --> ApplyWeights
    ApplyWeights --> WeightedMatrix
    
    Weights --> Normalize
    InitMx --> ApplyWeights
```

Sources: [src/namedparams.cpp:32-53](), [src/dssparams.cpp:271-296](), [src/dssparams.cpp:343-363]()

## MuFilter Parameters

The system uses a specialized mu-filtering system with three features for fast pre-screening:

### Mu Features Configuration

```mermaid
graph TB
    subgraph "MuFilter Feature System"
        MuFeatures["m_MuFeatures[3]<br/>Static feature array"]
        SS3["FEATURE_SS3<br/>Secondary structure (3-state)"]
        NENSS3["FEATURE_NENSS3<br/>N-terminus secondary structure"]
        RENDist4["FEATURE_RENDist4<br/>Relative distance (4-state)"]
    end
    
    subgraph "Alphabet Sizes"
        AlphaSizes["m_MuAlphaSizes[3]<br/>{3, 3, 4}"]
        TotalAlpha["m_MuAlphaSize<br/>36 total combinations"]
    end
    
    subgraph "Parameters"
        GapOpen["m_ParaMuGapOpen<br/>Default: 2"]
        GapExt["m_ParaMuGapExt<br/>Default: 1"]
        Pattern["m_MuPrefPatternStr<br/>Default: '1110011'"]
    end
    
    MuFeatures --> SS3
    MuFeatures --> NENSS3
    MuFeatures --> RENDist4
    
    SS3 --> AlphaSizes
    NENSS3 --> AlphaSizes
    RENDist4 --> AlphaSizes
    AlphaSizes --> TotalAlpha
    
    GapOpen --> Pattern
    GapExt --> Pattern
```

Sources: [src/dssparams.cpp:7-14](), [src/dssparams.h:69-72]()

## Parameter Persistence

The system provides methods for saving and loading parameter configurations:

### Parameter Export/Import

```mermaid
graph LR
    subgraph "Parameter I/O"
        Export["ToFev()<br/>Export to file"]
        Import["FromTsv()<br/>Import from TSV"]
        ParamStr["FromParamStr()<br/>Parse parameter string"]
    end
    
    subgraph "Formats"
        FEV["FEV Format<br/>Feature-weight pairs"]
        TSV["TSV Format<br/>Name-value pairs"]
        String["String Format<br/>Colon-separated"]
    end
    
    subgraph "Access Methods"
        GetParam["GetParam()<br/>Get float parameter"]
        GetIntParam["GetIntParam()<br/>Get integer parameter"]
        SetParam["SetParam()<br/>Set parameter value"]
    end
    
    Export --> FEV
    Import --> TSV
    ParamStr --> String
    
    GetParam --> SetParam
    GetIntParam --> SetParam
```

Sources: [src/dssparams.cpp:129-145](), [src/dssparams.cpp:154-215](), [src/namedparams.cpp:4-30]()

## Parameter Validation

The system includes validation for critical parameters:

### Gap Penalty Validation

Gap penalties must be non-positive values (represented as negative numbers internally):

```mermaid
graph TB
    subgraph "Parameter Validation"
        Input["Command Line Input<br/>Positive values"]
        Convert["Internal Conversion<br/>Multiply by -1"]
        Validate["Validation Check<br/>Must be <= 0"]
        Error["Die() on Invalid<br/>Error message"]
    end
    
    Input --> Convert
    Convert --> Validate
    Validate --> Error
```

The validation ensures that gap opening and extension penalties are properly specified as non-negative values on the command line but stored as negative values internally for the alignment algorithm.

Sources: [src/dssparams.cpp:105-108]()

---