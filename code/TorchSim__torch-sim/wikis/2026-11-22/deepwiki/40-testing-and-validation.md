# Testing and Validation

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [tests/conftest.py](tests/conftest.py)
- [tests/models/test_lennard_jones.py](tests/models/test_lennard_jones.py)
- [tests/models/test_mace.py](tests/models/test_mace.py)
- [tests/models/test_orb.py](tests/models/test_orb.py)
- [tests/models/test_sevennet.py](tests/models/test_sevennet.py)
- [tests/test_elastic.py](tests/test_elastic.py)
- [torch_sim/io.py](torch_sim/io.py)
- [torch_sim/models/orb.py](torch_sim/models/orb.py)

</details>



This document describes the testing infrastructure and validation strategies used in torch-sim to ensure correctness, reliability, and consistency with established atomistic simulation packages. The framework emphasizes three core validation approaches: comparison with ASE calculators, physics-based property testing, and reproducibility verification.

For information about the CI/CD pipeline and workflows, see [Continuous Integration](#11.2). For model-specific implementation details, see [Model Ecosystem Overview](#6.1).

---

## Testing Infrastructure Overview

The torch-sim testing framework is organized around three key components: reusable fixtures, parameterized test factories, and multi-level validation strategies. Tests are structured to validate individual components (unit tests), integration between systems, model implementations, and complete workflows.

### Test Organization Structure

```mermaid
graph TB
    subgraph "Test Organization"
        conftest["tests/conftest.py<br/>Global Fixtures"]
        model_conftest["tests/models/conftest.py<br/>Model Test Factories"]
        
        subgraph "Test Categories"
            unit["Unit Tests<br/>transforms, constraints<br/>state operations"]
            integration["Integration Tests<br/>integrators, optimizers<br/>elastic properties"]
            model_tests["Model Tests<br/>tests/models/test_*.py"]
            workflow["Workflow Tests<br/>A2C pipeline, examples"]
        end
        
        subgraph "Test Infrastructure"
            generators["SIMSTATE_GENERATORS<br/>Bulk crystals<br/>Molecules<br/>Supercells"]
            model_fixtures["Model Fixtures<br/>lj_model<br/>mace_model<br/>orb_model"]
            factories["Test Factories<br/>make_model_calculator_consistency_test<br/>make_validate_model_outputs_test"]
        end
    end
    
    conftest --> generators
    conftest --> model_fixtures
    model_conftest --> factories
    
    generators --> unit
    generators --> integration
    generators --> model_tests
    
    model_fixtures --> model_tests
    factories --> model_tests
    
    style conftest fill:#f9f9f9,stroke:#333,stroke-width:2px
    style factories fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Sources:** [tests/conftest.py:1-151](), [tests/models/test_mace.py:1-176](), [tests/models/test_orb.py:1-82]()

---

## Test Fixtures and Generators

The testing framework provides a comprehensive set of fixtures to create consistent, reproducible test cases across different structural types and chemical systems.

### SIMSTATE_GENERATORS Registry

The `SIMSTATE_GENERATORS` dictionary in the testing module provides factory functions for creating diverse `SimState` objects. These generators are automatically converted to pytest fixtures in `conftest.py`:

```mermaid
graph LR
    subgraph "Fixture Generation Pattern"
        registry["SIMSTATE_GENERATORS<br/>dict[str, Callable]"]
        factory["_make_simstate_fixture<br/>Factory function"]
        fixtures["Generated Fixtures<br/>cu_sim_state<br/>ar_supercell_sim_state<br/>benzene_sim_state<br/>..."]
    end
    
    registry --> factory
    factory --> fixtures
    
    subgraph "Usage in Tests"
        test["Test Function"]
        fixtures --> test
    end
    
    subgraph "Generator Categories"
        bulk["SIMSTATE_BULK_GENERATORS<br/>FCC Cu, Mg, Sb<br/>Tetragonal TiO2<br/>Orthorhombic Ga"]
        molecule["SIMSTATE_MOLECULE_GENERATORS<br/>Benzene<br/>Other molecules"]
        supercell["Supercell Variants<br/>ar_supercell_sim_state<br/>cu_supercell_sim_state"]
    end
    
    registry --> bulk
    registry --> molecule
    registry --> supercell
```

**Sources:** [tests/conftest.py:13-33]()

The fixture generation pattern at [tests/conftest.py:20-32]() programmatically creates pytest fixtures from the generator registry:

```python
def _make_simstate_fixture(name: str) -> Callable[[], ts.SimState]:
    """Create a pytest fixture for a sim_state generator."""
    @pytest.fixture(name=name)
    def _fixture() -> ts.SimState:
        return SIMSTATE_GENERATORS[name](DEVICE, DTYPE)
    return _fixture

# Programmatically generate fixtures for all sim_state generators
for _name in SIMSTATE_GENERATORS:
    globals()[_name] = _make_simstate_fixture(_name)
```

**Sources:** [tests/conftest.py:20-32]()

### Structure Fixtures

Standard structure fixtures provide common test cases using ASE, Pymatgen, and Phonopy formats:

| Fixture Name | Chemical System | Structure Type | Format | Line Reference |
|--------------|-----------------|----------------|--------|----------------|
| `ar_atoms` | Argon | FCC crystal | ASE Atoms | [tests/conftest.py:49-52]() |
| `fe_atoms` | Iron | FCC crystal | ASE Atoms | [tests/conftest.py:55-58]() |
| `si_atoms` | Silicon | Diamond | ASE Atoms | [tests/conftest.py:61-64]() |
| `benzene_atoms` | C₆H₆ | Molecule | ASE Atoms | [tests/conftest.py:67-70]() |
| `si_structure` | Silicon | Diamond | Pymatgen Structure | [tests/conftest.py:73-88]() |
| `si_phonopy_atoms` | Silicon | Diamond | PhonopyAtoms | [tests/conftest.py:91-111]() |

**Sources:** [tests/conftest.py:49-111]()

### Model Fixtures

Model fixtures instantiate pre-configured force fields for testing. The pattern separates model creation from calculator creation for comparison tests:

```mermaid
graph TB
    subgraph "Model Fixture Pattern"
        model_fixture["Model Fixture<br/>ts_mace_model<br/>orbv3_direct_20_omat_model<br/>sevenn_model"]
        calculator_fixture["Calculator Fixture<br/>ase_mace_calculator<br/>orbv3_direct_20_omat_calculator<br/>sevenn_calculator"]
        
        pretrained["Pretrained Weights<br/>mace_mp, orb_v3<br/>sevennet-mf-ompa"]
    end
    
    subgraph "Usage in Tests"
        consistency["Consistency Test<br/>Compare outputs"]
        validation["Output Validation<br/>Check structure"]
    end
    
    pretrained --> model_fixture
    pretrained --> calculator_fixture
    
    model_fixture --> consistency
    model_fixture --> validation
    calculator_fixture --> consistency
    
    style pretrained fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Example: MACE model fixture pattern** from [tests/models/test_mace.py:35-56]():

```python
raw_mace_mp = mace_mp(model=MaceUrls.mace_mp_small, return_raw_model=True)

@pytest.fixture
def ase_mace_calculator() -> MACECalculator:
    dtype = str(DTYPE).removeprefix("torch.")
    return mace_mp(
        model=MaceUrls.mace_mp_small, device="cpu", default_dtype=dtype, dispersion=False
    )

@pytest.fixture
def ts_mace_model() -> MaceModel:
    return MaceModel(
        model=raw_mace_mp,
        device=DEVICE,
        dtype=DTYPE,
        compute_forces=True,
        compute_stress=True,
    )
```

**Sources:** [tests/models/test_mace.py:35-56](), [tests/models/test_orb.py:23-45](), [tests/models/test_sevennet.py:33-53]()

### Batched State Fixtures

Batched fixtures test multi-system processing capabilities:

```mermaid
graph LR
    subgraph "Batched State Creation"
        single1["ar_supercell_sim_state"]
        single2["si_sim_state"]
        
        concat["ts.concatenate_states"]
        
        double["ar_double_sim_state<br/>Same system × 2"]
        mixed["mixed_double_sim_state<br/>Different systems"]
    end
    
    single1 --> concat
    single2 --> concat
    concat --> double
    concat --> mixed
```

**Sources:** [tests/conftest.py:124-150]()

---

## Model Testing Framework

The model testing framework uses factory patterns to generate consistent, parameterized tests across different MLIP backends while isolating incompatible dependencies.

### Test Factory Pattern

Test factories generate parameterized tests that validate models against multiple structural configurations. Two primary factory functions are provided in `tests/models/conftest.py`:

```mermaid
graph TB
    subgraph "Test Factory Architecture"
        factory1["make_model_calculator_consistency_test"]
        factory2["make_validate_model_outputs_test"]
        
        params["Parameters<br/>test_name<br/>model_fixture_name<br/>calculator_fixture_name<br/>sim_state_names<br/>tolerances"]
        
        generated1["Generated Tests<br/>test_[model]_consistency"]
        generated2["Generated Tests<br/>test_validate_[model]_model_outputs"]
    end
    
    subgraph "Validation Strategies"
        ase_compare["ASE Comparison<br/>Energy, forces, stress"]
        output_check["Output Structure<br/>Shape, dtype, device"]
        tolerance["Tolerance Checks<br/>rtol, atol"]
    end
    
    params --> factory1
    params --> factory2
    factory1 --> generated1
    factory2 --> generated2
    
    generated1 --> ase_compare
    generated1 --> tolerance
    generated2 --> output_check
    
    style factory1 fill:#f9f9f9,stroke:#333,stroke-width:2px
    style factory2 fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Sources:** Referenced in [tests/models/test_mace.py:59-65](), [tests/models/test_orb.py:57-73]()

### Consistency Testing with ASE

Consistency tests compare torch-sim model outputs with ASE calculator outputs to verify correctness. The test pattern validates:

1. **Energy agreement**: Per-system total energies
2. **Force agreement**: Per-atom forces (3D vectors)
3. **Stress agreement**: Per-system stress tensors (3×3)
4. **Tolerance specifications**: Configurable `rtol` and `atol` per model

**Example: ORB model consistency test** from [tests/models/test_orb.py:57-73]():

```python
test_orb_conservative_consistency = make_model_calculator_consistency_test(
    test_name="orbv3_conservative_inf_omat",
    model_fixture_name="orbv3_conservative_inf_omat_model",
    calculator_fixture_name="orbv3_conservative_inf_omat_calculator",
    sim_state_names=tuple(SIMSTATE_GENERATORS.keys()),
    energy_rtol=5e-5,
    energy_atol=5e-5,
)
```

The factory generates parameterized tests that:
- Loop over all specified `sim_state_names`
- Convert `SimState` to ASE `Atoms` via [torch_sim/io.py:35-102]()
- Compute outputs using both model and calculator
- Assert numerical agreement within tolerances

**Sources:** [tests/models/test_orb.py:57-73](), [tests/models/test_mace.py:59-65](), [tests/models/test_sevennet.py:66-72]()

### Output Validation Tests

Output validation tests verify that models return properly structured dictionaries with correct tensor shapes and properties:

```mermaid
graph LR
    subgraph "Output Validation Checks"
        model["Model.forward"]
        output["Output Dict"]
        
        checks["Validation Checks"]
        
        energy["energy key exists<br/>shape = (n_systems,)"]
        forces["forces key exists<br/>shape = (n_atoms, 3)"]
        stress["stress key (optional)<br/>shape = (n_systems, 3, 3)"]
        dtype_check["dtype matches model.dtype"]
        device_check["device matches model.device"]
    end
    
    model --> output
    output --> checks
    checks --> energy
    checks --> forces
    checks --> stress
    checks --> dtype_check
    checks --> device_check
```

**Sources:** [tests/models/test_mace.py:104-106](), [tests/models/test_orb.py:75-81]()

### Model-Specific Test Examples

Each MLIP integration includes comprehensive tests demonstrating the complete testing pattern:

#### MACE Model Tests

**Key test coverage** from [tests/models/test_mace.py:1-176]():

| Test Name | Purpose | Line Reference |
|-----------|---------|----------------|
| `test_mace_consistency` | Compare with ASE MACECalculator | [tests/models/test_mace.py:59-65]() |
| `test_mace_dtype_working` | Verify float32/float64 support | [tests/models/test_mace.py:68-78]() |
| `test_mace_off_consistency` | MACE-OFF molecular model | [tests/models/test_mace.py:96-102]() |
| `test_mace_charge_spin` | Charge/spin handling for molecules | [tests/models/test_mace.py:124-176]() |

**Charge and spin testing** demonstrates molecular property handling at [tests/models/test_mace.py:124-176]():

```python
@pytest.mark.parametrize(
    ("charge", "spin"),
    [
        (0.0, 0.0),  # Neutral, no spin
        (1.0, 1.0),  # +1 charge, spin=1 (doublet)
        (-1.0, 0.0), # -1 charge, no spin (singlet)
        (0.0, 2.0),  # Neutral, spin=2 (triplet)
    ],
)
def test_mace_charge_spin(benzene_sim_state: ts.SimState, charge: float, spin: float) -> None:
    # Test verifies charge/spin extraction and forward pass
```

**Sources:** [tests/models/test_mace.py:1-176]()

#### ORB Model Tests

**Key test coverage** from [tests/models/test_orb.py:1-82]():

- Two pretrained model variants: `orbv3_conservative_inf_omat` and `orbv3_direct_20_omat`
- Consistency tests for both variants
- Output validation tests for both variants
- Custom tolerance settings (`energy_rtol=5e-5`)

**Sources:** [tests/models/test_orb.py:1-82]()

#### SevenNet Model Tests

**Key test coverage** from [tests/models/test_sevennet.py:1-78]():

- Uses modal-specific loading (`modal="mpa"`)
- Tests on bulk structures only (molecular structures excluded due to numerics)
- float32 precision testing

**Sources:** [tests/models/test_sevennet.py:1-78]()

#### Lennard-Jones Classical Potential Tests

Classical potential tests validate analytical implementations and physical properties:

```mermaid
graph TB
    subgraph "Lennard-Jones Test Suite"
        pair_energy["lennard_jones_pair<br/>Energy function"]
        pair_force["lennard_jones_pair_force<br/>Force function"]
        model["LennardJonesModel<br/>Wrapped implementation"]
        
        analytical["Analytical Tests"]
        numerical["Numerical Tests"]
        physical["Physical Tests"]
    end
    
    subgraph "Test Coverage"
        minimum["Minimum at r = 2^(1/6)σ"]
        well_depth["Energy = -ε at minimum"]
        scaling["Linear ε scaling"]
        repulsive["Repulsive core"]
        gradient["Force-energy consistency"]
        conservation["Force sum = 0"]
    end
    
    pair_energy --> analytical
    pair_force --> analytical
    pair_energy --> numerical
    pair_force --> numerical
    model --> physical
    
    analytical --> minimum
    analytical --> well_depth
    analytical --> scaling
    analytical --> repulsive
    numerical --> gradient
    physical --> conservation
```

**Key validation tests** from [tests/models/test_lennard_jones.py:1-138]():

| Test Name | Physical Property | Line Reference |
|-----------|-------------------|----------------|
| `test_lennard_jones_pair_minimum` | Well location at r = 2^(1/6)σ | [tests/models/test_lennard_jones.py:17-23]() |
| `test_lennard_jones_pair_energy_at_minimum` | Well depth = -ε | [tests/models/test_lennard_jones.py:26-31]() |
| `test_lennard_jones_pair_epsilon_scaling` | Linear ε dependence | [tests/models/test_lennard_jones.py:34-40]() |
| `test_lennard_jones_force_energy_consistency` | Force = -∇E | [tests/models/test_lennard_jones.py:87-97]() |
| `test_lennard_jones_model_force_conservation` | Σᵢ Fᵢ = 0 | [tests/models/test_lennard_jones.py:119-137]() |

**Sources:** [tests/models/test_lennard_jones.py:1-138]()

---

## Physics Validation

Physics-based validation tests verify that simulations obey fundamental physical principles and produce thermodynamically consistent results. These tests go beyond numerical accuracy to validate conservation laws, symmetry properties, and material properties.

### Elastic Property Calculations

The elastic tensor testing framework validates both the computational approach and the resulting material properties through multi-level checks:

```mermaid
graph TB
    subgraph "Elastic Property Testing Pipeline"
        state["Initial SimState"]
        relax["Structure Relaxation<br/>FIRE optimizer<br/>fmax < 1e-5<br/>pressure ≈ 0"]
        bravais["Bravais Type Detection<br/>get_bravais_type"]
        deform["Elementary Deformations<br/>get_elementary_deformations"]
        strain["Strain Calculation<br/>get_strain"]
        tensor["Elastic Tensor<br/>calculate_elastic_tensor"]
        moduli["Elastic Moduli<br/>calculate_elastic_moduli"]
    end
    
    subgraph "Validation Tests"
        symmetry["Symmetry Tests<br/>C_symmetric ≈ C_triclinic"]
        properties["Property Tests<br/>Bulk modulus<br/>Shear modulus"]
        strain_test["Strain Tests<br/>Zero deformation<br/>Pure normal/shear<br/>Hydrostatic"]
    end
    
    state --> relax
    relax --> bravais
    bravais --> deform
    deform --> strain
    strain --> tensor
    tensor --> moduli
    
    tensor --> symmetry
    moduli --> properties
    strain --> strain_test
    
    style relax fill:#f9f9f9,stroke:#333,stroke-width:2px
    style tensor fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Sources:** [tests/test_elastic.py:1-412]()

### Strain Tensor Validation

Strain tensor calculations are validated through a comprehensive suite of geometric tests:

**Test coverage** from [tests/test_elastic.py:28-208]():

| Test Name | Physical Scenario | Validation | Line Reference |
|-----------|-------------------|------------|----------------|
| `test_get_strain_zero_deformation` | No deformation | ε = 0 | [tests/test_elastic.py:28-34]() |
| `test_get_strain_pure_normal_strain` | Uniaxial extension | εᵢᵢ ≠ 0, others = 0 | [tests/test_elastic.py:37-70]() |
| `test_get_strain_pure_shear_strain` | Simple shear | εᵢⱼ = (uᵢⱼ + uⱼᵢ)/2 | [tests/test_elastic.py:73-108]() |
| `test_get_strain_hydrostatic_strain` | Isotropic expansion | εₓₓ = εᵧᵧ = εᵧᵧ | [tests/test_elastic.py:111-143]() |
| `test_get_strain_symmetry_property` | Asymmetric deformation | ε = (u + uᵀ)/2 | [tests/test_elastic.py:146-208]() |

The **symmetric strain tensor calculation** is explicitly validated at [tests/test_elastic.py:84-88]():

```python
# For shear deformation, the displacement gradient u will have:
# u[1, 2] = shear_magnitude, but the symmetric strain is (u + u^T)/2
# So εyz = (u[1,2] + u[2,1])/2 = (shear_magnitude + 0)/2 = shear_magnitude/2
expected_strain[3] = shear_magnitude / 2  # εyz = symmetric shear strain
```

**Sources:** [tests/test_elastic.py:28-208]()

### Crystal Symmetry Testing

Elastic tensors are validated against known symmetries for different Bravais lattice types:

```mermaid
graph TB
    subgraph "Crystal System Test Matrix"
        cubic["Cubic<br/>Cu FCC<br/>3 independent constants"]
        hexagonal["Hexagonal<br/>Mg HCP<br/>5 independent constants"]
        trigonal["Trigonal<br/>Sb<br/>6 independent constants"]
        tetragonal["Tetragonal<br/>TiO₂<br/>6 independent constants"]
        orthorhombic["Orthorhombic<br/>Ga<br/>9 independent constants"]
        monoclinic["Monoclinic<br/>NiTi<br/>13 independent constants"]
    end
    
    subgraph "Validation Approach"
        relax_structure["Relax Structure<br/>FIRE + cell filter"]
        verify_bravais["Verify Bravais Type<br/>Pre and post relaxation"]
        calc_symmetric["Calculate C<br/>With symmetry constraints"]
        calc_triclinic["Calculate C<br/>No constraints"]
        compare["Assert<br/>C_symmetric ≈ C_triclinic"]
    end
    
    cubic --> relax_structure
    hexagonal --> relax_structure
    trigonal --> relax_structure
    tetragonal --> relax_structure
    orthorhombic --> relax_structure
    monoclinic --> relax_structure
    
    relax_structure --> verify_bravais
    verify_bravais --> calc_symmetric
    verify_bravais --> calc_triclinic
    calc_symmetric --> compare
    calc_triclinic --> compare
```

**Parameterized crystal system tests** from [tests/test_elastic.py:271-353]():

```python
@pytest.mark.parametrize(
    ("sim_state_name", "expected_bravais_type", "atol"),
    [
        ("cu_sim_state", BravaisType.cubic, 2e-1),
        ("mg_sim_state", BravaisType.hexagonal, 5e-1),
        ("sb_sim_state", BravaisType.trigonal, 5e-1),
        ("tio2_sim_state", BravaisType.tetragonal, 5e-1),
        ("ga_sim_state", BravaisType.orthorhombic, 5e-1),
        ("niti_sim_state", BravaisType.monoclinic, 5e-1),
    ],
)
def test_elastic_tensor_symmetries(...)
```

**Sources:** [tests/test_elastic.py:271-353]()

### Material Property Validation

The copper elastic properties test validates calculated moduli against expected values:

**Test implementation** from [tests/test_elastic.py:355-411]():

```python
def test_copper_elastic_properties(mace_model: MaceModel, cu_sim_state: ts.SimState):
    # Relax structure
    # Calculate elastic tensor
    # Calculate elastic moduli
    
    expected_bulk_modulus = 144.12  # GPa
    expected_shear_modulus = 43.11  # GPa
    
    assert abs(bulk_modulus - expected_bulk_modulus) < 1e-2 * expected_bulk_modulus
    assert abs(shear_modulus - expected_shear_modulus) < 1e-2 * expected_shear_modulus
```

The test validates both the full elastic tensor (6×6 matrix in Voigt notation) and derived scalar properties.

**Sources:** [tests/test_elastic.py:355-411]()

---

## I/O and Format Conversion Testing

Format conversion functions are critical for interoperability with ASE, Pymatgen, and Phonopy. Testing ensures bidirectional conversions preserve all relevant information:

### Conversion Test Coverage

```mermaid
graph LR
    subgraph "Bidirectional Conversion Testing"
        ase["ASE Atoms"]
        pymatgen["Pymatgen Structure"]
        phonopy["PhonopyAtoms"]
        simstate["SimState"]
        
        ase_to["atoms_to_state"]
        ase_from["state_to_atoms"]
        pmg_to["structures_to_state"]
        pmg_from["state_to_structures"]
        phon_to["phonopy_to_state"]
        phon_from["state_to_phonopy"]
    end
    
    ase --> ase_to
    ase_to --> simstate
    simstate --> ase_from
    ase_from --> ase
    
    pymatgen --> pmg_to
    pmg_to --> simstate
    simstate --> pmg_from
    pmg_from --> pymatgen
    
    phonopy --> phon_to
    phon_to --> simstate
    simstate --> phon_from
    phon_from --> phonopy
    
    subgraph "Properties Preserved"
        positions["Positions (Cartesian)"]
        cell["Cell vectors"]
        masses["Atomic masses"]
        numbers["Atomic numbers"]
        pbc["Periodic boundaries"]
        charge_spin["Charge and spin"]
        system_idx["System indices (batching)"]
    end
    
    simstate --> positions
    simstate --> cell
    simstate --> masses
    simstate --> numbers
    simstate --> pbc
    simstate --> charge_spin
    simstate --> system_idx
```

**Key conversion functions** from [torch_sim/io.py:1-487]():

| Function | Direction | Key Features | Line Reference |
|----------|-----------|--------------|----------------|
| `atoms_to_state` | ASE → SimState | Handles single/list, charge/spin | [torch_sim/io.py:243-317]() |
| `state_to_atoms` | SimState → ASE | Preserves charge/spin in info | [torch_sim/io.py:35-102]() |
| `structures_to_state` | Pymatgen → SimState | Validates consistent PBC | [torch_sim/io.py:325-398]() |
| `state_to_structures` | SimState → Pymatgen | Cartesian coordinates | [torch_sim/io.py:110-173]() |
| `phonopy_to_state` | Phonopy → SimState | Assumes PBC=True | [torch_sim/io.py:406-486]() |
| `state_to_phonopy` | SimState → Phonopy | Crystal structures only | [torch_sim/io.py:186-235]() |

**Cell matrix convention**: torch-sim uses column vectors for cell basis, requiring transpose operations during conversion. From [torch_sim/io.py:287-288]():

```python
cell = torch.tensor(  # Transpose cell from ASE convention to TorchSim convention
    np.stack([at.cell.array.T for at in atoms_list]), dtype=dtype, device=device
)
```

**Sources:** [torch_sim/io.py:1-487]()

### Charge and Spin Preservation

Molecular systems with charge and spin states require careful handling during conversions:

**Charge/spin storage** in ASE atoms.info from [torch_sim/io.py:94-98]():

```python
# Preserve charge and spin in atoms.info (as integers for FairChem compatibility)
if charge is not None:
    atoms.info["charge"] = int(charge[sys_idx].item())
if spin is not None:
    atoms.info["spin"] = int(spin[sys_idx].item())
```

**Extraction during conversion** at [torch_sim/io.py:301-306]():

```python
charge = torch.tensor(
    [at.info.get("charge", 0.0) for at in atoms_list], dtype=dtype, device=device
)
spin = torch.tensor(
    [at.info.get("spin", 0.0) for at in atoms_list], dtype=dtype, device=device
)
```

**Sources:** [torch_sim/io.py:94-98](), [torch_sim/io.py:301-306]()

---

## Continuous Integration Strategy

The CI workflow implements a three-tier isolation strategy to handle dependency conflicts while maintaining comprehensive test coverage. For full CI/CD details, see [Continuous Integration](#11.2).

### Test Matrix Architecture

```mermaid
graph TB
    subgraph "CI Workflow Structure"
        trigger["Push/PR Event"]
        
        core_job["test-core Job<br/>Broad compatibility matrix"]
        model_job["test-model Job<br/>Isolated MLIP testing"]
        examples_job["test-examples Job<br/>Documentation validation"]
        
        gate["all-required-pass<br/>Merge gatekeeper"]
    end
    
    subgraph "Core Test Matrix"
        os["2 Operating Systems<br/>ubuntu-latest<br/>macos-latest"]
        python["2 Python Versions<br/>3.10, 3.11"]
        resolution["2 Dependency Sets<br/>min, max"]
        total["= 8 Combinations"]
    end
    
    subgraph "Model Test Isolation"
        mace_test["MACE Tests<br/>torch-sim[mace]"]
        fairchem_test["FairChem Tests<br/>torch-sim[fairchem]"]
        orb_test["ORB Tests<br/>torch-sim[orb]"]
        sevenn_test["SevenNet Tests<br/>torch-sim[sevenn]"]
        other_tests["Other MLIPs<br/>Isolated environments"]
    end
    
    trigger --> core_job
    trigger --> model_job
    trigger --> examples_job
    
    core_job --> os
    os --> python
    python --> resolution
    resolution --> total
    
    model_job --> mace_test
    model_job --> fairchem_test
    model_job --> orb_test
    model_job --> sevenn_test
    model_job --> other_tests
    
    core_job --> gate
    examples_job --> gate
    
    style gate fill:#f9f9f9,stroke:#333,stroke-width:2px
```

**Key isolation features**:
- Model tests run in separate jobs to avoid `e3nn` version conflicts
- Core tests validate framework without MLIP dependencies
- Examples run dynamically discovered from `examples/` directory

**Sources:** Referenced in architecture diagram "Diagram 5: Testing and Quality Assurance Infrastructure"

---

## Test Execution and Coverage

### Running Tests Locally

Tests can be executed at different granularities:

```bash
# Run all tests
pytest

# Run core tests only (no MLIP models)
pytest tests/ --ignore=tests/models/

# Run specific model tests
pytest tests/models/test_mace.py
pytest tests/models/test_orb.py

# Run with specific markers
pytest -m "not slow"
pytest -k "consistency"

# Run with coverage
pytest --cov=torch_sim --cov-report=html
```

### Skip Patterns

Model tests automatically skip when dependencies are unavailable using conditional imports:

```python
try:
    from orb_models.forcefield import pretrained
    from torch_sim.models.orb import OrbModel
except ImportError:
    pytest.skip(
        f"ORB not installed: {traceback.format_exc()}", 
        allow_module_level=True
    )
```

**Sources:** [tests/models/test_orb.py:13-20](), [tests/models/test_mace.py:16-23](), [tests/models/test_sevennet.py:14-25]()

---

## Best Practices for Adding Tests

When contributing new functionality, follow these testing patterns:

### For New Models

1. **Create model fixtures** in `tests/models/test_[model].py`:
   - Model wrapper fixture
   - ASE calculator fixture (if available)
   - Use pretrained weights when possible

2. **Generate consistency tests** using factories:
   ```python
   test_[model]_consistency = make_model_calculator_consistency_test(
       test_name="[model]",
       model_fixture_name="[model]_model",
       calculator_fixture_name="[model]_calculator",
       sim_state_names=tuple(SIMSTATE_GENERATORS.keys()),
   )
   ```

3. **Add output validation**:
   ```python
   test_validate_[model]_model_outputs = make_validate_model_outputs_test(
       model_fixture_name="[model]_model",
   )
   ```

4. **Update CI configuration** to isolate incompatible dependencies

### For New Physics Validation

1. **Create analytical test cases** with known solutions
2. **Implement numerical gradient checks** for force-energy consistency
3. **Test conservation laws** (energy, momentum, etc.)
4. **Validate against literature values** for material properties

### For New Transformations

1. **Test identity operations**: f(f⁻¹(x)) = x
2. **Test edge cases**: empty inputs, single atoms, large systems
3. **Test consistency** with ASE/Pymatgen implementations
4. **Test batching behavior** with multi-system inputs

**Sources:** Testing patterns observed throughout [tests/models/test_*.py]() files

---