# Data Structures

<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [mlatom/data.py](mlatom/data.py)

</details>



## Purpose and Scope

This page documents the core data structures in MLatom that represent atoms, molecules, molecular databases, and trajectories. These classes form the foundation for all molecular data handling, from individual atomic properties to collections of molecules used in machine learning workflows and molecular dynamics simulations.

For information about the model framework that operates on these data structures, see [Model Framework](#2.2). For details about molecular simulations that generate trajectory data, see [Core Simulations](#5.1) and [Molecular Dynamics](#5.2).

## Core Atomic and Entry Structures

### Atom Class

The `atom` class [mlatom/data.py:191-294]() represents individual atoms with their fundamental properties:

```mermaid
classDiagram
    class atom {
        +int atomic_number
        +str element_symbol
        +float nuclear_charge
        +float nuclear_mass
        +ndarray xyz_coordinates
        +property multiplicity
        +property H0
        +property nuclear_spin
        +copy() atom
    }
```

**Key Properties:**
- `atomic_number`: Defines the element type
- `element_symbol`: String representation (e.g., 'H', 'C', 'O')
- `xyz_coordinates`: 3D position in Angström units
- `nuclear_mass`: Atomic mass, with automatic isotope lookup

The class uses property decorators to provide multiple ways to access the same atomic information and automatically converts between atomic number, element symbol, and nuclear charge [mlatom/data.py:222-279]().

**Sources:** [mlatom/data.py:191-294]()

### Entry Class

The `entry` class [mlatom/data.py:23-37]() provides a basic data container for machine learning applications:

```mermaid
classDiagram
    class entry {
        +str id
        +ndarray x
        +float|ndarray y
        +__add__(obj)
        +__str__()
    }
```

Each entry contains input features (`x`) and target values (`y`) with a unique identifier. Entries can be combined using the `+` operator to create `ml_database` objects.

**Sources:** [mlatom/data.py:23-37]()

## Molecular Structures

### Molecule Class

The `molecule` class [mlatom/data.py:329-1320]() is the central structure representing complete molecular systems:

```mermaid
classDiagram
    class molecule {
        +str id
        +int charge
        +int multiplicity
        +List[atom] atoms
        +ndarray pbc
        +ndarray cell
        +List electronic_states
        +property atomic_numbers
        +property element_symbols
        +property xyz_coordinates
        +property energy_gradients
        +property kinetic_energy
        +from_xyz_file() molecule
        +from_numpy() molecule
        +from_smiles_string() molecule
        +copy() molecule
        +bond_length(a1, a2) float
        +bond_angle(a1, a2, a3) float
        +proliferate() molecule
    }
    molecule --> atom : contains
```

**Key Features:**
- **Atomic Structure**: Contains a list of `atom` objects
- **Electronic Properties**: Charge, multiplicity, electronic states
- **Periodic Boundary Conditions**: Support for periodic systems via `pbc` and `cell`
- **Multiple Input Formats**: Can be created from XYZ files, NumPy arrays, or SMILES strings
- **Geometric Analysis**: Built-in methods for bond lengths, angles, and dihedral angles

**Data Loading Methods:**
- `from_xyz_file()`: Standard XYZ format with support for COLUMBUS, NEWTON-X, and Turbomole formats
- `from_numpy()`: Direct creation from coordinate and species arrays
- `from_smiles_string()`: Generation from SMILES with 3D optimization

**Sources:** [mlatom/data.py:329-1320]()

## Database and Collection Structures

### Molecular Database

The `molecular_database` class [mlatom/data.py:1364-2239]() manages collections of molecules:

```mermaid
classDiagram
    class molecular_database {
        +List[molecule] molecules
        +property size
        +property atomic_numbers
        +property xyz_coordinates
        +property energy
        +from_xyz_file() molecular_database
        +from_h5_file() molecular_database
        +read_from_numpy() molecular_database
        +add_scalar_properties()
        +add_xyz_derivative_properties()
        +split() List[molecular_database]
        +filter_by_property() molecular_database
        +groupby() List[molecular_database]
    }
    molecular_database --> molecule : contains
```

**Key Capabilities:**
- **Batch Operations**: Apply properties to all molecules simultaneously
- **Data Splitting**: Random or user-defined splits for training/validation
- **File I/O**: Support for XYZ, HDF5, JSON, and NPZ formats
- **Property Management**: Add scalar properties, gradients, and vectorial properties
- **Filtering and Grouping**: Select subsets based on property values

**Sources:** [mlatom/data.py:1364-2239]()

### ML Database

The `ml_database` class [mlatom/data.py:38-177]() is designed specifically for machine learning workflows:

```mermaid
classDiagram
    class ml_database {
        +List[entry] entries
        +property x
        +property y
        +property size
        +from_x_file() ml_database
        +read_from_y_file()
        +get_x() ndarray
        +get_property() ndarray
        +split() List[ml_database]
    }
    ml_database --> entry : contains
```

This class provides specialized methods for handling feature matrices (`x`) and target vectors (`y`) common in machine learning applications.

**Sources:** [mlatom/data.py:38-177]()

## Trajectory Structures

### Molecular Trajectory

For molecular dynamics and optimization tasks, MLatom provides trajectory data structures:

```mermaid
classDiagram
    class molecular_trajectory {
        +List[molecular_trajectory_step] steps
        +dump(filename, format)
        +load(filename, format)
        +get_xyz_string() str
        +to_database() molecular_database
        +view()
    }
    class molecular_trajectory_step {
        +int step
        +molecule molecule
        +float time
        +ndarray state_coefficients
        +float random_number
        +List hopping_probabilities
    }
    molecular_trajectory --> molecular_trajectory_step : contains
    molecular_trajectory_step --> molecule : contains
```

**Supported Formats:**
- **H5MD**: High-performance binary format for large trajectories
- **JSON**: Human-readable format for smaller datasets
- **Plain Text**: Multiple files (XYZ, gradients, energies, etc.)

**Sources:** [mlatom/data.py:2561-2923]()

## Chemical Reaction Structures

MLatom provides specialized structures for handling chemical reactions:

```mermaid
classDiagram
    class reaction {
        +List[reaction_step] steps
        +calculate_relative_energies()
    }
    class reaction_step {
        +List coefficients
        +List[molecule] molecules
        +str chemical_label
        +absolute_energy() float
        +copy() reaction_step
    }
    class reactions_database {
        +List[reaction] reactions
        +dump(filename, format)
        +load(filename, format)
        +groupby() List
    }
    reaction --> reaction_step : contains
    reaction_step --> molecule : contains
    reactions_database --> reaction : contains
```

**Sources:** [mlatom/data.py:2291-2436]()

## Data Flow and Relationships

The following diagram illustrates how data flows through MLatom's core structures:

```mermaid
flowchart TD
    A["Raw Input Files"] --> B["File Parsers"]
    B --> C["atom objects"]
    B --> D["entry objects"]
    
    C --> E["molecule objects"]
    D --> F["ml_database"]
    
    E --> G["molecular_database"]
    E --> H["molecular_trajectory_step"]
    
    H --> I["molecular_trajectory"]
    E --> J["reaction_step"]
    J --> K["reaction"]
    K --> L["reactions_database"]
    
    G --> M["ML Models & Simulations"]
    F --> M
    I --> M
    L --> M
    
    subgraph "File Formats"
        N["XYZ Files"]
        O["HDF5 Files"] 
        P["SMILES"]
        Q["JSON/NPZ"]
    end
    
    N --> B
    O --> B
    P --> B
    Q --> B
```

**Sources:** [mlatom/data.py:296-318](), [mlatom/data.py:436-564](), [mlatom/data.py:1405-1463]()

## Isotope and Atomic Data

MLatom includes comprehensive isotope data for accurate mass calculations:

```mermaid
classDiagram
    class isotope {
        +int nuclear_charge
        +float relative_isotopic_mass
        +float isotope_abundance
        +float nuclear_spin
        +float H0
        +int multiplicity
    }
    class isotopes {
        +List[isotope] isotopes
        +get_most_abundant_with_given_nuclear_charge() isotope
        +get_most_similar_isotope_given_nuclear_charge_and_mass() isotope
    }
    isotopes --> isotope : contains
```

The isotope database contains data for elements 1-118 with nuclear masses, abundances, and nuclear spin information sourced from NIST [mlatom/data.py:3269-3665]().

**Sources:** [mlatom/data.py:3269-3665]()

## Utility and I/O Classes

### HDF5 Support

MLatom provides specialized HDF5 handling through several classes:

- `h5md`: H5MD format support for trajectory data [mlatom/data.py:2931-3080]()
- `h5dataloader`: Efficient loading of large HDF5 datasets [mlatom/data.py:3081-3130]()

### Data Conversion

The module includes utilities for converting between different data representations:
- `class_instance_to_dict()`: Serialization to dictionary format [mlatom/data.py:2439-2464]()
- `dict_to_*_class_instance()`: Deserialization from dictionaries [mlatom/data.py:2466-2559]()

**Sources:** [mlatom/data.py:2931-3130](), [mlatom/data.py:2439-2559]()

---