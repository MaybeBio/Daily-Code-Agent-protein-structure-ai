"""NVT simulated anneal of NaCl with MACE MH-1 through ``lm.Simulation`` and an ``lm.protocols`` schedule.

The schedule heats 0 -> 1000 K in 20 ps, then cools at -3 K/ps to 250 K (270 ps, 270,000 steps at 1 fs).
``--steps`` runs only the first steps of it, so a smoke run is cheap; ``--steps 0`` runs the whole schedule.
Continue a paused run with ``lm.Simulation.resume(OUTPUT)``.

    python examples/01_nvt_anneal_nacl.py --steps 200
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _common  # noqa: E402


def main(argv=None):
    args = _common.parser(__doc__.splitlines()[0], name="01_nvt_anneal_nacl", steps=200,
                          structure=True).parse_args(argv)

    import loupmd as lm

    atoms = _common.structure(args).repeat((3, 3, 3))       # 216 atoms
    ff = _common.load(args)
    anneal = lm.protocols.ramp(0, 1000, ps=20) + lm.protocols.ramp(1000, 250, rate_K_per_ps=-3)
    sim = lm.Simulation(
        atoms, ff,
        integrator=lm.integrators.Langevin(timestep_fs=1.0, temperature_K=0.0, friction_per_fs=0.002),
        output=lm.Output(args.output, trajectory_every=10, thermo_every=10, restart_every=5000),
        seed=args.seed,
    )
    summary = sim.run(schedule=anneal, steps=args.steps or None)
    sim.save_restart()                                       # resume from here with lm.Simulation.resume
    print(f"{summary.steps} steps at {summary.ms_per_step:.3f} ms/step, T = {summary.final_temperature_K:.1f} K")
    sim.close()
    print(f"output: {args.output}")
    return summary


if __name__ == "__main__":
    main()
