

PySCF (Python Simulation of Chemistry Framework) represents a pure Python quantum chemistry package that Q|R integrates through the Atomic Simulation Environment (ASE) plugin architecture. This integration provides researchers with a Python-native quantum chemistry engine that supports both Hartree-Fock and Density Functional Theory calculations, making it particularly suitable for rapid prototyping and custom quantum refinement workflows. The PySCF interface leverages Q|R's modular QM engine design, allowing seamless switching between different quantum chemistry packages without modifying refinement protocols.

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L1-L129), [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L210-L225)

## Architecture Overview

The PySCF integration follows Q|R's standardized ASE calculator pattern, where the `Pyscf` class extends ASE's `Calculator` base class to provide quantum chemical energy and force calculations for molecular fragments during refinement. This architecture enables PySCF to function as a drop-in replacement for other QM engines while maintaining Python-native execution without requiring external binary dependencies or subprocess communication.

```mermaid
graph TD
    A[Q|R Refinement Engine] -->|Calls| B[ASE Calculator Interface]
    B -->|Instantiates| C[Pyscf Calculator]
    C -->|Manages| D[pyscf.gto.Mole Object]
    C -->|Executes| E{Quantum Method}
    E -->|HF| F[pyscf.scf.RHF]
    E -->|DFT| G[pyscf.dft.RKS]
    F -->|Computes| H[Energy & Forces]
    G -->|Computes| H
    H -->|Returns to| B
    B -->|Converts Units| I[kcal/mol & Å]
    I -->|Provides to| A
```

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L18-L28), [plugin/ase/README.md](plugin/ase/README.md#L1-L13)

## Installation and Setup

PySCF installation follows a straightforward pip-based approach that requires no external binary compilation, making it one of the most accessible QM engines in the Q|R ecosystem. The installation process leverages the Q|R Python environment to ensure proper dependency resolution and compatibility with the refinement framework. After installation, Q|R automatically detects PySCF through the `qr.build_interfaces` command-line utility, which validates the integration and confirms engine availability for refinement workflows.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L210-L215), [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L1-L8)

## Configuration Parameters

The PySCF calculator accepts a standardized set of configuration parameters that control quantum chemical calculations and molecular system properties. These parameters can be specified through Q|R's command-line interface using the `quantum.` prefix, enabling flexible customization of computational methods while maintaining consistency with other QM engine interfaces.

| Parameter | Default | Description | Valid Values |
|-----------|---------|-------------|--------------|
| `quantum.basis` | `'631g'` | Atomic orbital basis set | Any PySCF-supported basis set |
| `quantum.method` | `'hf'` | Quantum chemistry method | `'hf'`, `'dft'` |
| `quantum.charge` | `0` | Molecular charge | Integer values |
| `quantum.spin` | `0` | Spin multiplicity | Integer values |

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L19-L19), [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L33-L47)

## Supported Quantum Methods

PySCF integration currently supports two primary quantum chemistry methods: Hartree-Fock (HF) and Density Functional Theory (DFT). The HF implementation uses PySCF's `RHF` (Restricted Hartree-Fock) module, which provides accurate wavefunction-based energy calculations suitable for systems where electron correlation effects are minimal. The DFT implementation employs the `RKS` (Restricted Kohn-Sham) approach with the BP86 exchange-correlation functional by default, offering improved accuracy for systems requiring electron correlation treatment while maintaining computational efficiency.

> [!TIP]
> The DFT implementation in the PySCF integration currently hardcodes BP86 as the exchange-correlation functional. If you require other functionals, you may need to modify the source code in `plugin/ase/pyscf_qr.py` line 61 to specify your preferred functional via the `xc` parameter.

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L60-L64), [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L222-L225)

## Implementation Details

The PySCF calculator implementation converts ASE atomic objects into PySCF molecular format, extracting atomic symbols and positions to construct a `pyscf.gto.Mole` object that represents the quantum system. This conversion process includes setting molecular properties such as charge and spin multiplicity, which can be dynamically updated during refinement cycles to account for different electronic states in molecular fragments. The calculator manages computational parameters including SCF convergence thresholds (`1e-8`), gradient convergence criteria (`1e-12`), maximum SCF cycles (200), and memory allocation (1000 MB) to ensure robust and efficient calculations across diverse molecular systems.

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L54-L84), [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L19-L28)

