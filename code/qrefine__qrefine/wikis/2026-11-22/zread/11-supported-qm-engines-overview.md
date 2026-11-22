

Q|R provides a comprehensive quantum mechanical engine ecosystem that enables flexible quantum refinement workflows. The system integrates traditional quantum chemistry packages, semi-empirical methods, and modern machine learning potentials through a unified ASE (Atomic Simulation Environment) calculator architecture. This overview introduces the available QM engines, their characteristics, and how to select the appropriate engine for your refinement needs.

![Q|R Architecture](https://github.com/qrefine/qrefine/blob/master/doc/icons/QR1-2.png)

The QM engine integration follows a modular plugin architecture where each quantum chemistry package implements a common calculator interface. This design allows seamless switching between engines through the `engine_name` parameter without changing the refinement workflow. All calculators are located under `plugin/ase/` and extend base ASE Calculator classes with Q|R-specific methods for energy and force calculations.

Sources: [plugin/ase/README.md](plugin/ase/README.md#L1-L13), [restraints.py](restraints.py#L12-L20)

## Architecture Overview

The QM engine architecture demonstrates a clean separation of concerns where Q|R's refinement engine delegates quantum calculations to specialized ASE calculator plugins. Each plugin handles its own job submission, output parsing, and computational resource management while presenting a standardized interface to the refinement system.

```mermaid
graph TB
    A[Q|R Refinement Engine] --> B[Restraints Manager]
    B --> C{Engine Selection}
    C -->|engine_name='gaussian'| D[Gaussian Calculator]
    C -->|engine_name='mopac'| E[MOPAC Calculator]
    C -->|engine_name='orca'| F[ORCA Calculator]
    C -->|engine_name='terachem'| G[TeraChem Calculator]
    C -->|engine_name='turbomole'| H[Turbomole Calculator]
    C -->|engine_name='xtb'| I[GFN-xTB Calculator]
    C -->|engine_name='pyscf'| J[PySCF Calculator]
    C -->|engine_name='ani'| K[ANI Calculator]
    C -->|engine_name='torchani'| L[TorchANI Calculator]
    C -->|engine_name='aimnet2'| M[AIMNet2 Calculator]
    
    D & E & F & G & H & I & J & K & L & M --> N[run_qr Method]
    N --> O[Energy Calculation]
    N --> P[Force Calculation]
    O & P --> Q[Restraint Gradients]
    Q --> A
    
    style A fill:#e1f5ff
    style C fill:#fff4e1
    style D fill:#ffe1e1
    style E fill:#ffe1e1
    style F fill:#ffe1e1
    style G fill:#ffe1e1
    style H fill:#ffe1e1
    style I fill:#ffe1e1
    style J fill:#e1ffe1
    style K fill:#f0e1ff
    style L fill:#f0e1ff
    style M fill:#f0e1ff
```

The core integration point is the `run_qr()` method, which all QM calculator plugins implement. This method accepts atomic coordinates, charges, and point charges, then returns calculated energies and forces. The refinement engine calls this method for each fragment during the optimization cycle, using the QM-derived forces to guide structural refinement.

Sources: [restraints.py](restraints.py#L12-L20), [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L326-L334), [plugin/ase/mopac_qr.py](plugin/ase/mopac_qr.py#L367-L372)

## Plugin Directory Structure

The QM engine plugins are organized in a dedicated `plugin/ase/` directory, with each quantum chemistry package represented by a dedicated Python module. This structure facilitates maintenance and allows for straightforward addition of new quantum chemistry engines.

```
plugin/ase/
├── __init__.py
├── gaussian_qr.py       # Gaussian G16 interface
├── mopac_qr.py          # MOPAC semi-empirical
├── orca_qr.py           # ORCA quantum chemistry
├── terachem_qr.py       # TeraChem GPU-accelerated
├── turbomole_qr.py      # Turbomole quantum chemistry
├── xtb_qr.py            # GFN-xTB semi-empirical
├── pyscf_qr.py          # PySCF Python-based QM
├── ani_qr.py            # ANI neural network
├── torchani_qr.py       # TorchANI neural network
├── aimnet2_qr.py        # AIMNet2 neural network
├── server_qr.py         # REST API calculator interface
└── ani/                 # ANI model files
    └── ani_interface.py
```

This modular design enables Q|R to support a wide range of computational chemistry methods, from traditional ab initio calculations to modern machine learning potentials, all through a consistent interface.

Sources: [plugin/ase/README.md](plugin/ase/README.md#L1-L13), [get_repo_structure plugin/ase](plugin/ase/)

## Engine Categories

QM engines in Q|R fall into three main categories: traditional quantum chemistry packages, semi-empirical methods, and machine learning potentials. Each category offers different trade-offs between accuracy, computational cost, and system size limitations.

| Category | Engines | Typical Use Case | Speed | Accuracy |
|----------|---------|------------------|-------|----------|
| **Traditional QM** | Gaussian, ORCA, TeraChem, Turbomole, PySCF | High-accuracy studies, benchmarking, small fragments | Slow | High |
| **Semi-empirical** | MOPAC, xTB | Medium-sized fragments, exploratory calculations | Fast | Moderate |
| **ML Potentials** | ANI, TorchANI, AIMNet2 | Large systems, rapid screening, production refinement | Very Fast | Good (for trained elements) |

> [!TIP]
> The choice of QM engine significantly impacts refinement runtime and accuracy. Start with semi-empirical methods for initial testing, then validate with higher-level calculations for final refinement.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L1-L50), [plugin/ase/README.md](plugin/ase/README.md#L8-L13)

## Traditional Quantum Chemistry Engines

Traditional QM engines provide the highest accuracy but require the most computational resources. These packages implement established quantum chemistry methods including Hartree-Fock, density functional theory, and post-HF methods.

### Gaussian

Gaussian is one of the most widely used quantum chemistry packages, supporting a comprehensive set of methods and basis sets. The Q|R interface is compatible with Gaussian 16 (g16) and provides extensive customization options through Link0 and route section keywords.

Key features:
- Default method: HF/STO-3G
- Customizable via `quantum.method` and `quantum.basis` parameters
- Supports advanced features like DFT-D3 and gCP corrections through qm_addon
- Requires `g16` binary installation

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L26-L42), [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L107-L140)

### ORCA

ORCA is a free quantum chemistry package that excels in DFT calculations and provides excellent support for density functional approximations and dispersion corrections. The interface supports parallel execution and requires the full path to the `orca` binary in `ORCA_COMMAND`.

Key features:
- Default method: RHF/6-31G
- Strong parallel execution support
- Rich functional and basis set library
- Active development community

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L19-L27), [plugin/ase/orca_qr.py](plugin/ase/orca_qr.py#L36-L51)

### TeraChem

TeraChem is a GPU-accelerated quantum chemistry package designed for rapid DFT calculations. It's particularly effective for systems requiring many single-point energy and force evaluations during refinement cycles.

Key features:
- Default method: HF-D3(BJ)/6-31G
- GPU-accelerated for high throughput
- Requires `TeraChem_COMMAND` environment variable
- Ideal for time-sensitive refinement tasks

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L3-L18), [plugin/ase/terachem_qr.py](plugin/ase/terachem_qr.py#L18-L45)

### Turbomole

TeraChem's CPU-based counterpart, Turbomole, provides efficient quantum chemistry calculations with a focus on density functional theory and RI-J approximations for improved performance.

Key features:
- Default method: BP86/def2-SV(P)
- RI-J (Resolution of Identity) acceleration
- Requires Turbomole installation setup
- Supports custom Turbomole define strings

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L44-L56), [plugin/ase/turbomole_qr.py](plugin/ase/turbomole_qr.py#L30-L67)

### PySCF

PySCF is a Python-based quantum chemistry framework that provides programmatic access to quantum chemistry methods. Its native Python implementation facilitates easy integration and customization.

Key features:
- Default method: Hartree-Fock
- Pure Python implementation
- Requires `qrefine.python -m pip install pyscf`
- Extensible architecture for custom methods

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L200-L211), [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L18-L33)

## Semi-empirical Methods

Semi-empirical methods provide significantly faster calculations than traditional QM by parameterizing core aspects of the quantum mechanical treatment. These methods are ideal for larger fragments and exploratory refinement.

### MOPAC

MOPAC implements semi-empirical quantum chemistry methods, with PM7 being the most widely used. It offers a good balance between speed and accuracy for organic molecules.

Key features:
- Default method: PM7
- Very fast execution
- Requires `MOPAC_COMMAND` and optionally `MOPAC_DIR`
- Well-suited for organic systems

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L58-L69), [plugin/ase/mopac_qr.py](plugin/ase/mopac_qr.py#L26-L78)

### GFN-xTB

GFN-xTB (Grimme's extended tight-binding) provides a modern semi-empirical approach with good accuracy across a wide range of chemical systems. Q|R supports both GFN1-xTB and GFN2-xTB.

Key features:
- Default method: GFN2-xTB with GBSA
- Switch to GFN1-xTB via `quantum.method='--gfn 1 --gbsa h2o'`
- Requires `XTBHOME` environment variable
- Broad chemical coverage

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L71-L87), [plugin/ase/xtb_qr.py](plugin/ase/xtb_qr.py#L22-L57)

## Machine Learning Potentials

Machine learning potentials leverage neural networks trained on high-level quantum chemistry data to provide near-quantum accuracy at dramatically reduced computational cost. These methods are ideal for large-scale refinement tasks.

### ANI

The ANI (Accurate Neural Network engine) models provide deep learning potentials trained on DFT calculations. The original ASE_ANI implementation is supported.

Key features:
- Supports ANI models via ASE calculator
- Requires ANI ASE calculator installation
- Atom type restrictions apply (typically C, H, N, O)

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L89-L110), [plugin/ase/ani_qr.py](plugin/ase/ani_qr.py#L11-L21)

### TorchANI

TorchANI is a PyTorch-based implementation of ANI models, providing GPU acceleration and a modern deep learning framework. Q|R includes a specialized qrefine branch with optimized models.

Key features:
- Default model: ani-1x_8x (qr-ef variant)
- GPU acceleration through PyTorch
- Requires PyTorch and torchani installation
- Currently trained on C, H, N, O atoms only

> [!TIP]
> Machine learning potentials like TorchANI offer 2-3 orders of magnitude speedup over DFT with comparable accuracy for systems within their training set. Verify your system's atom types are supported before use.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L112-L152), [plugin/ase/torchani_qr.py](plugin/ase/torchani_qr.py#L1-L48)

### AIMNet2

AIMNet2 is a neural network potential that includes explicit treatment of atomic interactions and provides state-of-the-art accuracy for molecular systems. The Q|R interface extends the original AIMNet2 ASE calculator.

Key features:
- Deep learning potential with AIM methodology
- Built on AIMNet2 ASE calculator
- Requires aimnet2calc package
- Integrated into Q|R workflow through specialized calculator class

Sources: [plugin/ase/aimnet2_qr.py](plugin/ase/aimnet2_qr.py#L1-L18), [aimnet2.md](aimnet2.md)

## Interface Verification

Q|R provides a built-in utility to verify which QM engines are properly installed and configured on your system:

```bash
qr.build_interfaces
```

This command checks the availability of each QM calculator and reports their status, ensuring that your chosen engine is ready for refinement tasks.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L1-L6)

## Configuration Parameters

All QM engines share a common set of configuration parameters that control their behavior during refinement:

| Parameter | Purpose | Example |
|-----------|---------|---------|
| `quantum.engine_name` | Selects the QM engine | `engine_name=mopac` |
| `quantum.method` | Specifies computational method | `quantum.method='b3lyp'` |
| `quantum.basis` | Sets basis set (for ab initio engines) | `quantum.basis='6-31g*'` |
| `quantum.charge` | Sets system charge | `quantum.charge=0` |
| `quantum.qm_addon` | Enables correction methods | `qm_addon=dftd3` |
| `quantum.qm_addon_method` | Specifies correction parameters | `qm_addon_method="b3-lyp -bj"` |

> [!TIP]
> For production refinements, start with `engine_name=xtb` or `engine_name=mopac` for rapid convergence testing, then switch to higher-level methods like `engine_name=orca` or `engine_name=terachem` for final accuracy.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L223-L268), [qr.py](qr.py#L258-L276)

## Post-HF Corrections

Q|R supports advanced corrections through the `qm_addon` parameter, enabling dispersion corrections (DFT-D3) and basis set superposition error corrections (gCP) for improved accuracy.

### DFT-D3 Dispersion Correction

Add Grimme's D3 dispersion with Becke-Johnson damping to DFT calculations:

```bash
qr.refine model.pdb model.mtz \
    quantum.qm_addon=dftd3 \
    quantum.qm_addon_method="b3-lyp -bj"
```

The `qm_addon_method` string is passed directly to the `dftd3` program via the `-func` flag.

### gCP BSSE Correction

Add geometry counterpoise corrections for basis set superposition errors:

```bash
qr.refine model.pdb model.mtz \
    quantum.qm_addon=gcp \
    quantum.qm_addon_method="hf/631g"
```

The gCP program requires pre-parameterized basis sets and will error if an unsupported combination is specified.

### Combined Corrections

Apply both corrections simultaneously:

```bash
qr.refine model.pdb model.mtz \
    quantum.qm_addon=gcp-d3 \
    quantum.qm_addon_method="hf/631g+b3-lyp -bj"
```

Separate the gCP and D3 method strings with a `+` sign, with gCP parameters first.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L223-L268)

## Engine Selection Workflow

Selecting the appropriate QM engine depends on your refinement goals, available computational resources, and system characteristics. Consider the following decision factors:

```mermaid
flowchart TD
    A[Start Engine Selection] --> B{System Size}
    B -->|Small (<50 atoms)| C{Accuracy Requirement}
    B -->|Medium (50-200)| D{Time Constraints}
    B -->|Large (>200)| E[ML Potentials]
    
    C -->|Highest| F[Gaussian/ORCA/TeraChem]
    C -->|Balanced| G[PySCF/Turbomole]
    
    D -->|Tight| H[GFN-xTB]
    D -->|Flexible| I[MOPAC]
    
    E --> J{Atoms in Training Set}
    J -->|Yes| K[TorchANI/AIMNet2]
    J -->|No| L[GFN-xTB]
    
    F --> M[Final Refinement]
    G --> M
    H --> N[Testing/Exploration]
    I --> N
    K --> M
    L --> N
    
    style F fill:#ffe1e1
    style G fill:#ffe1e1
    style H fill:#fff4e1
    style I fill:#fff4e1
    style K fill:#f0e1ff
    style L fill:#fff4e1
```

For new users, we recommend starting with **GFN-xTB** for initial testing and refinement cycles, then validating results with a higher-level method like **ORCA** or **TeraChem** for final production runs.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L1-L268), [plugin/ase/README.md](plugin/ase/README.md#L8-L13)

## Next Steps

To deepen your understanding of QM engine integration and configuration, proceed through the engine-specific documentation:

- For semi-empirical methods: [MOPAC Integration](12-mopac-integration)
- For ab initio methods: [Gaussian Integration](13-gaussian-integration), [ORCA Integration](14-orca-integration), [PySCF Integration](15-pyscf-integration)
- For tight-binding methods: [xTB Integration](16-xtb-integration)
- For machine learning potentials: [AQuaRef and AIMNet2](17-aquaref-and-aimnet2), [Terachem Integration](18-terachem-integration), [Turbomole Integration](19-turbomole-integration)

These detailed guides provide installation instructions, configuration examples, and best practices for each specific QM engine.