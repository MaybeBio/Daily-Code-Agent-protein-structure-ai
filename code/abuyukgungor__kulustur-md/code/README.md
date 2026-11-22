# MD Analysis & Free Energy Landscape (FEL) Automation Suite

This suite is an all-in-one automation tool designed to analyze Molecular Dynamics (MD) simulation trajectories, calculate various structural parameters (RMSD, Rg, SASA, Hydrogen Bonds, DSSP, Dihedral, and Distance) using `cpptraj`, and automatically plot 1D, 2D, or 3D Free Energy Landscapes (FEL).

---

## Features

- **Multi-Dimensional FEL Plotting:**
  - **1D:** matplotlib-based line plot ($\Delta G$ vs Parameter).
  - **2D:** matplotlib-based contour plot (with custom energy level contour lines).
  - **3D:** Plotly-based interactive, rotatable, and zoomable 3D HTML scatter plot.
- **FEL Equilibration & Convergence Check:** Splits aligned trajectories into $B$ equal chronological blocks (default `2`, configurable to `3, 4, 5, ...`) over a shared bin grid, performs Boltzmann-weighted zero-point block alignment to suppress single-bin peak noise, computes Boltzmann-weighted block standard error ($\text{wSE}(\Delta G)$) and block spread ($\text{wRMSD}(\sigma_{\text{block}})$), unweighted $\text{RMSD}$/mean of $\sigma_{\text{block}}$, all-block bin & probability-mass overlap %, and normalized Jensen–Shannon divergence ($D_{\text{JS}}/\ln B$), and outputs comparative 1D/2D plots (`*_fel_equilibration.png`) and convergence reports (`*_fel_equilibration.log`; for 3D runs, the figure displays the 2D projection alongside the exact 3D convergence metrics).
- **Non-interactive Batch Mode:** Supports execution via command-line arguments and flags, facilitating seamless integration with HPC Slurm schedulers.
- **Discrete Binning for Integer Datasets:** Automatically centers bin boundaries to half-integers for variables like Hydrogen Bond counts or secondary structure counts to prevent gaps or NaN grid artifacts in contour maps.
- **Secondary Structure (DSSP) Analysis:** Tracks secondary structure timeline (`secstruct_output.dat` integer counts and `dssp_total_frac.dat` per-type fractions) and generates a 2D timeline residue heatmap (`dssp_heatmap.png` inside your output directory) if pandas is available.
- **PCA Mode Displacement & Explained Variance:** Generates per-atom Cartesian displacement tables (`mode{i}.out` inside the output directory via `runanalysis modes displ`) along the major eigenvectors (controlled by `pca_modes_visualize`), computes per-mode explained/cumulative variance percentages (`pca_eigenvalues.dat`, also logged per selected PC), and saves the PCA average structure as both high-precision `avg_pca.rst7` (used internally for covariance/projection alignment) and `avg_pca.pdb` (for visualization); `vect.out` can also be used with `cpptraj` `modes trajout` or NMWiz for trajectory/arrow visualization in PyMOL/VMD.
- **Centralized Parameter File (`parameters.in`):** Manage all analysis masks, temperature settings, axis labels, and colormaps from a single file.
- **Performance Caching:** Queries `cpptraj` (`resinfo @CA` with solvent/ion/lipid fallback) for the C-terminal residue index only once and caches it for all active mask auto-resolutions, speeding up initialization.
- **Clean Output Architecture:** Keeps intermediate `.in` input templates and `.log` logs in the output directory and selectively cleans only files belonging to the variables being recalculated at the start of each run.

---

## Installation

### 1. System Prerequisites
The backend uses **`cpptraj`** (provided by AmberTools) for calculations. Ensure `cpptraj` is installed and added to your system's `PATH`.

### 2. Python Dependencies
Install the required Python packages using:
```bash
pip install -r requirements.txt
```

---

## Configuration (`parameters.in`)

All defaults are loaded from the **`parameters.in`** file in the project directory. Key settings include:

