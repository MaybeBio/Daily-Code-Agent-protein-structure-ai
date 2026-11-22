"""NPT + D3(BJ) short melt-quench of NbCl5 with MACE MH-1 through ``lm.md``, then a relaxation with the same term.

The molecular chlorides need dispersion at constant pressure. The schedule heats 0 -> 1000 K in 2 ps, then cools
at -30 K/ps to 250 K (27 ps at 1 fs), Langevin BAOAB at 0 GPa with a hydrostatic cell. ``--steps`` runs only the
first steps. Afterwards the last state is relaxed (LBFGS on the GPU, MACE plus the same D3 term) at its own cell:
the 0 K end of a melt-quench.

    python examples/02_npt_d3_melt_quench_nbcl5.py --structure NbCl5.cif --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def main(argv=None):
    p = _common.parser(__doc__.splitlines()[0], name="02_npt_d3_melt_quench_nbcl5", steps=200, structure=True)
    p.add_argument("--repeat", type=int, nargs=3, default=(1, 1, 1), metavar=("NA", "NB", "NC"), help="supercell")
    p.add_argument("--relax-steps", type=int, default=200, help="LBFGS steps of the final relaxation")
    p.add_argument("--dispersion", default="d3bj", help="the D3 preset (`loupmd dispersion list`)")
    args = p.parse_args(argv)
    if args.structure is None:
        p.error("--structure NbCl5.cif is needed (any structure ASE reads)")

    import loupmd as lm

    ff = _common.load(args)
    melt_quench = lm.protocols.ramp(0, 1000, ps=2) + lm.protocols.ramp(1000, 250, rate_K_per_ps=-30)
    run = lm.md(args.structure, model=ff, ensemble="NPT", pressure_GPa=0.0, cell_mode="hydrostatic",
                schedule=melt_quench, timestep_fs=1.0, steps=args.steps or None, dispersion=args.dispersion,
                repeat=tuple(args.repeat), seed=args.seed,
                output=lm.Output(args.output, trajectory_every=10, thermo_every=10, restart_every=5000))
    print(run.summary)

    atoms = run.simulation.atoms                 # the last state, at its own (NPT) cell
    run.simulation.close()
    atoms.calc = None
    result = lm.optimize.relax(ff, atoms, lm.optimize.LBFGS(), fmax=0.01, steps=args.relax_steps,
                               dispersion=args.dispersion)
    out = Path(args.output) / "quenched.extxyz"
    result.atoms.write(out)
    print(f"relaxation: {result}; -> {out}")
    print(f"output: {args.output}")
    return run, result


if __name__ == "__main__":
    main()