## Unit Conversion and Output

PySCF performs calculations in atomic units (Hartree for energy, Bohr for distance), which the integration layer converts to Q|R's preferred units of kcal/mol for energy and Å for forces. The energy conversion factor multiplies Hartree values by `Hartree/(kcal/mol)`, while force conversion applies `-Hartree/Bohr/(kcal/mol)` to transform atomic unit gradients into proper force vectors. This unit transformation ensures compatibility with Q|R's restraint system and optimization engine, which operate in conventional chemical units rather than atomic units.

Sources: [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L8-L11), [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L67-L70)

## Usage Examples

Basic usage of PySCF for quantum refinement follows the standard Q|R interface pattern, requiring specification of the PDB structure, reflection data, and engine selection. The default Hartree-Fock calculation with the 6-31G basis set provides a robust starting point for refinement workflows, while DFT calculations offer improved accuracy for systems requiring electron correlation treatment.

```bash
# Default Hartree-Fock calculation
qr.refine model.pdb model.mtz mode=refine engine_name=pyscf

# DFT calculation with BP86 functional (default DFT)
qr.refine model.pdb model.mtz mode=refine engine_name=pyscf quantum.method=dft

# Custom basis set specification
qr.refine model.pdb model.mtz mode=refine engine_name=pyscf quantum.basis=ccpvdz
```

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L222-L225), [plugin/ase/pyscf_qr.py](plugin/ase/pyscf_qr.py#L19-L19)

## Advantages and Considerations

PySCF offers several distinct advantages as a QM engine for quantum refinement: pure Python implementation eliminates compilation and external binary dependencies, facilitating installation and cross-platform compatibility; the open-source nature enables custom method development and integration of specialized quantum chemistry techniques; and direct Python integration allows for sophisticated workflow automation and method prototyping. However, users should consider that PySCF may have different computational performance characteristics compared to compiled packages like Gaussian or ORCA, particularly for large systems or highly efficient implementations of certain methods.

Sources: [plugin/ase/README.md](plugin/ase/README.md#L1-L13), [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L12-L26)

## Integration with QM Add-ons

The PySCF interface can be enhanced with quantum chemistry corrections through Q|R's qm_addon system, which supports DFT-D3 dispersion corrections and gCP (geometrical counterpoise) BSSE corrections. These add-ons enable improved treatment of van der Waals interactions and basis set superposition errors, respectively, enhancing the accuracy of quantum refinement calculations while maintaining compatibility with PySCF's native functionality. The addon corrections are applied externally to the PySCF calculations, allowing flexible combination of quantum methods with dispersion and BSSE treatments.

Sources: [rst_files/qr/qm_interfaces.txt](rst_files/qr/qm_interfaces.txt#L228-L268), [plugin/tools/qr_tools.py](plugin/tools/qr_tools.py#L1-L5)

## Next Steps

To deepen your understanding of Q|R's quantum refinement capabilities, explore related documentation that covers complementary aspects of the framework. Understanding how PySCF fits into the broader QM engine ecosystem helps optimize your refinement workflow, while knowledge of fragmentation strategies enables efficient treatment of large biomolecular systems. Additionally, exploring restraint systems and optimization engines provides context for how quantum energies and forces integrate with crystallographic refinement targets.

- [Supported QM Engines Overview](11-supported-qm-engines-overview) - Compare PySCF with other available QM packages
- [Understanding Fragmentation](7-understanding-fragmentation) - Learn how molecular systems are divided for quantum calculations
- [QM vs CCTBX Restraints](20-qm-vs-cctbx-restraints) - Understand how PySCF outputs integrate with refinement restraints
- [Weight Factor Calculation](24-weight-factor-calculation) - See how quantum energies contribute to refinement targets
- [MOPAC Integration](12-mopac-integration) - Compare PySCF with the semi-empirical MOPAC alternative
