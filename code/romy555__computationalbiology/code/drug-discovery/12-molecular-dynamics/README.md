# Molecular Dynamics from Scratch

A Lennard-Jones molecular dynamics engine with velocity Verlet integration, an energy-conservation test, a thermostat, and physics read from the trajectory: radial distribution functions and diffusion coefficients.

**Data:** none; everything is simulated.

| File | What it is |
|---|---|
| `molecular_dynamics.ipynb` | The complete notebook; it reproduces every number and figure. |
| `animations/md_lab.html` | Interactive animation (open in a browser). |
| `images/` | Figures saved by the notebook. |

## Run it

```bash
python3 -m pip install -U jupyter numpy pandas matplotlib scipy scikit-learn biopython rdkit torch
jupyter notebook molecular_dynamics.ipynb
```
