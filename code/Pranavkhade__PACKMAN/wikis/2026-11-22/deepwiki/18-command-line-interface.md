# Command-Line Interface

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.github/workflows/python-package.yml](.github/workflows/python-package.yml)
- [README.md](README.md)
- [additional codes/ScanAlpha.py](additional codes/ScanAlpha.py)
- [docs/source/index.rst](docs/source/index.rst)
- [docs/source/tutorials/dci_cli.rst](docs/source/tutorials/dci_cli.rst)
- [docs/source/tutorials/entropy_api.rst](docs/source/tutorials/entropy_api.rst)
- [docs/source/tutorials/entropy_cli.rst](docs/source/tutorials/entropy_cli.rst)
- [docs/source/tutorials/gui.rst](docs/source/tutorials/gui.rst)
- [docs/source/tutorials/hdANM.rst](docs/source/tutorials/hdANM.rst)
- [docs/source/tutorials/hdANM_cli.rst](docs/source/tutorials/hdANM_cli.rst)
- [docs/source/tutorials/hinge_predict_cli.rst](docs/source/tutorials/hinge_predict_cli.rst)
- [docs/source/tutorials/installation.rst](docs/source/tutorials/installation.rst)
- [docs/source/tutorials/main.rst](docs/source/tutorials/main.rst)
- [packman/apps/__init__.py](packman/apps/__init__.py)
- [packman/apps/predict_hinge.py](packman/apps/predict_hinge.py)
- [packman/bin/PACKMAN.py](packman/bin/PACKMAN.py)
- [packman/molecule/__init__.py](packman/molecule/__init__.py)

</details>



