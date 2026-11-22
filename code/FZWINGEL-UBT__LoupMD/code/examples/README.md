# LoupMD examples

Short, runnable scripts for the common jobs, after FastMACE's. Every script takes

- `--model` and `--head` (default MACE MH-1 with its `matpes_r2scan` head) and `--checkpoint PATH` for the label's
  file, checked against its SHA-256; without it LoupMD looks in `$LOUPMD_MODELS` and its cache;
- `--steps N`: how many MD (or optimiser) steps to run, small for a smoke run;
- `--output DIR`: where to write (default `./loupmd-examples/<script>/`);
- `--seed`, and `--structure FILE` where the script reads one (default: rock-salt NaCl built in the script).

`python examples/<script> --help` lists the rest. The first run of a model exports it to a bundle, which needs the
export extra (`pip install "loupmd[export]"`); later runs reuse the bundle.

| Script | What it shows |
| --- | --- |
| `01_nvt_anneal_nacl.py` | NVT simulated anneal of NaCl 3x3x3 through `lm.load` and `lm.Simulation` with an `lm.protocols` schedule (0 -> 1000 K -> 250 K); `--steps` pauses the schedule early, and the restart continues it |
| `02_npt_d3_melt_quench_nbcl5.py` | NPT (Langevin BAOAB, 0 GPa) with D3(BJ): a short melt-quench of NbCl5 through `lm.md`, then an LBFGS relaxation of the last state with the same D3 term |
| `03_swap_mc_anneal.py` | Na <-> K swap Monte Carlo during an anneal of a (Na,K)Cl solid solution through `lm.md(mc=...)`; continue with `loupmd run --resume DIR`, then `loupmd quench DIR` |
| `04_gpu_relaxations.py` | `lm.optimize.LBFGS` and `lm.optimize.FIRE`, at fixed cell and with `FrechetCell` (variable cell) |
| `05_port_ase_script.py` | Porting an ASE script: `lm.calc` for single points, `loupmd.ase.Langevin(..., model=)` in place of ASE's `Langevin` |
| `06_large_cell.py` | A cell of 373,248 atoms through `lm.md`, run in tiles when it does not fit the GPU whole |

Smoke runs (the acceptance tier runs these with `--steps 200`, `tests/gpu/test_examples.py`):

```bash
python examples/01_nvt_anneal_nacl.py --steps 200
python examples/02_npt_d3_melt_quench_nbcl5.py --structure NbCl5.cif --steps 200
python examples/03_swap_mc_anneal.py --steps 200
python examples/04_gpu_relaxations.py --steps 200
python examples/05_port_ase_script.py --steps 200
python examples/06_large_cell.py --steps 200
```

The schedules' step counts are physical: at 1 fs, `01` is 270,000 steps and `02` and `03` 27,000. Short `--steps`
runs are smoke runs, not results.
