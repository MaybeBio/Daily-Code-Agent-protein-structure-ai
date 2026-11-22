# Command Line Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/release_and_docs.yaml](.github/workflows/release_and_docs.yaml)
- [.releaserc.js](.releaserc.js)
- [README.md](README.md)
- [docs/_static/atomworks_datapipelines.svg](docs/_static/atomworks_datapipelines.svg)
- [docs/_static/atomworks_logo_color.svg](docs/_static/atomworks_logo_color.svg)
- [docs/_static/atomworks_logo_dark.svg](docs/_static/atomworks_logo_dark.svg)
- [docs/_static/atomworks_logo_light.svg](docs/_static/atomworks_logo_light.svg)
- [docs/_static/atomworks_overview.png](docs/_static/atomworks_overview.png)
- [docs/_static/default_thumbnail.png](docs/_static/default_thumbnail.png)
- [docs/_static/favicon-16x16.png](docs/_static/favicon-16x16.png)
- [docs/_static/favicon-32x32.png](docs/_static/favicon-32x32.png)
- [docs/conf.py](docs/conf.py)
- [docs/index.rst](docs/index.rst)

</details>



The AtomWorks CLI provides data management utilities for synchronizing biological databases and setting up development environments. The CLI enables users to maintain local mirrors of the RCSB PDB and PDBeChem CCD archives, as well as automate test environment preparation.

