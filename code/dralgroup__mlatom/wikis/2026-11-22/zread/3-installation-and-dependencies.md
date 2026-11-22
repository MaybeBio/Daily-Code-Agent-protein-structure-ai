

This page provides a complete guide to installing MLatom and understanding its dependency structure. MLatom is a versatile atomistic simulation package that supports multiple execution modes — as a Python library, through input files, or via the command line. Its modular architecture means most features work immediately after a simple pip install, while advanced capabilities (external quantum chemistry programs, GPU-accelerated ML models, Fortran/Julia backends) require additional setup.

![MLatom-banner](https://github.com/user-attachments/assets/9433ac9a-bcc9-4dd4-9128-d834c85603b0)

The current version is **3.22.0**, distributed under a modified MIT license [Sources: [__init__.py](mlatom/__init__.py#L17-L17)].

## Dependency Architecture Overview

MLatom's dependencies are organized in a layered architecture. The core package has minimal requirements, while each optional capability pulls in additional libraries or external programs only when needed. Understanding this structure helps you install exactly what you need — nothing more, nothing less.

```mermaid
graph TD
    subgraph "Core Layer (pip install mlatom)"
        A[mlatom Python package]
        A --> B[numpy]
        A --> C[scipy]
    end

    subgraph "ML Models Layer"
        A --> D[PyTorch<br/>TorchANI, MACE,<br/>AIMNet2, GICnet]
        A --> E[TensorFlow<br/>PhysNet, DeePMD-kit]
        A --> F[Julia + PyJulia<br/>KRR (mlatom.jl)]
        A --> G[e3nn + torch-ema<br/>MACE-specific]
    end

    subgraph "External QM Programs"
        A --> H[PySCF]
        A --> I[xtb]
        A --> J[MNDO / Sparrow]
        A --> K[Gaussian / ORCA / Turbomole]
        A --> L[DFTB+]
        A --> M[D4 dispersion]
        A --> N[COLUMBUS]
    end

    subgraph "Simulation & Optimization"
        A --> O[ASE]
        A --> P[geomeTRIC]
        A --> Q[PySCF freq]
        A --> R[pysisyphus]
    end

    subgraph "Spectroscopy"
        A --> S[RDKit<br/>MLTPA]
    end

    subgraph "Fortran Backend"
        A --> T[Intel/gfortran<br/>MKL / OpenBLAS]
    end

    style A fill:#4a90d9,color:#fff
    style B fill:#6db56d,color:#fff
    style C fill:#6db56d,color:#fff
```

## Quick Installation

The simplest way to install MLatom is via pip, which installs the core Python package along with its essential dependencies [Sources: [README.md](README.md#L33-L34)]:

```bash
python3 -m pip install -U mlatom
```

After installation, verify it works by importing the package:

```python
import mlatom as ml
print(ml.__version__)  # Should print 3.22.0
```

The core package imports reveal the foundational modules available immediately after installation: `MLatom`, `args_class`, `MLtasks`, `header`, `data`, `models`, `plot`, `simulations`, `stats`, `xyz`, `namd`, `constants`, `spectra`, `model_cls` [Sources: [__init__.py](mlatom/__init__.py#L4-L4)].

> [!TIP]
> If you plan to use ML models that involve training (KREG, ANI) or matrix operations (KRR with scipy solver), ensure `numpy` and `scipy` are installed — these are typically pulled in automatically as pip dependencies but may need manual installation in minimal environments.

## Core Dependencies

The following table lists the packages required for MLatom's core functionality. These are either installed automatically with pip or are part of the Python standard library.

| Dependency | Purpose | Used By |
|---|---|---|
| **numpy** | Array operations, linear algebra | Nearly every module — kernel matrices in KRR [Sources: [models.py](mlatom/models.py#L17-L17)], molecular coordinate handling, statistics |
| **scipy** | Sparse/dense linear solvers (Cholesky, LU decomposition) | KRR training with `ml_program='scipy'` [Sources: [models.py](mlatom/models.py#L207-L218)] |
| **json** (stdlib) | Reference metadata, model serialization | Header printing [Sources: [header.py](mlatom/header.py#L5-L5)], model dump/load |
| **os / sys / subprocess** (stdlib) | File I/O, environment variables, process spawning | External program interfaces, MLatomF bridge |

The `krr` class with the `scipy` solver uses `scipy.linalg.cho_factor` and `cho_solve` as its primary matrix decomposition strategy, falling back to LU decomposition when the kernel matrix is not positive definite [Sources: [models.py](mlatom/models.py#L207-L214)].

## Machine Learning Model Dependencies

MLatom integrates with a rich ecosystem of ML potential frameworks. These dependencies are only required when you use the corresponding model types.

### PyTorch-Based Models

PyTorch is the most widely required optional dependency, powering several universal ML potential interfaces:

| Model / Interface | Additional Requirements | Import Location |
|---|---|---|
| **TorchANI** (ANI-1x, ANI-1ccx, ANI-2x, MS-ANI) | `torchani` | [Sources: [torchani_interface.py](mlatom/interfaces/torchani_interface.py#L1-L50)] |
| **MACE** | `mace`, `e3nn`, `torch_geometric`, `torch_ema` | [Sources: [mace_interface.py](mlatom/interfaces/mace_interface.py#L1-L50)] |
| **AIMNet2** | `torchani` (shared infrastructure) | [Sources: [aimnet2_interface.py](mlatom/interfaces/aimnet2_interface.py#L1-L50)] |
| **KRR (scipy, gradient kernel)** | `torch` (for autograd in kernel derivatives) | [Sources: [models.py](mlatom/models.py#L318-L319)] |
| **GICnet** | `torch` | [Sources: [GICnet.py](mlatom/GICnet.py)] |
| **MDtrajNet** | `torch` | [Sources: [__init__.py](mlatom/__init__.py#L12-L12)] |

The model class hierarchy includes dedicated base classes for PyTorch integration: `torch_model` extends `model` with thread configuration, and `torchani_model` further extends `torch_model` with multiprocessing setup for TorchANI [Sources: [model_cls.py](mlatom/model_cls.py#L139-L154)].

Installation command for the full PyTorch ML stack:

```bash
pip install torch torchani mace-torch e3nn torch_geometric torch-ema
```

### TensorFlow-Based Models

| Model / Interface | Additional Requirements | Notes |
|---|---|---|
| **PhysNet** | `tensorflow`, PhysNet source code | Expects `$PhysNet` environment variable pointing to installation directory [Sources: [physnet_interface.py](mlatom/interfaces/physnet_interface.py#L17-L31)] |
| **DeePMD-kit** | `tensorflow`, DeePMD-kit | Expects `$DeePMDkit` environment variable [Sources: [dpmd_interface.py](mlatom/interfaces/dpmd_interface.py#L18-L22)] |

Both PhysNet and DeePMD-kit use TensorFlow v1 compatibility mode. The `tensorflow_model` base class inherits from `model` and handles thread configuration for TF [Sources: [model_cls.py](mlatom/model_cls.py#L157-L157)].

### sGDML Interface

The symmetric Gradient Domain Machine Learning (sGDML) package provides its own GDML models. MLatom's interface converts molecular databases to sGDML data format and wraps the GDML train/predict pipelines [Sources: [sgdml_interface.py](mlatom/interfaces/sgdml_interface.py#L1-L60)].

```bash
pip install sgdml
```

### GAP/SOAP Interface

The Gaussian Approximation Potential (GAP) with SOAP descriptors requires external executables rather than Python packages. You must set two environment variables [Sources: [gap_interface.py](mlatom/interfaces/gap_interface.py#L18-L26)]:

```bash
export gap_fit=/path/to/gap_fit_executable
export quip=/path/to/quip_executable
```

### Julia Backend for KRR

MLatom can delegate KRR computations to a Julia implementation (`mlatom.jl`), which requires both Julia and the `PyJulia` Python bridge. The Julia KRR module supports Gaussian, periodic Gaussian, decaying periodic Gaussian, and Matern kernels [Sources: [models.py](mlatom/models.py#L128-L171)].

```bash
# Install Julia (e.g., via juliaup or system package manager)
pip install julia
python -c "import julia; julia.install()"
```

> [!TIP]
> When choosing between KRR solvers: `scipy` is the most portable (pure Python), `mlatom.jl` may offer performance benefits for large datasets, and `MLatomF` (Fortran) provides the highest performance but requires Fortran compilation. The solver is selected via the `ml_program` parameter.

## External Quantum Chemistry Program Interfaces

MLatom can use external QM programs as reference methods, baseline calculators (for AIQM methods), or standalone energy/gradient engines. Each interface requires the corresponding program to be installed and accessible via an environment variable or PATH.

### Program Installation Summary

| Program | Environment Variable | Interface | Supported Methods |
|---|---|---|---|
| **PySCF** | (Python import) | [Sources: [pyscf_interface.py](mlatom/interfaces/pyscf_interface.py#L1-L50)] | HF, MP2, DFT, CCSD, TD-DFT, CISD, FCI, DM21 |
| **xtb** | (PATH) | [Sources: [xtb_interface.py](mlatom/interfaces/xtb_interface.py#L1-L50)] | GFN2-xTB, GFN2-xTB* |
| **MNDO** | `mndobin` | [Sources: [mndo_interface.py](mlatom/interfaces/mndo_interface.py#L1-L50)] | ODM2, ODM2*, ODM3, OM1-3, PM3, AM1, MNDO/d, SCC-DFTB |
| **Sparrow** | `sparrowbin` | (via MNDO interface) | ODM2, ODM2* |
| **Gaussian** | `GAUSS_EXEDIR` | [Sources: [gaussian_interface.py](mlatom/interfaces/gaussian_interface.py)] | DFT, ab initio, TD-DFT |
| **ORCA** | (PATH) | [Sources: [orca_interface.py](mlatom/interfaces/orca_interface.py)] | CCSD(T)*, DFT |
| **Turbomole** | (PATH) | [Sources: [turbomole_interface.py](mlatom/interfaces/turbomole_interface.py)] | DFT, MP2 |
| **DFTB+** | (PATH) | [Sources: [dftbplus_interface.py](mlatom/interfaces/dftbplus_interface.py)] | DFTB, TD-DFTB |
| **COLUMBUS** | `COLUMBUS` | [Sources: [columbus_interface.py](mlatom/interfaces/columbus_interface.py#L1-L50)] | CASSCF, MRCI |
| **D4 dispersion** | (via d4 Python package) | [Sources: [dftd4_interface.py](mlatom/interfaces/dftd4_interface.py)] | DFT-D4 |

Example environment setup for commonly used programs:

```bash
# xtb (usually installed via conda)
conda install -c conda-forge xtb

# PySCF
pip install pyscf

# MNDO/Sparrow (external binaries)
export mndobin=/path/to/mndo/bin
export sparrowbin=/path/to/sparrow/bin

# D4 dispersion correction
pip install d4
```

The `method_model` base class provides a unified pattern for external program interfaces: it implements `is_method_supported()`, `is_program_found()`, and `get_bin_env_var()` class methods that child interfaces override to declare their capabilities [Sources: [model_cls.py](mlatom/model_cls.py#L175-L206)].

## Simulation and Optimization Dependencies

### Geometry Optimization Engines

MLatom supports multiple optimization backends. The `header.py` module demonstrates an automatic fallback mechanism: it first attempts to import `geometric`, then falls back to `scipy` for optimization, and checks for `ase` as an additional option [Sources: [header.py](mlatom/header.py#L147-L158)].

| Engine | Package | Install Command |
|---|---|---|
| **geomeTRIC** | `geometric` | `pip install geometric` |
| **ASE** | `ase` | `pip install ase` |
| **PySCF** | `pyscf` | `pip install pyscf` (for PySCF-based optimization) |
| **Gaussian** | (external) | Must be installed separately |

The geomeTRIC interface wraps MLatom models into a `geometric.engine.Engine` subclass (`MLatomEngine`), converting between MLatom's internal molecule representation and geomeTRIC's coordinate system (Bohr ↔ Ångström) [Sources: [geometric_interface.py](mlatom/interfaces/geometric_interface.py#L1-L50)].

The ASE interface provides an `MLatomCalculator` (extending ASE's `Calculator` base class) that allows any MLatom model to be used within ASE's workflow, including geometry optimization, frequency calculations, and thermochemistry [Sources: [ase_interface.py](mlatom/interfaces/ase_interface.py#L1-L50)].

### Molecular Dynamics

The built-in MD engine (`mlatom/md.py`) requires only `numpy` and the internal `thermostat` module, supporting NVE and NVT ensembles with Andersen, Nosé-Hoover, and Langevin thermostats [Sources: [md.py](mlatom/md.py#L1-L60)].

For parallel molecular dynamics batch execution, no additional dependencies are needed beyond the core package [Sources: [__init__.py](mlatom/__init__.py#L9-L9)].

## Spectroscopy and Analysis Dependencies

| Feature | Dependency | Notes |
|---|---|---|
| IR/Raman spectra | `scipy` (interpolation), optional QM program | Linear/cubic interpolation via `scipy.interpolate.interp1d` [Sources: [spectra.py](mlatom/spectra.py#L38-L42)] |
| UV-Vis / ML-NEA | `numpy` | Nuclear ensemble approach with Wigner sampling |
| MLTPA (two-photon absorption) | `RDKit` | Referenced in header printing [Sources: [header.py](mlatom/header.py#L116-L117)] |
| Hyperparameter optimization | `hyperopt` | Tree-Structured Parzen Estimator algorithm [Sources: [header.py](mlatom/header.py#L119-L120)] |

## Add-on Models

MLatom includes an add-on system (`mlatom/addons/`) for premium models that require separate licensing or download. Currently, three add-on packages are structured in the repository [Sources: [addons/__init__.py](mlatom/addons/__init__.py)]:

| Add-on | Models | Status | Requirement |
|---|---|---|---|
| **AIQM3** | AIQM3, AIQM3@DFT | Requires Aitomistic subscription | Raises `ValueError` directing users to [mlatom.com/aitomic](http://mlatom.com/aitomic) [Sources: [aiqm3.py](mlatom/addons/aiqm3/aiqm3.py#L26-L35)] |
| **UAIQM** | Universal updatable AI-enhanced QM methods | Requires Aitomistic subscription | Multiple method variants (ODM2*, GFN2-xTB*, DFT, CC baselines) [Sources: [uaiqm.py](mlatom/addons/uaiqm/uaiqm.py#L36-L44)] |
| **OmniP2x** | Multi-state potentials (vecMSANI) | Requires Aitomistic subscription | Excited-state dynamics [Sources: [addons/__init__.py](mlatom/addons/__init__.py)] |

The `downloadable_model` class in `model_cls.py` provides infrastructure for downloading model files from remote URLs, handling zip extraction and path flattening — used by universal models like ANI-1x, ANI-1ccx, MACE-OFF, and AIMNet2 [Sources: [model_cls.py](mlatom/model_cls.py#L208-L313)].

## Fortran Backend (MLatomF)

MLatom includes a Fortran backend called **MLatomF** located in `mlatom/MLatomF_src/`. This is a standalone Fortran executable that handles kernel ridge regression (KREG), descriptor generation (Coulomb Matrix, RE, ID), and model training with hyperparameter optimization [Sources: [MLatomF_src/Makefile](mlatom/MLatomF_src/Makefile#L1-L61)].

### Compilation Requirements

The MLatomF Makefile includes multiple compiler configuration files:

| Makefile | Compiler | Notes |
|---|---|---|
| `Makefile.intel` | Intel Fortran (ifort) + MKL | Default; highest performance with Intel MKL for BLAS/LAPACK |
| `Makefile.gnu` | GNU Fortran (gfortran) + OpenBLAS | Open-source alternative |
| `Makefile.cygwin` | Intel Fortran (Cygwin) | Windows via Cygwin |

The build produces two artifacts: the `MLatomF` executable and `cs.so` (a shared library for ML-NEA cross-section calculations via C++) [Sources: [MLatomF_src/Makefile](mlatom/MLatomF_src/Makefile#L37-L40)].

### Compilation Steps

```bash
cd mlatom/MLatomF_src/

# Edit Makefile to select your compiler:
# Change "include Makefile.intel" to "include Makefile.gnu" if using gfortran
vim Makefile

# Compile
make clean
make
```

The Python interface to MLatomF (`mlatom/interface_MLatomF.py`) invokes the compiled binary via `subprocess.Popen`, passing command-line arguments and parsing stdout for timing and result information [Sources: [interface_MLatomF.py](mlatom/interface_MLatomF.py#L1-L50)].

### Fortran KREG Module (Optional)

A separate Fortran KREG module exists in `mlatom/fortran/` with its own compilation script. The compile script in `compile.py` shows it uses `f2py` (from NumPy) to build a Python-callable shared object from `KREG.f90`, linking against Intel MKL and OpenMP for parallel execution [Sources: [compile.py](mlatom/fortran/compile.py#L1-L10)].

## Complete Dependency Map by Feature

The following table provides a comprehensive, feature-oriented dependency checklist. Use it to determine exactly what you need to install for your intended workflow.

| Feature / Workflow | Required Packages | External Programs | Environment Variables |
|---|---|---|---|
| **Basic prediction with pre-trained ML models** | `mlatom`, `numpy`, `torch` | — | — |
| **Training KRR models (scipy solver)** | `mlatom`, `numpy`, `scipy`, `torch` | — | — |
| **Training KRR models (Julia solver)** | + `julia`, PyJulia | Julia runtime | — |
| **ANI models** | + `torchani`, `torch` | — | — |
| **MACE models** | + `mace-torch`, `e3nn`, `torch_geometric`, `torch_ema` | — | — |
| **AIMNet2 models** | + `torchani`, `torch` | — | — |
| **PhysNet models** | + `tensorflow` | PhysNet source | `$PhysNet` |
| **DeePMD-kit models** | + `tensorflow` | DeePMD-kit | `$DeePMDkit` |
| **GAP/SOAP models** | — | GAP, QUIP | `$gap_fit`, `$quip` |
| **sGDML models** | + `sgdml` | — | — |
| **AIQM1** | `torchani`, `torch` | MNDO or Sparrow, D4 | `$mndobin` or `$sparrowbin` |
| **AIQM2** | `torchani`, `torch` | xtb, D4 | (xtb in PATH) |
| **AIQM3 (add-on)** | Aitomistic subscription | xtb | — |
| **PySCF calculations** | + `pyscf` | — | — |
| **xtb calculations** | — | xtb | (xtb in PATH) |
| **MNDO semi-empirical** | — | MNDO | `$mndobin` |
| **Gaussian interface** | — | Gaussian | `$GAUSS_EXEDIR` |
| **ORCA interface** | — | ORCA | (orca in PATH) |
| **DFTB+ interface** | — | DFTB+ | (dftb+ in PATH) |
| **D4 dispersion** | + `d4` | — | — |
| **COLUMBUS interface** | — | COLUMBUS | `$COLUMBUS` |
| **Geometry optimization (geomeTRIC)** | + `geometric` | — | — |
| **Geometry optimization (ASE)** | + `ase` | — | — |
| **MLatomF backend** | — | Intel Fortran / gfortran, MKL / OpenBLAS | — |
| **Spectroscopy (IR/Raman)** | + `scipy` | Optional QM program | — |
| **Hyperparameter optimization** | + `hyperopt` | — | — |
| **Active learning** | `numpy`, `scipy`, model dependencies | Reference method | — |
| **MLTPA** | + `rdkit` | — | — |

## Verifying Your Installation

After installing MLatom and your desired dependencies, run this verification script to check what's available:

```python
import mlatom as ml

# Check core version
print(f"MLatom version: {ml.__version__}")

# Check optional dependencies
checks = {
    'numpy': lambda: __import__('numpy'),
    'scipy': lambda: __import__('scipy'),
    'torch': lambda: __import__('torch'),
    'ase': lambda: __import__('ase'),
    'geometric': lambda: __import__('geometric'),
    'pyscf': lambda: __import__('pyscf'),
}

for name, check in checks.items():
    try:
        check()
        print(f"  ✓ {name} available")
    except ImportError:
        print(f"  ✗ {name} not installed")

# Check environment variables for external programs
import os
env_checks = ['mndobin', 'sparrowbin', 'GAUSS_EXEDIR', 'COLUMBUS',
              'DeePMDkit', 'PhysNet', 'gap_fit', 'quip']
for var in env_checks:
    path = os.environ.get(var, None)
    if path:
        print(f"  ✓ ${var} = {path}")
    else:
        print(f"  ✗ ${var} not set")
```

## Troubleshooting Common Issues

| Problem | Likely Cause | Solution |
|---|---|---|
| `ImportError: cannot import name 'torch'` | PyTorch not installed | `pip install torch` |
| `please set $mndobin` | MNDO not configured | `export mndobin=/path/to/mndo/bin` |
| MLatomF binary not found | Fortran backend not compiled | `cd mlatom/MLatomF_src && make` |
| `ModuleNotFoundError: No module named 'julia'` | PyJulia not installed | `pip install julia && python -c "import julia; julia.install()"` |
| CUDA out of memory | Model too large for GPU | Set `device='cpu'` in model constructor |
| `cho_factor` LinAlgError | Non-positive-definite kernel matrix | MLatom falls back to LU automatically [Sources: [models.py](mlatom/models.py#L213-L216)] |

## Next Steps

With MLatom installed and dependencies configured, you're ready to begin using it. Here's a recommended reading progression based on the catalog:

- **[Usage Modes and Input Files](4-usage-modes-and-input-files)** — Learn the three ways to interact with MLatom: Python API, input files, and CLI
- **[Architecture Overview](5-architecture-overview)** — Understand the internal design that makes MLatom's modular dependency system work
- **[Quick Start](2-quick-start)** — If you skipped ahead, revisit this for your first calculations

For deeper dives into specific model systems and their dependencies:
- **[Kernel Ridge Regression Models](10-kernel-ridge-regression-models)** — Detailed setup for scipy, Julia, and Fortran KRR backends
- **[AIQM Methods and Delta Learning](11-aiqm-methods-and-delta-learning)** — Configure ANI + semi-empirical baselines for AIQM1/AIQM2
- **[Quantum Chemistry Program Interfaces](14-quantum-chemistry-program-interfaces)** — Full setup for each external QM program
- **[Universal ML Potential Interfaces](15-universal-ml-potential-interfaces)** — Configure TorchANI, MACE, DeePMD-kit, and others