| Parameter | Description | Default Value |
| :--- | :--- | :--- |
| `topology` | Path to the default topology file (prmtop/top) | `h2h3mono.top` |
| `trajectory` | Input file containing trajectory paths | `traj.in` |
| `trajectory_type` | Trajectory parsing mode: `md`, `remd`, or `mix` | `md` |
| `output_dir` | Default directory to save output files and plots | `kulustur_folder` |
| `dimension` | Default FEL dimension (1, 2, or 3) | `2` |
| `temperature` | Temperature in Kelvin used for FEL calculation and `remdtrajtemp` | `310.0` |
| `kB` | Boltzmann constant (e.g. `0.001987` for kcal/mol·K, `0.008314` for kJ/mol·K) | `0.001987` |
| `energy_unit` *(optional)* | Energy unit label override (`kcal/mol` or `kJ/mol`; auto-inferred from `kB` if omitted) | Auto |
| `autoimage` | Run `cpptraj` `autoimage` after loading trajectories (recommended for wrapped multi-chain systems) | `true` |
| `energy_threshold_3d` | Maximum energy cutoff shown in 3D plots | `auto` (Dynamic estimation) |
| `bins_1d`, `bins_2d`, `bins_3d` | Histogram bin counts for 1D, 2D (also used in `export`), and 3D FELs | `50`, `50`, `30` |
| `plot_format_3d` | Output format for 3D FEL plots (`html`, `png`, or `both`) | `html` |
| `fel_equilibration_check` | Also run block-based FEL equilibration check when executing `fel` mode | `false` |
| `fel_equilibration_blocks` | Number of equal chronological time blocks ($\ge 2$) for FEL equilibration check | `2` |
| `pca_mask` | Atom mask used for PCA coordinate calculation | `@CA` |
| `pca_modes_visualize` | Number of PCA modes to calculate displacement tables for | `4` |
| `pca_mass_weighted` | Use mass-weighted RMS fit + `mwcovar` (`true`) or standard Cartesian `covar` PCA (`false`) | `false` |
| `rmsd_mask` | Atom mask used for RMSD alignment and calculation | `@CA` |
| `rmsd_reference` | Alignment reference structure (`average`, `first`, or path to a custom PDB file; `average` generates `avg_rmsd.rst7` for alignment and `avg_rmsd.pdb` for visualization; for flexible/bimodal systems prefer `first` or an experimental PDB) | `average` |
| `rg_mask` | Atom mask used for mass-weighted Radius of Gyration (`radgyr`) | `@CA` |
| `sasa_mask` | Atom mask used for LCPO SASA calculation | `:1-auto&!@H*` |
| `sasa_strip_solvent` | Strip common water models (`WAT`, `OPC`, `TIP3P`, `TIP4P`, `SPCE`, etc.) and monovalent ions before SASA | `true` |
| `sasa_strip_divalent` *(optional)* | Also strip divalent metal ions (`MG`, `CA`, `ZN`, etc.) during SASA calculation | `false` |
| `hbond_mask` | Atom mask used for solute-solute hydrogen bond detection | `:1-auto` |
| `hbond_distance` | Cutoff distance for hydrogen bond acceptance (Å) | `3.0` |
| `hbond_angle` | Cutoff angle for hydrogen bond acceptance (degrees, or `-1` to disable) | `135.0` |
| `distance1_mask1`, `distance1_mask2` | Atom masks for Distance 1 (`auto` resolves to `:<last_res>@CA`) | `:1@CA`, `auto` |
| `distance2_mask1`, `distance2_mask2` | Atom masks for Distance 2 (`auto` resolves to `:<last_res>@CA`) | `:1@CA`, `auto` |
| `distance_noimage` | Append `noimage` to `cpptraj` `distance` calculations to prevent PBC minimum-image wrapping on extended/intramolecular distances | `true` |
| `secstruct_res` | Residue selection range for DSSP | `1-auto` (Auto C-terminal resolution) |
| `secstruct_type` | Secondary structure types to count: `total` (codes 1–7: all non-coil incl. turn/bend), `structured` (codes 1–5: canonical $\alpha+\beta$ only), or comma-separated types (`beta`, `alpha`, `helix`, `turn`, `bend`, `coil`, etc.) | `total` (All structures except coil) |
| `secstruct_betadetail` | Split beta structures into Parallel/Anti-parallel (`true`) or Extended/Bridge (`false`) | `true` |
| `dihedral_mask1` .. `dihedral_mask4` | Four atom/center masks defining the pseudo-dihedral angle | `:1-13@CA`, `:14@CA`, `:49@CA`, `:50-auto@CA` |
| `periodic_vars` *(optional)* | Comma-separated custom variable/file labels to treat as periodic $\pm 180^\circ$ angles (in addition to auto-detected `DIHEDRAL`/`PHI`/`PSI`/`OMEGA`/`CHI*`/`TORSION`) | *(empty)* |
| `plot_title` | Plot title template (`{dir_name}` is replaced by output folder name) | `Free Energy Landscape ({dir_name})` |
| `label_pc1`, `label_pc2`, `label_pc3`, `label_rmsd`, `label_rg`, `label_sasa`, `label_hbond`, `label_dihedral`, `label_secstruct`, `label_distance1`, `label_distance2` | Custom axis labels for plots | Variable defaults |
| `color_1d` | Hex color code for 1D line plotting | `#1f77b4` |
| `colormap_2d` | Color map for 2D plotting | `viridis` |
| `colormap_3d` | Color map for 3D Plotly/Matplotlib plotting | `jet` |
| `export_top_n` | Maximum number of distinct local minimum wells to extract in `export` mode | `10` |
| `export_frames_per_well` | Number of representative frames extracted per well | `1` |
| `export_distance_ratio` | Minimum normalized Euclidean separation between wells as a fraction of the 2D diagonal | `0.10` |
| `export_min_bin_count` | Minimum bin count required for candidate local minimum wells in `export` mode | `5` |
| `export_max_dg` | Maximum relative free energy ($\Delta G$) cutoff for candidate export wells (`auto` = $5 k_B T$, a positive float, or `none` to disable) | `auto` |
| `export_strip_solvent` | Strip common water models and monovalent ions (plus divalent ions if `sasa_strip_divalent = true`) from exported PDB frames | `false` |
| `mode` | Default execution mode (`analysis`, `fel`, `export`, or `equilibration`) | `analysis` |
| `var1`, `var2`, `var3` | Default reaction coordinates for `fel` and `export` modes | `PC1`, `PC2`, *(empty)* |
| `vars` | Default comma-separated variable list for `analysis` (and fallback for `export`) | *(empty)* |

