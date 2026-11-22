# Nonbonded Energy

**Nonbonded Energy** is a Python 3 tool for calculating short-range non-bonded interaction energies from molecular-dynamics trajectories.

It evaluates Lennard–Jones short-range (LJ-SR) and PME/Ewald real-space Coulomb short-range (Coulomb-SR) interactions between two user-defined [MDAnalysis](https://www.mdanalysis.org/) atom selections. Force-field parameters are read from GROMACS topology files, so the analysis can be run on an existing trajectory without a new `gmx mdrun -rerun` calculation.

> [!IMPORTANT]
> This program is not a general replacement for the GROMACS energy engine. It calculates only the LJ-SR and real-space Coulomb-SR terms described below.

## Features

- Analyze existing MD trajectories directly.
- Define two atom groups with MDAnalysis selection syntax.
- Calculate Lennard–Jones short-range and PME/Ewald real-space Coulomb short-range energies.
- Read GROMACS topology files and included ITP files.
- Support GROMACS combination rules 1, 2, and 3, and explicit `[ nonbond_params ]` entries.
- Resolve topology includes automatically, with an optional force-field directory fallback.
- Apply periodic boundary conditions when calculating distances.
- Write per-frame LJ-SR, Coulomb-SR, and summed energies.
- Optionally report the atom pairs with the largest non-bonded contributions.

## Theory and implementation

### Lennard–Jones short-range energy

For force fields using sigma and epsilon parameters, the interaction between atoms $i$ and $j$ is

$$
V_{\mathrm{LJ}}(r_{ij}) = 4\varepsilon_{ij} \left[\left(\frac{\sigma_{ij}}{r_{ij}}\right)^{12} - \left(\frac{\sigma_{ij}}{r_{ij}}\right)^6\right].
$$

For force fields using $C_6$ and $C_{12}$ parameters, the equivalent expression is

$$
V_{\mathrm{LJ}}(r_{ij}) = \frac{C_{12,ij}}{r_{ij}^{12}} - \frac{C_{6,ij}}{r_{ij}^6}.
$$

The program reads the GROMACS `[ defaults ]`, `[ atomtypes ]`, and `[ nonbond_params ]` topology sections. Explicit parameters in `[ nonbond_params ]` take precedence over parameters generated from individual atom types.

### GROMACS combination rules

The topology parser supports these non-bonded combination rules:

**Rule 1 — geometric combination of $C_6$ and $C_{12}$:**

$$
C_{6,ij} = \sqrt{C_{6,i} C_{6,j}}, \qquad C_{12,ij} = \sqrt{C_{12,i} C_{12,j}}.
$$

**Rule 2 — arithmetic sigma and geometric epsilon:**

$$
\sigma_{ij} = \frac{\sigma_i + \sigma_j}{2}, \qquad \varepsilon_{ij} = \sqrt{\varepsilon_i \varepsilon_j}.
$$

**Rule 3 — geometric sigma and geometric epsilon:**

$$
\sigma_{ij} = \sqrt{\sigma_i \sigma_j}, \qquad \varepsilon_{ij} = \sqrt{\varepsilon_i \varepsilon_j}.
$$

### Coulomb short-range energy

For PME/Ewald electrostatics, the real-space contribution is

$$
V_{\mathrm{Coul,SR}}(r_{ij}) = k_e q_i q_j \frac{\mathrm{erfc}(\beta r_{ij})}{r_{ij}}.
$$

Here, $q_i$ and $q_j$ are atomic partial charges, $r_{ij}$ is the interatomic distance in nm, and

$$
k_e = 138.935456\;\mathrm{kJ\,mol^{-1}\,nm\,e^{-2}}.
$$

The Ewald splitting coefficient $\beta$ is determined from the Coulomb cutoff $r_c$ and the relative Ewald tolerance by solving

$$
\mathrm{erfc}(\beta r_c) = \epsilon_{\mathrm{tol}}.
$$

Here, $\epsilon_{\mathrm{tol}}$ is the value of the `--ewald-rtol` command-line option.

Defaults are `rcoulomb = 1.2 nm` and `ewald-rtol = 1e-5`; both can be changed from the command line.

### Reported energy

For each trajectory frame, `Total` is calculated as

$$
E_{\mathrm{NB,SR}} = E_{\mathrm{LJ,SR}} + E_{\mathrm{Coul,SR}}.
$$

Only interactions between atoms in the two user-defined selections are included. `Total` is the sum of the two short-range terms implemented here; it is **not** the total potential energy of the molecular system.

## Requirements

- Python 3
- MDAnalysis
- NumPy

The exact tested package versions can be specified in the included `environment.yml` file.

## Installation

Clone the repository:

```bash
git clone https://github.com/jessierich22/Nonbonded-Energy.git
cd Nonbonded-Energy
```

Create and activate the Conda environment:

```bash
conda env create -f environment.yml
conda activate nonbonded-energy
```

## Usage

View all command-line options:

```bash
python3 nb_energy.py --help
```

General usage:

```bash
python3 nb_energy.py \
  -s system.tpr \
  -f trajectory.xtc \
  -p topol.top \
  --sel1 "SELECTION_1" \
  --sel2 "SELECTION_2" \
  -o energy.xvg
```

### Main arguments

| Argument | Description | Default |
|---|---|---|
| `-s`, `--structure` | GROMACS TPR file | Required |
| `-f`, `--trajectory` | MD trajectory (`XTC` or `TRR`) | Required |
| `-p`, `--topology` | GROMACS topology, such as `topol.top` | Required |
| `--sel1` | First MDAnalysis atom selection | Required |
| `--sel2` | Second MDAnalysis atom selection | Required |
| `--ff-dir` | Optional directory for unresolved topology includes | None |
| `--rcoulomb` | Coulomb cutoff in nm | `1.2` |
| `--rvdw` | Lennard–Jones cutoff in nm | `1.2` |
| `--ewald-rtol` | Ewald relative tolerance | `1e-5` |
| `--top-pairs` | Number of atom pairs with the largest absolute contribution to report per frame | `0` |
| `-o`, `--output` | Output XVG file | `energy.xvg` |

## Example

For a protein–nanoparticle interaction:

```bash
python3 nb_energy.py \
  -s system.tpr \
  -f trajectory.xtc \
  -p topol.top \
  --sel1 "protein and not resname RES" \
  --sel2 "resname RES and resid 1" \
  --rcoulomb 1.2 \
  --rvdw 1.2 \
  --ewald-rtol 1e-5 \
  -o protein_np_energy.xvg
```

Selections can represent any groups supported by the MDAnalysis selection language. For example, a protein–ligand interaction can use:

```text
--sel1 "protein"
--sel2 "resname LIG"
```

## Force-field directory

GROMACS topologies frequently contain recursive `#include` directives. Nonbonded Energy first attempts to resolve each include relative to the TOP or ITP file that contains it.

For example:

```text
simulation/
├── topol.top
├── Protein.itp
└── charmm36-jul2022.ff/
    ├── forcefield.itp
    ├── ffnonbonded.itp
    └── ...
```

A topology containing `#include "charmm36-jul2022.ff/forcefield.itp"` can normally be processed without an additional force-field path. If the force-field directory is stored elsewhere, use `--ff-dir`:

```bash
python3 nb_energy.py \
  -s system.tpr \
  -f trajectory.xtc \
  -p topol.top \
  --ff-dir /path/to/charmm36-jul2022.ff \
  --sel1 "protein" \
  --sel2 "resname LIG" \
  -o energy.xvg
```

`--ff-dir` is an optional fallback and is not restricted to a hard-coded local path.

## Identifying dominant atom pairs

Use `--top-pairs` to report the atom pairs with the largest absolute non-bonded contributions in each frame:

```bash
python3 nb_energy.py \
  -s system.tpr \
  -f trajectory.xtc \
  -p topol.top \
  --sel1 "protein" \
  --sel2 "resname LIG" \
  --top-pairs 10 \
  -o energy.xvg
```

For each analyzed frame, the report includes atom indices, residue names and IDs, atom names and types, distance, LJ contribution, Coulomb contribution, and the summed contribution. This can help identify specific interactions responsible for unusually large attractive or repulsive contributions.

## Output

The main output is an XVG-compatible text file. Its header contains the selections and calculation parameters, followed by columns for time, LJ-SR, Coulomb-SR, and Total. For example:

```text
# Nonbonded interaction energy
# Selection A: protein
# Selection B: resname LIG
# rvdw: 1.2 nm
# rcoulomb: 1.2 nm
# electrostatics: PME/Ewald real-space erfc(beta*r)/r
# ewald-rtol: 1e-05
# beta: ...
# time(ps) LJ-SR(kJ/mol) Coulomb-SR(kJ/mol) Total(kJ/mol)
```

The file can be plotted directly or processed with scientific Python tools and compatible plotting programs.

## Periodic boundary conditions

Candidate atom pairs are identified with MDAnalysis `capped_distance`. The box dimensions stored for each trajectory frame are passed to the distance calculation, so minimum-image distances are evaluated under periodic boundary conditions. Ensure the trajectory contains the appropriate box information.

## Units

| Quantity | Unit |
|---|---|
| Interatomic distance | nm |
| `rvdw` and `rcoulomb` | nm |
| Energy | kJ/mol |
| Atomic charge | Elementary charge ($e$) |
| Trajectory time | ps |
| Ewald coefficient $\beta$ | nm$^{-1}$ |

MDAnalysis provides coordinates internally in Å; the program converts them to nm before calculating energies.

## Topology handling

The program recursively reads GROMACS topology includes and extracts the parameters required for the implemented calculations. It currently uses:

```text
[ defaults ]
[ atomtypes ]
[ nonbond_params ]
```

Atomic charges and atom types are obtained from the GROMACS TPR through MDAnalysis. Missing position-restraint includes whose filenames begin with `posre` are ignored because they are not needed for the calculation. Other unresolved includes generate a warning and should be inspected.

## Scope and limitations

Nonbonded Energy calculates selected short-range non-bonded interactions between two atom selections:

- Lennard–Jones short-range interactions;
- PME/Ewald real-space Coulomb short-range interactions;
- the sum of those two contributions.

It is not a general replacement for the GROMACS energy engine or `gmx mdrun -rerun`. In particular, it does not calculate the complete potential energy, bonded terms, reciprocal-space PME contributions, or every correction and specialized interaction supported by GROMACS. Interpret results only as the interaction-energy terms implemented by this program.

## Reproducibility

For reproducible calculations, report the software version or release, topology and trajectory files/formats, MDAnalysis selections for `SEL1` and `SEL2`, `rvdw`, `rcoulomb`, `ewald-rtol`, and the force field used for the simulation. Use the same topology and force-field parameters as the molecular-dynamics simulation.

## Repository structure

```text
Nonbonded-Energy/
├── nb_energy.py
├── README.md
├── environment.yml
├── CITATION.cff
├── LICENSE
└── .gitignore
```

## Citation

If you use Nonbonded Energy in your research, cite the software repository. Citation metadata is provided in `CITATION.cff`. A versioned DOI can also be assigned to stable releases through Zenodo.

## Author

**Jéssica Cristiane Magalhães Ierich**  
Postdoctoral Researcher  
Federal University of São Carlos (UFSCar), Brazil

**ORCID:** [0000-0002-7447-9566](https://orcid.org/0000-0002-7447-9566)  
**GitHub:** [jessierich22](https://github.com/jessierich22)  
**Email:** <jessica.ierich@gmail.com>

## License

This project is distributed under the MIT License. See `LICENSE` for details.

## Acknowledgments

This software uses MDAnalysis for molecular-dynamics trajectory handling and distance calculations. The implemented non-bonded expressions and topology conventions follow the GROMACS molecular-simulation framework. Consult the official GROMACS documentation for the definitions and conventions associated with the force field and simulation settings used in your system.
