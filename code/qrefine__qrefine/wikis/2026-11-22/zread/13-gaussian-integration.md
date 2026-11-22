

Gaussian integration in Q|R provides quantum mechanical restraints through the Gaussian electronic structure package, enabling high-accuracy refinement for challenging biomolecular structures. This integration leverages the Atomic Simulation Environment (ASE) framework to interface with Gaussian, allowing seamless energy and force calculations during quantum refinement cycles.

## Architecture Overview

The Gaussian integration follows a layered architecture where Q|R orchestrates calculations through ASE, which in turn manages Gaussian's input/output workflow. This design enables consistent interfaces across multiple QM engines while respecting Gaussian's specific requirements for job submission and result parsing.

```mermaid
graph TB
    A[Q|R Refinement Engine] --> B[ASE Calculator Interface]
    B --> C[Gaussian Q|R Adapter]
    C --> D[Gaussian Executable g16]
    C --> E[Input Files .com .chk]
    C --> F[Output Files .log]
    D -.-> G[Q|M Energy/Forces]
    G --> H[Restraints Manager]
    H --> I[Refinement Loop]
    
    style A fill:#e1f5fe
    style B fill:#fff9c4
    style C fill:#c8e6c9
    style D fill:#ffccbc
```

The architecture enables Gaussian calculations to be treated as abstract energy/force providers, with the adapter handling all Gaussian-specific file formats and command construction.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L107-L358), [plugin/ase/README.md](plugin/ase/README.md#L1-L13)

## Implementation Details

### Core Calculator Class

The `Gaussian` class extends ASE's `FileIOCalculator`, implementing the standard ASE calculator interface while adding Q|R-specific methods for parameter configuration. The calculator is initialized with default parameters including charge (0), method (hf), basis (sto-3g), and force calculation enabled.

The calculator implements three core properties required by Q|R:
- **Energy**: Total electronic energy from Gaussian
- **Forces**: Gradient vectors for each atom
- **Dipole**: Molecular dipole moment

Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L107-L120)

### Input File Generation

Gaussian uses a specific input format with Link0 commands (prefixed with `%`) and a Route section (prefixed with `#`). The adapter automatically constructs proper input files by:

1. **Link0 Section**: System-level configuration including memory allocation, processor count, and checkpoint file management
2. **Route Section**: Quantum method specification including basis set, functional, and calculation type
3. **Molecule Specification**: Charge, multiplicity, and atomic coordinates in Cartesian format

The input generator distinguishes between different keyword types (Link0, Route self-keys, and Route keys) to format them correctly according to Gaussian syntax.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L26-L107), [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L186-L276)

> [!TIP]
> The multiplicity is automatically calculated as the sum of magnetic moments + 1 if not explicitly specified, ensuring correct handling of open-shell systems in quantum refinement workflows.

### Result Parsing

The calculator reads Gaussian output files (.log) using ASE's Gaussian reader to extract energy, forces, dipole moments, and multiplicity information. The magnetic moment is converted from Gaussian's multiplicity format (magnetic moment = multiplicity - 1) to ASE's standard format.

The `run_qr` method serves as the primary interface for Q|R, accepting new atomic positions and any parameter modifications, executing the calculation, and returning the forces and energy for restraint generation.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L293-L328)

### Configuration Options

Gaussian integration supports comprehensive parameter control through dedicated setter methods:

| Parameter | Method | Description | Example |
|-----------|--------|-------------|---------|
| Molecular Charge | `set_charge()` | Total charge of the system | `set_charge(0)` |
| Basis Set | `set_basis()` | Atomic orbital basis set | `set_basis('6-31G*')` |
| Quantum Method | `set_method()` | Electronic structure method | `set_method('B3LYP')` |
| Memory Allocation | `set_memory()` | Memory for Gaussian job | `set_memory('8GB')` |
| Processor Count | `set_nproc()` | Number of CPU cores | `set_nproc(4)` |

Additional flexibility is provided through `extra` (arbitrary route section text), `addsec` (additional Gaussian sections), and `ioplist` (internal option parameters) initialization parameters.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L336-L349), [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L121-L168)

## Integration with Q|R Workflow

The Gaussian calculator integrates into the refinement cycle through the `sites` calculator class, which manages the coordination between experimental data fitting and quantum restraints. During each refinement cycle:

