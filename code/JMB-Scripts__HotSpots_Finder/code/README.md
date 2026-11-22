# HotSpots Finder for PyMOL

A PyMOL-integrated hotspot detection and visualization tool designed for protein interface analysis and AI-guided binder design workflows such as RFdiffusion.

---
## CHANGES IN v3.7
  - Run now replaces the previous result instead of merging into it.
  - All calculations restricted to protein (waters/ligands/ions excluded).
  - SASA computed once on one clean clone (was twice, inconsistently).
  - Removed dead code: _project_surface_local, _HYDRO_OBJ, an overwritten
    score formula, and five unused imports.
  - One Run code path: the logger is built into run_hs_auto(), replacing the
    signal disconnect/reconnect patch that duplicated the logic.
  - Fixed a race where PyMOL's asynchronous command queue could delete the
    SASA clone after it was recreated, breaking every run after the first.
  - Output compatible with RFdiffusion-3 and Rfdiffusion-proteina  

## Overview

**HotSpots Finder** is a PyQt-based plugin for PyMOL that identifies and ranks surface residues likely to participate in protein-protein interactions.

The tool combines:

- geometric protrusion analysis
- solvent accessibility
- local residue environment
- hydrophobicity
- neighborhood density

to generate weighted hotspot scores directly inside PyMOL.

The plugin was designed with modern protein design workflows in mind, particularly:

- RFdiffusion
- ProteinMPNN
- interface engineering
- binder design
- epitope targeting

---

## Features

### Hotspot Detection

- Surface residue identification
- Weighted multi-parameter scoring
- Adjustable thresholds
- Automatic ranking of candidate interface residues

### Visualization

- PyMOL-integrated coloring
- Surface highlighting
- Hotspot markers
- Hydrophobic patch visualization
- Interactive selection handling

### RFdiffusion Support

- Direct hotspot export
- Contig-compatible residue formatting
- Binder-design oriented workflows

### GUI

- Modern PyQt interface
- Real-time controls
- Adjustable scoring weights
- Interactive residue selection

---

## Scoring Parameters

The hotspot score combines several structural descriptors:

| Parameter | Description |
|----------|-------------|
| SASA | Solvent Accessible Surface Area |
| Protrusion | Exposure relative to surrounding atoms |
| Hydrophobicity | Interface-friendly chemistry |
| Density | Local packing environment |
| Neighborhood | Nearby residue composition |

The final score is computed as a weighted combination of these descriptors.

---

## Requirements

### Software

- PyMOL
- Python 3.9+
- PyQt5 or PyQt6

### Python Packages

Required:
- numpy
- scipy
- matplotlib

Optional:
- pandas
- scikit-learn

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your_username/hotspots-finder.git
cd hotspots-finder
```

### 2. Install dependencies

```bash
pip install numpy scipy matplotlib
```

### 3. Launch in PyMOL

Inside PyMOL:

```python
run HotSpots_Finder_PyQt-v3.5.py
```

Then launch the plugin:

```python
hotspots_finder
```

---

## Usage

### Basic Workflow

1. Load a protein structure in PyMOL
2. Open HotSpots Finder
3. Select the target object
4. Adjust scoring parameters if needed
5. Run hotspot detection
6. Inspect and export selected hotspots

---

## RFdiffusion Example

Generated hotspots can be directly used in RFdiffusion configurations:

```json
{
    "select_hotspots": {
        "A46": "ALL",
        "A103": "ALL",
        "A108": "ALL"
    }
}
```

Typical workflow:

1. Detect hotspots
2. Select best interface residues
3. Export hotspot list
4. Launch RFdiffusion binder generation

---

## Planned Features

- Hotspot clustering
- Surface heatmaps
- Automatic contig generation
- Live rescoring
- PyMOL CGO vector visualization
- KD-tree acceleration
- AI-assisted hotspot ranking

---

## Scientific Applications

- Protein binder design
- Interface engineering
- Antibody epitope targeting
- Viral protein interaction studies
- Rational mutagenesis
- Structural bioinformatics

---

## Screenshots

### Interface Overview

<img width="562" height="740" alt="image" src="https://github.com/user-attachments/assets/d3a1bd8d-5343-4b02-a13a-b2df93ef092c" />


### Hotspot Surface Visualization

<img width="1383" height="559" alt="image" src="https://github.com/user-attachments/assets/8ce330be-139f-4f5f-9c7e-041c0fa36338" />


###  Export

<img width="562" height="740" alt="image" src="https://github.com/user-attachments/assets/92187f49-f83c-41d1-af22-4d5d96a50bdc" />

---

## Citation

If you use this tool in academic work, please let a small message in issues 

---

## License

Do whatever you want, just don't forget it was coded by a stupid biochemist for this matter me.

---

## Author

JMB-scripts

---

## Acknowledgements
