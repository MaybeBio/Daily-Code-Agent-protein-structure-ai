# Commands and Options

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [src/cmds.h](src/cmds.h)
- [src/myopts.h](src/myopts.h)
- [src/reseek.vcxproj](src/reseek.vcxproj)
- [src/reseek.vcxproj.filters](src/reseek.vcxproj.filters)

</details>



This document provides a comprehensive reference for reseek's command-line interface, covering all 69 available commands and 217+ configuration parameters. The command-line interface serves as the primary entry point for all reseek functionality, from basic protein structure searches to advanced benchmarking and calibration tasks.

For information about customizing output formats and columns, see [Output Formatting](#6.2). For details about the core alignment algorithms that these commands control, see [Core Alignment Engine](#3).

## Command-Line Interface Architecture

The reseek command-line interface follows a structured approach where commands define the operation to perform, and options configure the behavior of those operations. The interface is implemented through a macro-based system that ensures type safety and comprehensive parameter handling.

```mermaid
graph TD
    CLI["reseek_main.cpp<br/>Entry Point"]
    CMDS["cmds.h<br/>69 Commands"]
    OPTS["myopts.h<br/>217+ Options"]
    USAGE["usage.h<br/>Help System"]
    
    CLI --> CMDS
    CLI --> OPTS
    CLI --> USAGE
    
    CMDS --> SEARCH["search<br/>Database Search"]
    CMDS --> CONVERT["convert<br/>Format Conversion"]
    CMDS --> BENCH["scop40bench<br/>Benchmarking"]
    CMDS --> CALIB["calibrate<br/>Statistical Calibration"]
    
    OPTS --> STR_OPTS["STR_OPT<br/>String Parameters"]
    OPTS --> UNS_OPTS["UNS_OPT<br/>Unsigned Integer Parameters"]
    OPTS --> FLT_OPTS["FLT_OPT<br/>Float Parameters"]
    OPTS --> FLAG_OPTS["FLAG_OPT<br/>Boolean Flags"]
    
    STR_OPTS --> DB_OPTS["--db, --input, --output<br/>File Paths"]
    UNS_OPTS --> PERF_OPTS["--threads, --maxseqlength<br/>Performance Settings"]
    FLT_OPTS --> SCORE_OPTS["--evalue, --minscore<br/>Scoring Thresholds"]
    FLAG_OPTS --> MODE_OPTS["--sensitive, --fast<br/>Algorithm Modes"]
```

**Sources:** [src/myopts.h:1-150](), [src/cmds.h:1-79](), [src/reseek_main.cpp]()

## Command Categories

The 69 available commands are organized into functional categories, each serving specific aspects of protein structure analysis and system maintenance.

### Core Search and Analysis Commands

```mermaid
graph LR
    subgraph "Primary Operations"
        SEARCH["search<br/>Database Search"]
        CONVERT["convert<br/>Format Conversion"]
        ALIGNPAIR["alignpair<br/>Pairwise Alignment"]
    end
    
    subgraph "Filtering Pipeline"
        MUKMER["mukmerfilter<br/>K-mer Pre-filtering"]
        POSTMU["postmufilter<br/>Post-filtering"]
        PREFILTER["prefilter_mu<br/>MU Pre-filtering"]
    end
    
    subgraph "Benchmarking"
        SCOP40["scop40bench<br/>SCOP40 Benchmark"]
        SCOP40BIT["scop40bit<br/>Bit Score Analysis"]
        SCOP40ROC["scop40bit_roc<br/>ROC Analysis"]
    end
    
    subgraph "Calibration"
        CALIBRATE["calibrate<br/>Statistical Calibration"]
        CALIBRATE2["calibrate2<br/>Advanced Calibration"]
        CALIBRATE5["calibrate5<br/>Model Calibration"]
    end
```

**Sources:** [src/cmds.h:25-76]()

### Specialized Analysis Commands

| Command | Purpose | Key Options |
|---------|---------|-------------|
| `daliscore_msa` | DALI scoring for MSAs | `--input`, `--output`, `--columns` |
| `lddt_msa` | LDDT scoring for MSAs | `--input`, `--output`, `--feature` |
| `msta_scores` | Multiple structure alignment scoring | `--input`, `--features`, `--output` |
| `distmx` | Distance matrix calculation | `--input`, `--output`, `--minchainlength` |
| `cluster` | Structure clustering | `--input`, `--output`, `--minscore` |

**Sources:** [src/cmds.h:38-53]()

## Option Type System

The option system uses a macro-based approach to define four distinct parameter types, each with specific validation and handling characteristics.

```mermaid
graph TB
    subgraph "String Options (STR_OPT)"
        STR_DB["--db<br/>Database Path"]
        STR_INPUT["--input<br/>Input File"]
        STR_OUTPUT["--output<br/>Output File"]
        STR_FASTA["--fasta<br/>FASTA File"]
        STR_FEATURES["--features<br/>Feature List"]
    end
    
    subgraph "Unsigned Integer Options (UNS_OPT)"
        UNS_THREADS["--threads<br/>Thread Count"]
        UNS_MAXLEN["--maxseqlength<br/>Max Sequence Length"]
        UNS_WINDOW["--window<br/>Window Size"]
        UNS_DBSIZE["--dbsize<br/>Database Size"]
    end
    
    subgraph "Float Options (FLT_OPT)"
        FLT_EVALUE["--evalue<br/>E-value Threshold"]
        FLT_MINSCORE["--minscore<br/>Minimum Score"]
        FLT_GAPOPEN["--gapopen<br/>Gap Open Penalty"]
        FLT_GAPEXT["--gapext<br/>Gap Extension Penalty"]
    end
    
    subgraph "Boolean Flags (FLAG_OPT)"
        FLAG_SENSITIVE["--sensitive<br/>Sensitive Mode"]
        FLAG_FAST["--fast<br/>Fast Mode"]
        FLAG_VERBOSE["--verbose<br/>Verbose Output"]
        FLAG_QUIET["--quiet<br/>Quiet Mode"]
    end
```

**Sources:** [src/myopts.h:8-144]()

## Core Configuration Options

### Algorithm Mode Selection

The algorithm behavior is controlled through mutually exclusive mode flags that configure the entire processing pipeline:

| Flag | Purpose | Impact |
|------|---------|---------|
| `--fast` | High-speed mode | Reduced sensitivity, faster execution |
| `--sensitive` | Balanced mode | Default sensitivity/speed tradeoff |
| `--verysensitive` | High-accuracy mode | Maximum sensitivity, slower execution |

**Sources:** [src/myopts.h:124-125](), [src/myopts.h:140]()

### Input/Output Configuration

```mermaid
graph LR
    subgraph "Input Sources"
        INPUT["--input<br/>Primary Input"]
        INPUT2["--input2<br/>Secondary Input"]
        DB["--db<br/>Database"]
        FASTA["--fasta<br/>FASTA Sequences"]
    end
    
    subgraph "Output Destinations"
        OUTPUT["--output<br/>Primary Output"]
        OUTPUT2["--output2<br/>Secondary Output"]
        OUTPUT3["--output3<br/>Tertiary Output"]
        LOG["--log<br/>Log File"]
    end
    
    subgraph "Format Specifications"
        CAL["--cal<br/>CAL Format"]
        BCA["--bca<br/>BCA Format"]
        COLUMNS["--columns<br/>Output Columns"]
        FEATURES["--features<br/>Feature List"]
    end
    
    INPUT --> OUTPUT
    INPUT2 --> OUTPUT2
    DB --> OUTPUT
    FASTA --> OUTPUT
```

**Sources:** [src/myopts.h:50-54](), [src/myopts.h:26-28](), [src/myopts.h:44-45]()

### Performance and Threading Options

| Option | Type | Purpose | Default Range |
|--------|------|---------|---------------|
| `--threads` | UNS_OPT | CPU thread count | System-dependent |
| `--maxseqlength` | UNS_OPT | Maximum sequence length | Memory-dependent |
| `--window` | UNS_OPT | Sliding window size | Algorithm-dependent |
| `--randseed` | UNS_OPT | Random seed for reproducibility | Time-based |

**Sources:** [src/myopts.h:66](), [src/myopts.h:80](), [src/myopts.h:72](), [src/myopts.h:82]()

### Scoring and Threshold Parameters

The scoring system provides fine-grained control over alignment sensitivity and statistical significance:

```mermaid
graph TD
    subgraph "Score Thresholds"
        MINSCORE["--minscore<br/>Minimum Alignment Score"]
        MAXSCORE["--maxscore<br/>Maximum Alignment Score"]
        MINFWD["--minfwdscore<br/>Minimum Forward Score"]
    end
    
    subgraph "Statistical Significance"
        EVALUE["--evalue<br/>E-value Threshold"]
        PVALUE["--pvalue<br/>P-value Threshold"]
        EVALUE_A["--evalue_a<br/>E-value Parameter A"]
        EVALUE_B["--evalue_b<br/>E-value Parameter B"]
    end
    
    subgraph "Gap Penalties"
        GAPOPEN["--gapopen<br/>Gap Open Penalty"]
        GAPEXT["--gapext<br/>Gap Extension Penalty"]
        MAXGAP["--maxgappct<br/>Maximum Gap Percentage"]
    end
    
    MINSCORE --> EVALUE
    EVALUE --> GAPOPEN
    EVALUE_A --> EVALUE_B
```

**Sources:** [src/myopts.h:99-115]()

## Specialized Configuration Categories

### Benchmarking and Calibration Options

| Option | Type | Purpose |
|--------|------|---------|
| `--benchlevel` | STR_OPT | Benchmark detail level |
| `--roc` | STR_OPT | ROC analysis output |
| `--calib_output` | STR_OPT | Calibration results |
| `--slopes` | STR_OPT | Score slope parameters |
| `--alpha` | STR_OPT | Alpha parameter for statistics |

**Sources:** [src/myopts.h:14](), [src/myopts.h:11](), [src/myopts.h:18](), [src/myopts.h:23](), [src/myopts.h:25]()

### Advanced Filtering Parameters

| Option | Type | Purpose |
|--------|------|---------|
| `--mkfl` | UNS_OPT | MU k-mer filter length |
| `--mun` | UNS_OPT | MU sequence number |
| `--muhsp` | UNS_OPT | MU HSP count |
| `--xdrop1` | UNS_OPT | X-drop threshold 1 |
| `--xdrop2` | UNS_OPT | X-drop threshold 2 |

**Sources:** [src/myopts.h:76-78](), [src/myopts.h:74-75]()

### Memory and Resource Management

```mermaid
graph LR
    subgraph "Memory Control"
        MAXSEQ["--maxseqlength<br/>Sequence Length Limit"]
        BUFF["--sfasta_buff_bytes<br/>Buffer Size"]
        RSB["--rsb_size<br/>Ranked Scores Buffer"]
    end
    
    subgraph "Allocation Debugging"
        ALLOC_TRACE["--myalloc_trace<br/>Memory Tracing"]
        ALLOC_DUMP["--myalloc_dump_secs<br/>Dump Interval"]
        ALLOC_SUMMARY["--myalloc_summary_secs<br/>Summary Interval"]
    end
    
    subgraph "Performance Monitoring"
        TIMER_PCT["--min_timer_pct<br/>Timer Threshold"]
        VERBOSE["--verbose<br/>Verbose Output"]
        QUIET["--quiet<br/>Quiet Mode"]
    end
```

**Sources:** [src/myopts.h:80-96](), [src/myopts.h:143-144](), [src/myopts.h:119-120]()

## Common Usage Patterns

### Basic Database Search
```bash
reseek search --db database.bca --input query.fasta --output results.tsv
```

### Sensitive Search with Custom Scoring
```bash
reseek search --db database.bca --input query.fasta --output results.tsv --sensitive --evalue 1e-5 --minscore 50
```

### Format Conversion
```bash
reseek convert --input structures.pdb --output structures.cal --format cal
```

### Benchmarking with ROC Analysis
```bash
reseek scop40bench --db scop40.bca --roc results.roc --benchlevel detailed
```

**Sources:** [src/cmds.h:25](), [src/cmds.h:37](), [src/cmds.h:10]()

---