1. **Weight Calculation**: The adaptive weight factor balances experimental data against QM restraints based on gradient magnitudes
2. **Geometry Update**: Atomic coordinates from the current model are passed to the Gaussian calculator
3. **Energy/Force Evaluation**: Gaussian computes quantum mechanical energies and atomic forces
4. **Restraint Application**: Forces are converted into geometric restraints for the next refinement step
5. **Convergence Check**: Bond and angle RMSD values determine if the refinement has converged

The clustering system can trigger re-clustering when atomic displacements exceed specified thresholds, ensuring that the QM region remains physically meaningful throughout refinement.
Sources: [calculator.py](calculator.py#L26-L63), [driver.py](driver.py#L301-L380), [driver.py](driver.py#L160-L184)

## Supported Gaussian Features

The integration supports Gaussian's Link0 and Route section keywords through categorized keyword lists:

### Link0 Commands
System configuration parameters prefixed with `%`, including checkpoint file management (`chk`), memory allocation (`mem`), read-write files (`rwf`), and parallel execution (`nprocshared`, `nproc`).

### Route Section Self-Keywords
Keywords that can be specified with or without options, such as geometry optimization (`opt`), force calculation (`force`), frequency analysis (`freq`), and solvation models (`scrf`).

### Route Section Keywords
Parameters that require values, including basis set specifications, SCF convergence criteria, integral accuracy, and various quantum chemistry methods.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L36-L106)

## Computational Considerations

### File Management

The calculator manages temporary files with configurable labels (default: `ase/tmp_ase`). Generated files include:
- **.com**: Gaussian input file
- **log**: Gaussian output file
- **chk**: Checkpoint file for restart capability

The `clean()` method removes these files after successful completion, though checkpoint files may be preserved for restart calculations.
Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L309-L322)

### Performance Optimization

Several factors influence Gaussian integration performance:
- **Basis Set Choice**: Larger basis sets (e.g., def2-TZVP) provide higher accuracy but require more computational resources
- **Method Selection**: Hybrid functionals (B3LYP, PBE0) are more accurate but slower than pure DFT methods
- **Parallel Execution**: Gaussian supports multi-core computation through `nprocshared` Link0 commands
- **Memory Allocation**: Adequate memory (`mem` parameter) prevents I/O bottlenecks

> [!TIP]
> For large biomolecular systems with fragmentation, ensure that individual fragments remain computationally tractable (< 100 atoms) to maintain reasonable refinement cycles.

### Error Handling

The calculator implements robust error handling through:
- Restart file detection with configurable ignore behavior
- Input validation for basis set files when using custom basis sets
- Comprehensive file existence checks before Gaussian execution
- Integration with ASE's ReadError exception handling Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L277-L293)

## Usage Example

The following example demonstrates typical Gaussian integration usage in a Q|R refinement workflow:

```python
from qrefine import calculator
from plugin.ase.gaussian_qr import Gaussian

# Initialize Gaussian calculator with parameters
gauss_calc = Gaussian(
    label='qr_gaussian',
    scratch='./scratch',
    extra='Integral=UltraFine SCF=QC'
)

# Configure calculation
gauss_calc.set_charge(0)
gauss_calc.set_method('B3LYP')
gauss_calc.set_basis('6-31G*')
gauss_calc.set_memory('8GB')
gauss_calc.set_nproc(4)

# The calculator is then integrated into Q|R's refinement cycle
# through the sites calculator class, which coordinates
# between experimental data and quantum restraints
```

Sources: [plugin/ase/gaussian_qr.py](plugin/ase/gaussian_qr.py#L121-L168), [calculator.py](calculator.py#L190-L287)

## Next Steps

For practical application of Gaussian integration, explore these related topics:

- **[Understanding Fragmentation](7-understanding-fragmentation)**: Learn how to partition large biomolecules for efficient QM calculations
- **[Weight Factor Calculation](24-weight-factor-calculation)**: Understand how experimental and QM restraints are balanced
- **[QM vs CCTBX Restraints](20-qm-vs-cctbx-restraints)**: Compare quantum restraints with traditional parameter-based restraints
- **[ORCA Integration](14-orca-integration)**: Explore alternative QM engine options for quantum refinement

For installation requirements and dependencies, see the [Supported QM Engines Overview](11-supported-qm-engines-overview).
Sources: [README.md](README.md#L24-L69)