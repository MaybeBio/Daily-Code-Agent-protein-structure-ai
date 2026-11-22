"""A cell larger than the GPU holds whole: NaCl with hundreds of thousands of atoms, run in tiles.

``lm.md`` chooses the execution by itself (``capacity="auto"``): the whole cell when it fits the GPU's memory,
else tiles, each evaluated with a halo of its neighbours (``guide/large-cells`` in the documentation). The report's
plan line names the mode. The default 36x36x36 supercell of the 8-atom cell has 373,248 atoms;
``--capacity tiled`` forces tiles on a small cell, which is how the tests run it.

    python examples/06_large_cell.py --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def main(argv=None):
    p = _common.parser(__doc__.splitlines()[0], name="06_large_cell", steps=200, structure=True)
    p.add_argument("--repeat", type=int, nargs=3, default=(36, 36, 36), metavar=("NA", "NB", "NC"),
                   help="supercell of the structure")
    p.add_argument("--capacity", choices=("auto", "whole", "tiled", "wavefront"), default="auto",
                   help="auto: tiles only when the cell does not fit the GPU")
    args = p.parse_args(argv)

    import loupmd as lm

    atoms = _common.structure(args).repeat(tuple(args.repeat))
    print(f"{len(atoms):,} atoms")
    ff = _common.load(args)
    run = lm.md(atoms, model=ff, temperature_K=300, timestep_fs=1.0, steps=args.steps, capacity=args.capacity,
                initial_velocities="maxwell_boltzmann", seed=args.seed,
                output=lm.Output(args.output, trajectory_every=None, thermo_every=20, restart_every=None))
    print(run.summary)
    run.simulation.close()
    print(f"output: {args.output}")
    return run


if __name__ == "__main__":
    main()