### Trajectory List Format (`traj.in` & `trajectory_type`)
- **`md`:** Each non-comment line specifies `<trajectory_path> [start stop offset]`.
- **`remd`:** Each line specifies the first replica trajectory `<trajectory_path> [start stop offset]` and automatically appends `remdtraj remdtrajtemp <temperature>`.
- **`mix`:** Allows per-line tagging via `<trajectory_path> <remd|md> [start stop offset]` (untagged lines default to standard `md`).

> [!IMPORTANT]
> **Scientific Note on `mix` Mode:** Unweighted pooling of multiple trajectories assumes that all included frames sample the same canonical equilibrium ensemble at the configured `temperature`. Mixing trajectories from different temperatures, biased simulations without reweighting, or unequilibrated runs invalidates Boltzmann free energy estimation ($\Delta G = -k_B T \ln P$).

---

## Usage

The suite supports both **Interactive Mode** (prompting for variables) and **Non-interactive Batch Mode** (passing options via CLI flags).

### 1. Command-Line Arguments & Flags

The orchestrator `main.py` accepts the following arguments:

| Flag | Long Flag | Description | Default Value |
| :--- | :--- | :--- | :--- |
| `-b` | `--batch` | Enable non-interactive batch mode (bypasses all prompts). | `False` |
| `-m` | `--mode` | Execution mode (`analysis`, `fel`, `export`, or `equilibration`/`eq`). | Loaded from config or prompted |
| | `--eq-check` | Run FEL equilibration check (block convergence analysis) alongside `fel` mode. | `False` |
| | `--eq-blocks` | Number of equal chronological time blocks ($\ge 2$) for FEL equilibration check. | `2` |
| `-p` | `--params` | Path to the configuration file (e.g. `parameters.in`). | `parameters.in` |
| `-d` | `--dim` | Dimension of the FEL (1, 2, or 3). | Loaded from config or prompted |
| `-t` | `--top` | Topology file path (`.top`/`.prmtop`). | Loaded from config or prompted |
| `-x` | `--traj` | Trajectory list file path. | Loaded from config or prompted |
| `-o` | `--out` | Output directory name. | Loaded from config or prompted |
| | `--temp` | Simulation temperature in Kelvin. | Loaded from config or prompted |
| `-v` | `--vars` | Comma-separated variables list (e.g. `PC1,RMSD`) for `analysis` and `export` modes. | Prompted |
| | `--var1` | First reaction coordinate/variable (e.g. `RMSD`, `RG`, etc.). | Prompted |
| | `--var2` | Second reaction coordinate (required for 2D/3D). | Prompted |
| | `--var3` | Third reaction coordinate (required for 3D). | Prompted |

### 2. Execution Modes

