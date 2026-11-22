# AlgoSB 2026 practical: implicit transfer operators

Material for the hands-on session *"Software practical on Implicit Transfer Operators"* (Simon Olsson, Monday 23 November).

* **Part 1:** `notebooks/1_ito_wolfe_quapp.ipynb`. Train an implicit transfer operator (ITO) on a 2D toy system and evaluate it
  against reference simulations (free energies, stationarity, implied timescales, Chapman–Kolmogorov test).
* **Part 2:** `notebooks/2_tito_proteins.ipynb`. Run the pre-trained transferable ITO model **TITO-3M**
  ([PLaTITO project](https://panosantoniadis.github.io/platito/)) on a small protein of your choice.

Everything runs on a normal laptop CPU (macOS, Linux or Windows). No GPU or accounts are needed.

---

## Setup: please try do this *before* the school

**1. Unzip** this folder somewhere convenient, e.g. your home directory.

**2. Install `uv`**, a small Python package manager, by pasting one line into a terminal:

* macOS / Linux (Terminal):

  ```
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

* Windows (PowerShell):

  ```
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

Then **close and reopen the terminal**. If you already have `uv`, `brew install uv` or `pip install uv` work too.

**3. Install the environment.** In the terminal, go to this folder and run `uv sync`:

```
cd path/to/AlgoSB_exercises
uv sync
```

This downloads Python 3.12 and all packages into a `.venv` folder inside this folder.

**4. Check that everything works:**

```
uv run python check_setup.py
```

It should end with `All good!`. If not, try to check if you followed the instructions. You can always start from scratch. If the problem persists work with a partner. 

---

## During the practical

In a terminal in this folder:

```
uv run jupyter lab
```

This opens Jupyter in your browser. Open `notebooks/1_ito_wolfe_quapp.ipynb` and run the cells from top to bottom with `Shift + Enter`.

*VS Code users:* open this folder, open a notebook, and choose the `.venv` Python environment as the kernel.

---

## Troubleshooting

* **`uv: command not found`**: close and reopen the terminal after installing uv.
* **Intel Mac**: supported. An older PyTorch version is installed automatically.
* **Windows on ARM / Linux on ARM**: not supported by all packages. Please team up with a neighbour.
* **Without uv**: in any Python 3.11 or 3.12 environment, run `pip install -e .` in this folder. On Linux this downloads a
  much larger GPU version of PyTorch.
* **To remove everything**: delete this folder. `uv cache clean` frees uv's download cache.

---

## Contents

```
notebooks/            the two notebooks for the practical
minito/               a minimal ITO library written for this practical (Wolfe-Quapp simulation, flow-matching ITO, analysis)
platito/              inference code of PLaTITO (unmodified subset, MIT licence; see platito/README_VENDORED.md)
data/checkpoints/     TITO-3M weights (from huggingface.co/pantoniadis/platito)
data/proteins/        folded/unfolded starting structures of 11 fast-folding proteins (from the PLaTITO repository)
data/wolfe_quapp/     a pre-trained ITO for part 1, in case training is too slow on your laptop
data/3Dmol-min.js     3D molecule viewer (3Dmol.js, BSD licence), so that visualisation works offline
check_setup.py        installation check
```

Everything works offline except the optional cell in part 2 that downloads a structure from the PDB or AlphaFold DB.

**Credits.** PLaTITO and TITO-3M: Antoniadis, Pavesi, Olsson & Winther, *Protein Language Model Embeddings Improve Generalization
of Implicit Transfer Operators*, ICML 2026 ([arXiv:2602.11216](https://arxiv.org/abs/2602.11216),
[code](https://github.com/PanosAntoniadis/platito)). ITO: Schreiner, Winther & Olsson, NeurIPS 2023
([arXiv:2305.18046](https://arxiv.org/abs/2305.18046)). Fast-folding proteins: Lindorff-Larsen et al., *Science* 334, 517 (2011).