This page covers the overall CLI architecture and command structure. For detailed information about database synchronization, see [Data Synchronization](#4.1). For test environment setup procedures, see [Test Environment Setup](#4.2).

## CLI Architecture

The AtomWorks CLI is built using the `typer` framework and organized into three main command groups: `pdb`, `ccd`, and `setup`. Each group provides specialized functionality for different aspects of data management.

### Command Structure

```mermaid
graph TB
    CLI["atomworks CLI<br/>(__main__.py)"]
    
    subgraph "Command Groups"
        PDB["pdb<br/>(pdb.py)"]
        CCD["ccd<br/>(ccd.py)"]  
        SETUP["setup<br/>(setup.py)"]
    end
    
    subgraph "PDB Commands"
        PDB_SYNC["pdb sync<br/>sync_pdb()"]
    end
    
    subgraph "CCD Commands"  
        CCD_SYNC["ccd sync<br/>sync_ccd()"]
    end
    
    subgraph "Setup Commands"
        SETUP_METADATA["setup metadata<br/>setup_metadata()"]
        SETUP_TESTS["setup tests<br/>setup_tests()"]
    end
    
    CLI --> PDB
    CLI --> CCD
    CLI --> SETUP
    
    PDB --> PDB_SYNC
    CCD --> CCD_SYNC
    SETUP --> SETUP_METADATA
    SETUP --> SETUP_TESTS
```

**CLI Command Hierarchy**

The main CLI application is defined in [src/atomworks/cli/__init__.py:7]() as a `typer.Typer` instance. Sub-applications are registered using `app.add_typer()` calls at [src/atomworks/cli/__init__.py:15-17]().

Sources: [src/atomworks/cli/__init__.py:1-18](), [src/atomworks/cli/__main__.py:1-14]()

### Application Entry Point

The CLI is accessible through multiple entry points:

| Entry Method | Command |
|--------------|---------|
| Module execution | `python -m atomworks.cli` |
| Direct execution | `atomworks <command>` |
| Package entry point | Configured in `pyproject.toml` |

The entry point is implemented in [src/atomworks/cli/__main__.py:8-9]() with a simple `main()` function that calls the root `app()`.

Sources: [src/atomworks/cli/__main__.py:8-14]()

## Data Synchronization Overview

### Remote Data Sources

The CLI connects to external biological databases to maintain local mirrors:

```mermaid
graph LR
    subgraph "Remote Sources"
        PDB_REMOTE["rsync.wwpdb.org:33444<br/>RCSB PDB Archive"]
        CCD_REMOTE["ftp.ebi.ac.uk<br/>PDBeChem CCD"]
        METADATA_REMOTE["Pre-computed Metadata<br/>(PN units & interfaces)"]
        TEST_REMOTE["files.ipd.uw.edu<br/>Test Data Pack"]
    end
    
    subgraph "Synchronization Tools"
        RSYNC["rsync utility<br/>(-rltvz --stats)"]
        HTTP["urllib.request<br/>(with tqdm progress)"]
    end
    
    subgraph "Local Storage"
        PDB_MIRROR["PDB Mirror<br/>(divided mmCIF layout)"]
        CCD_MIRROR["CCD Mirror<br/>(hierarchical CIF structure)"]
        METADATA_DIR["Metadata Directory<br/>(pn_units_df.parquet<br/>interfaces_df.parquet)"]
        TEST_DATA["Test Environment<br/>(tests/data/)"]
    end
    
    PDB_REMOTE --> RSYNC
    CCD_REMOTE --> RSYNC
    METADATA_REMOTE --> HTTP
    TEST_REMOTE --> HTTP
    
    RSYNC --> PDB_MIRROR
    RSYNC --> CCD_MIRROR
    HTTP --> METADATA_DIR
    HTTP --> TEST_DATA
```

**Data Source Configuration**

Remote endpoints are defined as constants in each module:
- PDB: `PDB_REMOTE` and `PDB_PORT` in [src/atomworks/cli/pdb.py:18-19]()
- CCD: `CCD_REMOTE` in [src/atomworks/cli/ccd.py:18]()
- Test pack: `TEST_PACK_URL` in [src/atomworks/cli/setup.py:18]()

Sources: [src/atomworks/cli/pdb.py:18-19](), [src/atomworks/cli/ccd.py:18](), [src/atomworks/cli/setup.py:18]()

### Synchronization Strategies

The CLI supports two synchronization modes for database mirrors:

| Mode | Description | Use Case |
|------|-------------|----------|
| Full sync | Complete mirror of entire database | Initial setup, comprehensive datasets |
| Selective sync | Specific entries only | Development, testing, targeted workflows |

Both PDB and CCD synchronization commands accept entry lists via command-line arguments (`--pdb-id`, `--ccd-code`) or input files (`--pdb-ids-file`, `--ccd-codes-file`).

## Environment Integration

### Environment Variables

The CLI integrates with environment-based configuration for database paths:

```mermaid
graph TB
    subgraph "CLI Commands"
        PDB_SYNC["pdb sync"]
        CCD_SYNC["ccd sync"]
        SETUP_TESTS["setup tests"]
    end
    
    subgraph "Environment Configuration"
        PDB_ENV["PDB_MIRROR_PATH"]
        CCD_ENV["CCD_MIRROR_PATH"]
    end
    
    subgraph "Local Filesystem"
        PDB_DIR["PDB Mirror Directory"]
        CCD_DIR["CCD Mirror Directory"]
        TEST_DIR["tests/data/"]
    end
    
    PDB_SYNC --> PDB_DIR
    CCD_SYNC --> CCD_DIR
    SETUP_TESTS --> TEST_DIR
    
    PDB_ENV -.-> PDB_DIR
    CCD_ENV -.-> CCD_DIR
    
    PDB_SYNC -.-> PDB_ENV
    CCD_SYNC -.-> CCD_ENV
    SETUP_TESTS --> PDB_ENV
```

**Environment Variable Usage**

After successful synchronization, the CLI provides instructions for setting environment variables. For example, the PDB sync command outputs setup instructions at [src/atomworks/cli/pdb.py:225-228]().

Sources: [src/atomworks/cli/pdb.py:225-228](), [src/atomworks/cli/ccd.py:258-262](), [src/atomworks/cli/setup.py:87]()

## Error Handling and Validation

### Connection Testing

Both PDB and CCD synchronization commands perform connectivity tests before attempting data transfer:

```mermaid
graph TD
    SYNC_START["Sync Command Initiated"]
    CONN_TEST["Connection Test<br/>(_run_rsync_list)"]
    CONN_SUCCESS{"Connection<br/>Successful?"}
    SYNC_EXEC["Execute Sync<br/>(rsync commands)"]
    ERROR_EXIT["Display Error & Exit"]
    SUCCESS["Sync Complete<br/>(Write README)"]
    
    SYNC_START --> CONN_TEST
    CONN_TEST --> CONN_SUCCESS
    CONN_SUCCESS -->|Yes| SYNC_EXEC
    CONN_SUCCESS -->|No| ERROR_EXIT
    SYNC_EXEC --> SUCCESS
```

**Connection Test Implementation**

The `_run_rsync_list()` function is implemented in both [src/atomworks/cli/pdb.py:40-52]() and [src/atomworks/cli/ccd.py:53-73]() to validate remote connectivity before attempting synchronization.

Sources: [src/atomworks/cli/pdb.py:40-52](), [src/atomworks/cli/pdb.py:192-199](), [src/atomworks/cli/ccd.py:53-73](), [src/atomworks/cli/ccd.py:229-236]()

### Input Validation

Entry ID validation ensures data integrity:

| Database | Validation Function | Pattern |
|----------|-------------------|---------|
| PDB | `_normalize_pdb_id()` | 4-character alphanumeric |
| CCD | `_normalize_ccd_code()` | 1-3 character uppercase |

Invalid entries are silently skipped during collection in `_collect_pdb_ids()` and `_collect_ccd_codes()` functions.

Sources: [src/atomworks/cli/pdb.py:22-27](), [src/atomworks/cli/ccd.py:21-34](), [src/atomworks/cli/pdb.py:117-139](), [src/atomworks/cli/ccd.py:149-180]()

## Integration with AtomWorks Ecosystem

The CLI serves as the entry point for data acquisition in the broader AtomWorks processing pipeline:

```mermaid
graph LR
    subgraph "CLI Layer"
        CLI_SYNC["CLI Sync Commands"]
    end
    
    subgraph "Data Storage"
        MIRRORS["Local Database Mirrors"]
    end
    
    subgraph "Processing Layer"
        PARSER["atomworks.io.parser"]
        ML_PIPELINE["atomworks.ml pipeline"]
    end
    
    subgraph "Applications"
        TRAINING["ML Training"]
        ANALYSIS["Structure Analysis"]
    end
    
    CLI_SYNC --> MIRRORS
    MIRRORS --> PARSER
    PARSER --> ML_PIPELINE
    ML_PIPELINE --> TRAINING
    PARSER --> ANALYSIS
```

**Data Flow Integration**

The CLI-maintained mirrors provide the raw data consumed by the `atomworks.io.parser` system documented in [Core Parser System](#2.1). Environment variables set by CLI commands configure parser data source locations.

Sources: [src/atomworks/cli/pdb.py:225-228](), [src/atomworks/cli/ccd.py:258-262](), [src/atomworks/cli/setup.py:134]()

---