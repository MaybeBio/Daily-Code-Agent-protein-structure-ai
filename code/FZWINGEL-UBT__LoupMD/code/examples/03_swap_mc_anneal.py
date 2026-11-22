"""Swap Monte Carlo during an anneal: Na <-> K swaps in a (Na,K)Cl rock-salt solid solution.

Half of the Na sites of a 3x3x3 NaCl supercell (216 atoms) hold K, placed at random. The anneal heats 0 -> 1000 K
in 2 ps and cools at -30 K/ps to 250 K (27 ps at 1 fs); every 100 MD steps a block of 50 Na <-> K swap attempts
(Metropolis at the thermostat's target) lets the cations order. ``--steps`` runs only the first MD steps; the
run writes a restart, so ``loupmd run --resume OUTPUT`` continues it, and ``loupmd quench OUTPUT`` relaxes picked
frames once the schedule is finished.

    python examples/03_swap_mc_anneal.py --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def solid_solution(seed):
    """NaCl 3x3x3 with half of the Na replaced by K at random, at the mean lattice constant (5.97 A)."""
    import numpy as np
    from ase.build import bulk

    atoms = bulk("NaCl", "rocksalt", a=5.97, cubic=True).repeat((3, 3, 3))
    sodium = np.flatnonzero(atoms.numbers == 11)
    chosen = np.random.default_rng(seed).choice(sodium, size=len(sodium) // 2, replace=False)
    atoms.numbers[chosen] = 19
    return atoms


def main(argv=None):
    p = _common.parser(__doc__.splitlines()[0], name="03_swap_mc_anneal", steps=200)
    p.add_argument("--every", type=int, default=100, help="MD steps between swap blocks")
    p.add_argument("--attempts", type=int, default=50, help="swap attempts per block")
    args = p.parse_args(argv)

    import loupmd as lm

    ff = _common.load(args)
    anneal = lm.protocols.ramp(0, 1000, ps=2) + lm.protocols.ramp(1000, 250, rate_K_per_ps=-30)
    run = lm.md(solid_solution(args.seed), model=ff, schedule=anneal, timestep_fs=1.0, steps=args.steps or None,
                mc=[lm.mc.Swap(pairs=[("Na", "K")], every=args.every, attempts=args.attempts)],
                initial_velocities=10.0, seed=args.seed,
                output=lm.Output(args.output, trajectory_every=10, thermo_every=10, restart_every=10_000))
    print(run.summary)
    run.simulation.close()
    print(f"output: {args.output}; continue with: loupmd run --resume {args.output}")
    return run


if __name__ == "__main__":
    main()
