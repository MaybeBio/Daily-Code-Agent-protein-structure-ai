"""Structure relaxations with LBFGS and FIRE, at fixed cell and with a variable cell.

Four relaxations of one structure with ``lm.optimize`` (ASE 3.27's algorithms and defaults): LBFGS and FIRE at
fixed cell, then both with ``FrechetCell`` (ASE's ``FrechetCellFilter``) at ``--pressure`` GPa. LBFGS at fixed cell
runs on the GPU inside the engine; FIRE and the cell filter take their steps on the host. The structure is
rattled first so there is something to relax. ``--steps`` caps every relaxation.

    python examples/04_gpu_relaxations.py --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def main(argv=None):
    p = _common.parser(__doc__.splitlines()[0], name="04_gpu_relaxations", steps=500, structure=True)
    p.add_argument("--fmax", type=float, default=0.01, help="convergence, eV/A")
    p.add_argument("--pressure", type=float, default=0.0, help="variable-cell target pressure, GPa")
    p.add_argument("--repeat", type=int, nargs=3, default=(2, 2, 2), metavar=("NA", "NB", "NC"), help="supercell")
    args = p.parse_args(argv)

    import loupmd as lm

    start = _common.structure(args).repeat(tuple(args.repeat))
    start.rattle(0.05, seed=args.seed)
    ff = _common.load(args)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    cell = lm.optimize.FrechetCell(scalar_pressure_GPa=args.pressure)
    runs = {
        "lbfgs_fixed": lm.optimize.LBFGS(),
        "fire_fixed": lm.optimize.FIRE(),
        "lbfgs_cell": lm.optimize.LBFGS(cell_filter=cell),
        "fire_cell": lm.optimize.FIRE(cell_filter=cell),
    }
    results = {}
    for name, optimizer in runs.items():
        result = lm.optimize.relax(ff, start, optimizer, fmax=args.fmax, steps=args.steps)
        result.atoms.write(out / f"{name}.extxyz")
        volume = result.atoms.get_volume() / start.get_volume()
        print(f"{name}: {result}; V/V0 {volume:.4f}")
        results[name] = result
    print(f"output: {out}")
    return results


if __name__ == "__main__":
    main()