The suite operates in four distinct modes (`--mode`):
- **Analysis (`analysis`):** Calculates structural metrics from the trajectory using `cpptraj` but does not plot FELs.
- **FEL (`fel`):** First calculates the metrics, then computes the 1D/2D/3D Free Energy Landscape histogram and plots it. Pass `--eq-check` (or set `fel_equilibration_check = true`) to also run the equilibration check.
- **Export Frames (`export`):** Calculates metrics, builds a 2D histogram, detects distinct free energy wells via 8-neighbor local-maximum detection with connected-component plateau suppression and normalized minimum-separation filtering (including periodic $\pm 180^\circ$ dihedral distance handling), selects representative frames strictly from inside each target well's bin, and extracts representative PDB structures via `cpptraj`. Extraction details are logged to `export_info.log`.
- **FEL Equilibration Check (`equilibration` / `eq`):** Splits the aligned trajectory into $B$ equal chronological blocks (default `2`; configurable via `fel_equilibration_blocks` or `--eq-blocks`) on shared bin edges, evaluates Boltzmann-weighted block standard error $\text{wSE}(\Delta G)$ (alongside block $\text{wRMSD}$), unweighted block-std $\text{RMSD}$/mean, all-block bin & probability-mass overlap %, and normalized Jensen–Shannon divergence ($D_{\text{JS}}/\ln B$), and generates `*_fel_equilibration.png` and `*_fel_equilibration.log`. As a $B$-invariant rule of thumb (assuming weakly correlated blocks), $\text{wSE} \le 0.5\,k_B T$, mass overlap $\ge 80\%$, and $D_{\text{JS}}/\ln B \le 0.10$ indicate good convergence, whereas $\text{wSE} > 1\,k_B T$, mass overlap $< 60\%$, or $D_{\text{JS}}/\ln B > 0.25$ warns of conformational drift or insufficient sampling.

### 3. Secondary Structure Filtering (`filter_beta.sh`)
You can filter frames by a secondary-structure threshold before plotting using `filter_beta.sh`:
```bash
# 2D filtering (e.g. RMSD vs beta-sheet count >= 5)
./filter_beta.sh output/rmsd_output.dat output/secstruct_output.dat 5

# 1D filtering
./filter_beta.sh output/secstruct_output.dat 5
```

> [!NOTE]
> **Scientific Note on Filtered FELs:** Set `secstruct_type = beta` (or `para,anti` / `extended,bridge`) in `parameters.in` when filtering strictly by $\beta$-sheet content rather than `secstruct_type = total`. Any FEL plotted from filtered frames represents a **conditional** free energy landscape $\Delta G(q \mid \text{filter})$ whose zero reference is shifted by $+k_B T \ln P(\text{filter})$, so its $\Delta G$ scale should not be compared directly with the unfiltered trajectory.

### 4. Interactive Execution
Run the following command to start the analysis suite. You will be prompted to enter parameters. Any values specified via CLI flags will override the configuration file defaults and become the preselected default values for the prompts:
```bash
# Standard interactive mode (using default parameters.in):
python main.py

# Interactive mode overriding the config file and dimension:
python main.py -p local_parameters.in --dim 3
```

> [!NOTE]
> If no parameter file is specified using `-p` or `--params`, the program strictly falls back to the global `parameters.in` located in the script's directory. It does not automatically load a `parameters.in` in your current working directory.

### 5. Non-interactive Batch Execution (HPC/Slurm Recommended)
Specify the `-b`/`--batch` flag to bypass all prompts. If any required parameters are missing from both the CLI flags and the configuration file, the script will exit with an error.

```bash
# Run a 2D FEL analysis completely non-interactively
python main.py --batch --mode fel --dim 2 --top h2h3mono.top --traj traj.in --var1 RMSD --var2 RG --out my_analysis
```

Here is a sample Slurm submission script utilizing the batch mode:

```bash
#!/bin/bash
#SBATCH -J md_fel_analysis
#SBATCH -p short
#SBATCH -N 1
#SBATCH -n 1
#SBATCH -t 02:00:00
#SBATCH -o analysis_%j.out
#SBATCH -e analysis_%j.err

cd $SLURM_SUBMIT_DIR

# Load required modules
module load python/3.9

# Run program in batch mode (no user interaction required)
python main.py --batch --mode fel --dim 2 --top h2h3mono.top --traj traj.in --var1 RMSD --var2 RG --out analysis
```
---


## Project Structure

- **`main.py`:** Main orchestrator Python script that parses user inputs, loads configurations, validates parameters, and triggers analyses/exports.
- **`plot_fel.py`:** Visualization utility that constructs histograms and computes free energies to generate 1D/2D/3D plots.
- **`calculate_*.sh`:** Specialized bash wrappers that generate input files and invoke `cpptraj` to calculate metrics (`PC*`, `RMSD`, `Rg`, `SASA`, `Distance`, `Dihedral`, `HBOND`, and `DSSP`).
- **`farkli_min_bulma.sh`:** Local-minimum detection and representative PDB frame extraction script for `export` mode.
- **`filter_beta.sh`:** Helper script to filter time series frames by secondary-structure count threshold.
- **`parameters.in`:** Configuration file.
- **`requirements.txt`:** List of Python library dependencies.