This page documents the PACKMAN command-line interface (CLI): its entry point, all subcommands, their arguments, defaults, and example invocations. The CLI exposes the same four analysis applications as the Python API and GUI. For the Python API usage of each application, see [Analysis Applications](#4). For the GUI, see [Graphical User Interface](#8).

---

## Entry Point

The CLI is launched via Python's `-m` flag:

```
python -m packman <subcommand> [arguments]
```

The dispatcher `main()` in [packman/bin/PACKMAN.py:141-148]() checks `sys.argv[1]`. If it equals `"gui"`, it calls `load_gui()`. Otherwise, it calls `load_cli()`, which invokes `IO()` to parse arguments and then dispatches to the appropriate `_cli` function.

**Launch GUI instead:**
```
python -m packman gui
```

---

## CLI Dispatch Architecture

**Diagram: CLI call flow from entry point to application**

```mermaid
flowchart TD
    user["\"python -m packman <subcommand>\""]
    main["\"main() in PACKMAN.py\""]
    gui["\"load_gui()\""]
    cli["\"load_cli()\""]
    io["\"IO() — argparse subparsers\""]
    load["\"molecule.load_structure()\""]
    hinge_cli["\"hinge_cli(args, mol)\""]
    hdanm_cli["\"hdanm_cli(args, mol)\""]
    entropy_cli["\"entropy_cli(args, mol)\""]
    dci_cli["\"dci_cli(args, mol)\""]

    user --> main
    main -- "sys.argv[1] == 'gui'" --> gui
    main -- "otherwise" --> cli
    cli --> io
    io --> load
    load --> hinge_cli
    load --> hdanm_cli
    load --> entropy_cli
    load --> dci_cli
```

Sources: [packman/bin/PACKMAN.py:95-131](), [packman/bin/PACKMAN.py:141-148]()

---

**Diagram: Subcommand to implementation mapping**

```mermaid
flowchart LR
    subgraph "packman/bin/PACKMAN.py"
        IO["\"IO() — defines subparsers\""]
    end
    subgraph "packman/apps/"
        hinge_cli["\"hinge_cli() in predict_hinge.py\""]
        hdanm_cli["\"hdanm_cli() in hdanm.py\""]
        entropy_cli["\"entropy_cli() in calculate_entropy.py\""]
        dci_cli["\"dci_cli() in dci.py\""]
    end

    IO -- "command == 'hinge'" --> hinge_cli
    IO -- "command == 'hdanm'" --> hdanm_cli
    IO -- "command == 'entropy'" --> entropy_cli
    IO -- "command == 'dci'" --> dci_cli
```

Sources: [packman/bin/PACKMAN.py:27-87](), [packman/apps/__init__.py:16-19]()

---

## Global Options

These options apply at the top-level parser and are primarily used by the hosted web servers:

| Option | Type | Default | Description |
|---|---|---|---|
| `--outputfile` | writable file | `sys.stdout` | Path to write analysis output |
| `--logfile` | writable file | `sys.stderr` | Path to write log messages |

Sources: [packman/bin/PACKMAN.py:82-84]()

---

## Subcommand: `hinge`

Runs hinge prediction using the alpha-shape algorithm. Implemented by `hinge_cli()` in [packman/apps/predict_hinge.py:326-366]().

**Synopsis:**
```
python -m packman hinge [--pdbid PDB_ID] [--e_clusters N] [--minhnglen N]
                        [--chain CHAIN] [--generateobj FILE]
                        AlphaValue FILENAME
```

### Arguments

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `AlphaValue` | float (positional) | Yes | — | Alpha parameter for the alpha-shape. Recommended: `2.8` (closed), `4.5` (open). |
| `FILENAME` | string (positional) | Yes | — | Path to the input PDB/CIF file. |
| `-pdbid` / `--pdbid` | string | No | `None` | PDB ID to download; file is saved to `FILENAME`. |
| `--e_clusters` | int | No | `4` | Number of eccentricity clusters for K-means. |
| `--minhnglen` | int | No | `5` | Minimum residue length for a predicted hinge to be reported. |
| `--chain` | string | No | `None` | Single chain ID to analyze; all chains analyzed if omitted. |
| `--generateobj` | writable binary file | No | `None` | Path to save an `.obj` file of the alpha shape. Only used when `--chain` is also provided. |

### Behavior

- If `--chain` is given, only that chain's backbone atoms are used.
- If `--chain` is omitted, all chains in `mol[0]` are iterated.
- The `--generateobj` flag is silently ignored without `--chain`.
- Output (hinge residues, statistics, p-values, PyMOL commands) is written to `--outputfile` (default: stdout).

### Examples

```bash
# Download 1prw and predict hinges on all chains, alpha=2.8
python -m packman hinge --pdbid 1prw 2.8 1prw.pdb

# Use a local file, single chain
python -m packman hinge 2.8 1prw.pdb --chain A

# Export alpha-shape mesh
python -m packman hinge 2.8 1prw.pdb --chain A --generateobj shape.obj
```

Sources: [packman/bin/PACKMAN.py:40-48](), [packman/apps/predict_hinge.py:326-366](), [docs/source/tutorials/hinge_predict_cli.rst:47-79]()

---

## Subcommand: `hdanm`

Runs the Hinge-Domain ANM (hdANM) to generate mode-based motion movies. Implemented by `hdanm_cli()` imported from `packman/apps/hdanm.py`.

**Synopsis:**
```
python -m packman hdanm [--pdbid PDB_ID] [--chain CHAIN] [--dr DR]
                        [--power POWER] [--mass MASS] [--scale N]
                        [--frames N] [--modes N] [--ca_to_aa] [--make_tar]
                        FILENAME HNG
```

### Arguments

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `FILENAME` | string (positional) | Yes | — | Path to the input PDB/CIF file. |
| `HNG` | string (positional) | Yes | — | Path to the `.hng` hinge definition file. |
| `-pdbid` / `--pdbid` | string | No | `None` | PDB ID to download; file saved to `FILENAME`. |
| `--chain` | string | No | `None` | Chain ID to analyze. |
| `--dr` | float | No | `15` | Distance cutoff (Å) for the ANM contact map. |
| `--power` | float | No | `0` | Exponent for distance weighting in the non-parametric ANM. |
| `--mass` | string | No | `'residue'` | Mass assignment: `unit`, `residue`, or `atom`. |
| `--scale` | int | No | `2` | Amplitude scale for generated movie frames. |
| `--frames` | int | No | `10` | Number of frames per mode movie. |
| `--modes` | int | No | `10` | Number of modes to compute and output. |
| `--ca_to_aa` | bool flag | No | `False` | Project Cα motions onto all atoms in the structure. |
| `--make_tar` | flag | No | off | Bundle all output files into a `.tar.gz` archive. |

### HNG File Format

The `.hng` file is tab-separated and defines which residue ranges are rigid domains (`D`) and which are hinges (`H`):

```
1exr.pdb_A	D1	1:70
1exr.pdb_A	H1	71:90
1exr.pdb_A	D2	91:148
```

Columns: `Filename_ChainID`, `Domain/HingeID`, `StartResidue:EndResidue`. The `.hng` file can be produced by the `hinge` subcommand or by the `ScanAlpha.py` batch utility.

### Examples

```bash
# Basic hdANM with local files
python -m packman hdanm 1exr.pdb 1exr.hng --chain A

# Download structure, custom cutoff, 20 frames
python -m packman hdanm --pdbid 1exr 1exr.pdb 1exr.hng --dr 12 --frames 20

# Package outputs
python -m packman hdanm 1exr.pdb 1exr.hng --make_tar
```

Sources: [packman/bin/PACKMAN.py:50-62](), [docs/source/tutorials/hdANM_cli.rst:24-46](), [docs/source/tutorials/hdANM.rst:48-54]()

---

## Subcommand: `entropy`

Computes per-residue packing entropy using Voronoi tessellation. Implemented by `entropy_cli()` imported from `packman/apps/calculate_entropy.py`.

**Synopsis:**
```
python -m packman entropy [--type entropy_type] [--pdbid PDB_ID]
                          [--chains CHAINS] [--probe_size FLOAT]
                          [--onspherepoints INT]
                          FILENAME
```

### Arguments

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `FILENAME` | string (positional) | Yes | — | Path to the input PDB/CIF file. |
| `-type` / `--type` | string | No | `None` | Entropy variant. Currently supported: `PackingEntropy`. |
| `-pdbid` / `--pdbid` | string | No | `None` | PDB ID to download; file saved to `FILENAME`. |
| `--chains` | string | No | `None` | Comma-separated chain IDs (e.g., `A,B`). `None` includes all chains. |
| `--probe_size` | float | No | `1.4` | Solvent probe radius in Å (water ≈ 1.4 Å). |
| `--onspherepoints` | int | No | `30` | Number of surface probe points per atom. |

### Chain Selection Note

`--chains` controls which chains are *included in the entropy calculation*, not just which chains appear in the output. To include chain C in the geometry but exclude it from reported entropy, omit `--chains` and filter the output by chain column.

### Examples

```bash
# Entropy for all chains
python -m packman entropy 1prw.pdb --type PackingEntropy

# Entropy restricted to chains A and B
python -m packman entropy 1prw.pdb --type PackingEntropy --chains A,B

# Download and run
python -m packman entropy --pdbid 1prw 1prw.pdb --type PackingEntropy
```

Sources: [packman/bin/PACKMAN.py:65-71](), [docs/source/tutorials/entropy_cli.rst:22-57]()

---

## Subcommand: `dci`

Runs Dynamic Community Identification (DCI) using GNM-based cross-correlations and hierarchical clustering. Implemented by `dci_cli()` imported from `packman/apps/dci.py`.

**Synopsis:**
```
python -m packman dci [--pdbid PDB_ID] [--chain CHAIN]
                      [--cutoff FLOAT] [--n_com INT]
                      FILENAME
```

### Arguments

| Argument | Type | Required | Default | Description |
|---|---|---|---|---|
| `FILENAME` | string (positional) | Yes | — | Path to the input PDB/CIF file. |
| `-pdbid` / `--pdbid` | string | No | `None` | PDB ID to download; file saved to `FILENAME`. |
| `-chain` / `--chain` | string | No | `None` | Chain ID. `None` analyzes all chains. |
| `-cutoff` / `--cutoff` | float | No | `7.0` | Distance cutoff (Å) for GNM contact map construction. |
| `-n_com` / `--n_com` | int | No | `None` | Number of communities. `None` uses the Calinski-Harabasz optimal score. |

### Examples

```bash
# DCI on chain A with default cutoff
python -m packman dci 1prw.pdb --chain A

# DCI on all chains, fixed number of communities
python -m packman dci 1prw.pdb --n_com 5

# Download and run
python -m packman dci --pdbid 1prw 1prw.pdb --chain A
```

Sources: [packman/bin/PACKMAN.py:74-79](), [docs/source/tutorials/dci_cli.rst:22-47]()

---

## Subcommand Summary

| Subcommand | Positional Args | Key Optional Args | Implementation |
|---|---|---|---|
| `hinge` | `AlphaValue`, `FILENAME` | `--chain`, `--e_clusters`, `--minhnglen`, `--generateobj` | `hinge_cli()` in `predict_hinge.py` |
| `hdanm` | `FILENAME`, `HNG` | `--chain`, `--dr`, `--mass`, `--modes`, `--frames`, `--make_tar` | `hdanm_cli()` in `hdanm.py` |
| `entropy` | `FILENAME` | `--type`, `--chains`, `--probe_size`, `--onspherepoints` | `entropy_cli()` in `calculate_entropy.py` |
| `dci` | `FILENAME` | `--chain`, `--cutoff`, `--n_com` | `dci_cli()` in `dci.py` |

All four subcommands share the `-pdbid`/`--pdbid` option for on-demand structure download.

Sources: [packman/bin/PACKMAN.py:27-87](), [packman/apps/__init__.py:16-19]()

---

## Structure Loading

`load_cli()` in [packman/bin/PACKMAN.py:95-131]() loads the molecular structure before dispatching to any subcommand:

1. If `--pdbid` is given, `molecule.download_structure()` is called first, saving to `FILENAME`.
2. The file extension is extracted from `FILENAME` and passed as `ftype` to `molecule.load_structure()`.
3. If the extension cannot be determined, `load_structure()` is called without `ftype` and PACKMAN attempts auto-detection.

See [Loading and Downloading Structures](#3.1) for details on `load_structure()` and `download_structure()`.

Sources: [packman/bin/PACKMAN.py:112-120]()

---

## ScanAlpha Batch Utility

For scanning a range of alpha values to find consensus hinges, a standalone script is provided at [additional codes/ScanAlpha.py](). It is not part of the installed CLI but can be copied to the working directory and run directly.

```bash
python3 ScanAlpha.py myprotein.pdb --chain A --begin 0 --end 10 --step_size 0.5
```

| Argument | Default | Description |
|---|---|---|
| `filename` | required | Input PDB/CIF file |
| `--chain` | `None` | Chain ID (all chains if omitted) |
| `--begin` | `0` | Starting alpha value |
| `--end` | `10` | Ending alpha value |
| `--step_size` | `0.5` | Increment between alpha values |
| `--outfilename` | `output.hng` | Name for the output `.hng` file |

The script iterates `predict_hinge()` over all alpha values, collects overlapping significant hinges (p-value ≤ 0.05), and writes a merged `.hng` file suitable for use with the `hdanm` subcommand.

Sources: [additional codes/ScanAlpha.py:1-144]()

---