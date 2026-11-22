

TeraChem provides GPU-accelerated quantum chemistry calculations for Q|R's quantum refinement pipeline, offering exceptional performance for large-scale biomolecular systems. This integration enables efficient computation of QM-derived restraints through the Atomic Simulation Environment (ASE) framework, allowing Q|R to leverage TeraChem's specialized hardware acceleration for density functional theory (DFT) calculations.

## Architecture Overview

The TeraChem integration follows a modular calculator pattern that bridges Q|R's refinement engine with TeraChem's computational capabilities. The implementation centers on the `TeraChem` class in [plugin/ase/terachem_qr.py](plugin/ase/terachem_qr.py#L18-L234), which inherits from ASE's base `Calculator` class and provides the interface methods required by Q|R's refinement infrastructure.

```mermaid
graph TD
    A[Q|R Refinement Loop] --> B[Calculator Wrapper]
    B --> C[TeraChem ASE Calculator]
    C --> D[Input Generation]
    C --> E[TeraChem Execution]
    C --> F[Output Parsing]
    D --> G[.sp Input File]
    E --> H[TeraChem GPU Process]
    H --> I[.out Output File]
    F --> J[Energy & Forces]
    J --> B
    B --> K[Restraints Manager]
    K --> A
```

The calculator is instantiated and managed through Q|R's `minimizer_ase` class in [driver.py](driver.py#L185-L249), which orchestrates the LBFGS optimization steps. Each optimization cycle triggers the calculator's `run_qr` method, which executes a single-point energy and gradient calculation on the current atomic configuration.

> [!TIP]
> The TeraChem calculator automatically handles unit conversions: energies are read in Hartree and converted to kcal/mol, while forces (gradients) in Hartree/Bohr are converted to kcal/mol/Å for compatibility with Q|R's internal units.

## Configuration and Initialization

The TeraChem calculator accepts comprehensive initialization parameters that control both QM theory and execution environment. The constructor signature in [plugin/ase/terachem_qr.py#L20](plugin/ase/terachem_qr.py#L20) exposes the following configuration options:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `command` | `None` | Explicit TeraChem execution command (overrides environment variable) |
| `gpus` | `'1    1'` | GPU specification (space-separated device IDs) |
| `basis` | `'6-31g'` | AO basis set for molecular orbitals |
| `coordinates` | `'tmp_ase.pdb'` | PDB file for atomic coordinates |
| `charge` | `'0'` | Total molecular charge |
| `method` | `'rhf'` | Quantum chemistry method (HF, DFT functional) |
| `dftd` | `'no'` | DFT-D dispersion correction (`'no'`, `'yes'`, or `'bj'`) |
| `run` | `'gradient'` | Calculation type (gradient for refinement) |

A global `key_parameters` dictionary ([line 16](plugin/ase/terachem_qr.py#L16)) stores additional advanced configuration options, including multibasis specifications for elements requiring effective core potentials (Se, Cl, Cd, Zn, Mg), SCF convergence thresholds, and maximum iteration limits.

## Input File Generation

The `write_input` method ([lines 45-83](plugin/ase/terachem_qr.py#L45-L83)) constructs TeraChem's input format with the following structure:

1. **Working Directory Setup**: Creates a temporary directory structure with `tmp/scr` subdirectory for scratch files, ensuring clean workspace isolation
2. **Molecular Coordinates**: Writes atomic positions in PDB format using ASE's `write` function, with periodic boundary conditions disabled for molecular systems
3. **Parameter Serialization**: Iterates through `key_parameters` and writes key-value pairs in TeraChem's expected format
4. **Multibasis Handling**: Special formatting for pseudopotential specifications using `$multibasis...$end` blocks

The input file ends with the `end` keyword, completing TeraChem's expected input syntax. When `terachem_file=True`, the calculator skips generation and uses a pre-existing input file, providing flexibility for advanced users to manually specify complex calculations.

## Execution Environment

The calculator's execution environment requires specific configuration for TeraChem's GPU-accelerated architecture:

**Command Resolution**: The `get_command` method ([lines 84-89](plugin/ase/terachem_qr.py#L84-L89)) and its overload ([lines 222-228](plugin/ase/terachem_qr.py#L222-L228)) implement a fallback hierarchy:
1. Explicit `command` parameter passed to constructor
2. `TeraChem_COMMAND` environment variable
3. `TERACHEM_COMMAND` environment variable (alternative naming)

**Library Path Configuration**: On Linux systems, the calculator automatically augments `LD_LIBRARY_PATH` to include TeraChem's library directory ([lines 107-113](plugin/ase/terachem_qr.py#L107-L113)), ensuring dynamic linking resolution for GPU runtime libraries.

**Subprocess Management**: The `run` method ([lines 91-130](plugin/ase/terachem_qr.py#L91-L130)) executes TeraChem via Python's `subprocess` module with output redirection to capture the full calculation log in the `.out` file. Exit codes are monitored, raising a `RuntimeError` if TeraChem terminates abnormally.

## Output Parsing

The calculator extracts results from TeraChem's output file using specialized parsing methods that handle the program's specific output format:

**Energy Extraction** ([lines 131-148](plugin/ase/terachem_qr.py#L131-L148)): The `read_energy` method searches for the `FINAL ENERGY:` marker and extracts the value in atomic units, then applies the conversion factor `Hartree/(kcal/mol)` to return energy in Q|R's expected units.

**Force Extraction** ([lines 150-176](plugin/ase/terachem_qr.py#L150-L176)): The `read_forces` method locates the gradient section marked by `Gradient units`, extracts the force components for each atom (three columns corresponding to x, y, z components), and handles TeraChem's formatting of infinite values (represented as `*****`) by replacing them with a large finite number. The extracted gradients are negated (forces = -gradients) and unit-converted to kcal/mol/Å.

## Integration with Q|R Refinement

The TeraChem calculator integrates with Q|R's refinement loop through the `run_qr` method ([lines 230-233](plugin/ase/terachem_qr.py#L230-L233)), which provides the standard interface expected by Q|R's calculator abstraction layer. This method:

1. Updates the calculator's atomic configuration
2. Applies any runtime parameter modifications via the `set` method ([lines 214-217](plugin/ase/terachem_qr.py#L214-L217))
3. Triggers calculation execution via the `run` method

The calculator's state management includes the `atoms_are_equal` method ([lines 178-205](plugin/ase/terachem_qr.py#L178-L205)), which implements tolerance-based comparison of atomic positions to avoid redundant calculations when geometry changes fall below the numerical threshold (default: 1.0e-6 Å).

**LBFGS Optimization**: When `params.refine.use_ase_lbfgs` is enabled, the `minimizer_ase` class ([driver.py#L185](driver.py#L185-L249)) manages the optimization loop, calling the calculator's `target_and_gradients` method at each step. The forces returned by TeraChem are negated and passed to ASE's LBFGS optimizer, which computes coordinate updates that are synchronized back to Q|R's internal structure representation.

## Usage Example

The basic invocation for quantum refinement using TeraChem follows the pattern documented in [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L12-L15):

```bash
qr.refine model.pdb model.mtz mode=refine engine_name=terachem
```

This command executes the default HF-D3(BJ)/6-31G calculation. Advanced usage requires setting the execution environment:

```bash
export TeraChem_COMMAND=/path/to/terachem/bin/terachem
qr.refine model.pdb model.mtz mode=refine engine_name=terachem \
    quantum.method=b3lyp quantum.basis=6-31g** quantum.dftd=bj
```

The integration supports the full range of quantum parameters accessible through Q|R's PHIL parameter system, enabling customization of method, basis set, dispersion corrections, and other QM-specific settings without modifying the underlying TeraChem calculator code.

## Advanced Configuration

For specialized applications requiring custom TeraChem features beyond the standard interface, users can:

1. **Disable Input Generation**: Set `terachem_file=True` and provide a manually crafted input file with advanced directives
2. **Specify Multiple GPUs**: Format the `gpus` parameter with space-separated device IDs (e.g., `'0    1    2'` for three GPUs)
3. **Configure ECPs**: Add element-specific pseudopotentials through the `multibasis` parameter in `key_parameters`
4. **Adjust SCF Convergence**: Modify `threall` and `maxit` parameters for difficult convergence cases

The calculator maintains separation between Q|R's refinement logic and TeraChem's execution details, ensuring that advanced TeraChem capabilities remain accessible through the parameter system without requiring code modifications.
