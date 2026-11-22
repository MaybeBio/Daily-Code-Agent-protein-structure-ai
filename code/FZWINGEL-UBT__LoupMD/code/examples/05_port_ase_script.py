"""Porting an ASE script to LoupMD: ``lm.calc`` for single points, ``loupmd.ase.Langevin`` for MD.

The ASE original would be

    atoms.calc = MACECalculator(model_paths=..., head="matpes_r2scan")
    dyn = ase.md.langevin.Langevin(atoms, 1 * units.fs, temperature_K=300, friction=0.002 / units.fs)
    dyn.attach(log, interval=10); dyn.run(steps)

The port changes two lines: the calculator becomes ``lm.calc`` (ASE drives every call, so the speed-up is the
smaller one) and the integrator comes from ``loupmd.ase`` with ``model=`` (LoupMD runs the MD loop in its engine:
the full speed-up). ASE's arguments, units and observers stay.

    python examples/05_port_ase_script.py --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def main(argv=None):
    p = _common.parser(__doc__.splitlines()[0], name="05_port_ase_script", steps=100, structure=True)
    p.add_argument("--repeat", type=int, nargs=3, default=(3, 3, 3), metavar=("NA", "NB", "NC"), help="supercell")
    args = p.parse_args(argv)

    import numpy as np
    from ase import units
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

    import loupmd as lm
    from loupmd.ase import Langevin  # was: from ase.md.langevin import Langevin

    ff = _common.load(args)
    atoms = _common.structure(args).repeat(tuple(args.repeat))

    # 1. Single points through the ASE calculator interface (was: MACECalculator).
    atoms.calc = lm.calc(ff)
    print(f"E = {atoms.get_potential_energy():.6f} eV, max |F| = {abs(atoms.get_forces()).max():.4f} eV/A")

    # 2. MD: the same ASE arguments; model= hands the loop to LoupMD.
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    atoms.calc = None
    MaxwellBoltzmannDistribution(atoms, temperature_K=300, rng=np.random.default_rng(args.seed))
    dyn = Langevin(atoms, 1.0 * units.fs, temperature_K=300, friction=0.002 / units.fs, model=ff,
                   seed=args.seed, trajectory=str(out / "md.traj"), logfile=str(out / "md.log"), loginterval=10,
                   output=str(out / "md.loupmd"))
    temperatures = []

    def report():
        temperatures.append(atoms.get_temperature())
        print(f"step {dyn.get_number_of_steps():6d}  T = {temperatures[-1]:7.1f} K")

    dyn.attach(report, interval=max(1, args.steps // 5))
    dyn.run(args.steps)
    dyn.close()
    print(f"output: {out}")
    return temperatures


if __name__ == "__main__":
    main()
