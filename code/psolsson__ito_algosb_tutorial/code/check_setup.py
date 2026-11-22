"""Checks that everything needed for the practical works on this computer.

Run from this folder with:   uv run python check_setup.py
"""

import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
ok = True


def step(name):
    print(f"- {name:<50s}", end="", flush=True)


try:
    step("importing packages")
    import numpy as np
    import torch
    import deeptime  # noqa: F401
    import mdtraj as md
    import matplotlib  # noqa: F401
    import py3Dmol  # noqa: F401
    import jupyterlab  # noqa: F401
    from minito.systems import WolfeQuapp, simulate
    from minito.ito import LaggedPairs, VectorField
    from platito.models import PLaTITO
    from platito.utils.amino_acid_vocab import AA_1_TO_ID, AA_3_TO_1

    print(f"ok  (python {sys.version.split()[0]}, torch {torch.__version__}, numpy {np.__version__})")

    step("part 1: simulation + a few training steps")
    t0 = time.time()
    trajs = simulate(WolfeQuapp(), np.zeros((10, 2)), n_steps=10_000, stride=50)
    pairs = LaggedPairs(trajs, max_lag=50)
    model = VectorField(max_lag=50)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    t1 = time.time()
    n_iter = 100
    for _ in range(n_iter):
        x_t, x_tau, lag = pairs.sample(1024)
        z0, s = torch.randn_like(x_tau), torch.rand(1024)
        z_s = s[:, None] * x_tau + (1 - s[:, None]) * z0
        loss = ((model(z_s, s, x_t, lag) - (x_tau - z0)) ** 2).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
    sec_per_it = (time.time() - t1) / n_iter
    print(f"ok  (~{10_000 * sec_per_it / 60:.1f} min for the default training run)")

    step("part 2: TITO-3M checkpoint + one sampling step")
    tito = PLaTITO.load_from_checkpoint(
        ROOT / "data" / "checkpoints" / "tito_3M.ckpt", map_location="cpu", weights_only=False
    ).eval()
    pdb = md.load(ROOT / "data" / "proteins" / "trp_cage" / "folded.pdb")
    ca = pdb.topology.select("name CA")
    seq = "".join(AA_3_TO_1.get(pdb.topology.atom(i).residue.name, "X") for i in ca)
    n = 8
    x0 = torch.tensor(pdb.xyz[0, ca], dtype=torch.float32)[None].repeat(n, 1, 1)
    t0 = time.time()
    tito.sample(
        x0,
        ode_steps=50,
        lag=torch.full((n,), 1, dtype=torch.long),
        temp=torch.full((n,), 300, dtype=torch.long),
        residue_ids=torch.tensor([[AA_1_TO_ID.get(a, AA_1_TO_ID["X"]) for a in seq]] * n),
    )
    print(f"ok  ({time.time() - t0:.1f} s per step for {n} Trp-cage trajectories)")
except Exception as e:  # noqa: BLE001
    ok = False
    print("FAILED")
    print(f"\n{type(e).__name__}: {e}")

print()
if ok:
    print("All good! You are ready for the practical. Start it with:  uv run jupyter lab")
else:
    print("Something is not working. Please send the full output above to the organisers.")
    sys.exit(1)
