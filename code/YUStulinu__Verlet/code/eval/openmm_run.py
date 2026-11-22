"""OpenMM runs of the same systems (our parameters, via openmm_ref.openmm_system),
for the comparison of speed, density and structure.

    python eval/openmm_run.py SYSTEM.vsys --steps N [--pressure 1] [--traj out.vtrj] [--log out.csv]
"""

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prep"))
from verlet_prep import openmm_ref as ref  # noqa: E402
from verlet_prep.topology import read_vsys  # noqa: E402

import openmm as mm  # noqa: E402
import openmm.unit as u  # noqa: E402

AVOGADRO = 6.02214076e23


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vsys")
    ap.add_argument("--steps", type=int, default=5000)
    ap.add_argument("--equilibrate", type=int, default=0)
    ap.add_argument("--dt", type=float, default=0.002)
    ap.add_argument("--temperature", type=float, default=300)
    ap.add_argument("--friction", type=float, default=1.0)
    ap.add_argument("--pressure", type=float, default=None)
    ap.add_argument("--report", type=int, default=500)
    ap.add_argument("--platform", default="CUDA")
    ap.add_argument("--precision", default="mixed")
    ap.add_argument("--log")
    ap.add_argument("--traj", help="frames in the engine's VTRJ format")
    ap.add_argument("--traj-every", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    s = read_vsys(a.vsys)
    sysm = ref.openmm_system(s)
    if a.pressure:
        sysm.addForce(mm.MonteCarloBarostat(a.pressure * u.bar, a.temperature * u.kelvin, 25))
    sysm.addForce(mm.CMMotionRemover(1000))
    integ = mm.LangevinMiddleIntegrator(a.temperature * u.kelvin, a.friction / u.picosecond, a.dt * u.picoseconds)
    integ.setRandomNumberSeed(a.seed)
    props = {"Precision": a.precision} if a.platform == "CUDA" else {}
    ctx = mm.Context(sysm, integ, ref.platform(a.platform), props)
    ctx.setPositions(s.xyz)
    ctx.applyConstraints(1e-6)
    mm.LocalEnergyMinimizer.minimize(ctx, 10.0, 1000)
    ctx.setVelocitiesToTemperature(a.temperature * u.kelvin, a.seed)
    if a.equilibrate:
        integ.step(a.equilibrate)
    total_mass = float(np.sum(s.mass))
    rows = []
    traj = open(a.traj, "wb") if a.traj else None
    if traj:
        traj.write(b"VTRJ" + np.int32(s.n).tobytes())
    t0 = time.perf_counter()
    done = 0
    while done < a.steps:
        n = min(a.report - done % a.report, a.traj_every - done % a.traj_every if a.traj else a.steps, a.steps - done)  # stop at every report and every frame
        integ.step(n)
        done += n
        st = ctx.getState(getEnergy=True, getPositions=bool(a.traj) and done % a.traj_every == 0)
        box = st.getPeriodicBoxVectors(asNumpy=True).value_in_unit(u.nanometer)
        V = float(box[0][0] * box[1][1] * box[2][2])
        ke = st.getKineticEnergy().value_in_unit(u.kilojoule_per_mole)
        pe = st.getPotentialEnergy().value_in_unit(u.kilojoule_per_mole)
        dof = 3 * s.n - sysm.getNumConstraints() - 3
        rows.append((done, done * a.dt, pe, ke, pe + ke, 2 * ke / (dof * 0.00831446261815324), V, total_mass / AVOGADRO / (V * 1e-21)))
        if a.traj and done % a.traj_every == 0:
            xyz = st.getPositions(asNumpy=True).value_in_unit(u.nanometer).astype(np.float32)
            traj.write(np.int64(done).tobytes() + np.float64(done * a.dt).tobytes())
            traj.write(np.array([box[0][0], box[1][1], box[2][2]], dtype=np.float64).tobytes() + xyz.tobytes())
    secs = time.perf_counter() - t0
    if a.log:
        with open(a.log, "w") as f:
            f.write("step,time_ps,potential,kinetic,total,temperature,volume_nm3,density_g_cm3\n")
            for r in rows:
                f.write(",".join(f"{x:.6f}" if isinstance(x, float) else str(x) for x in r) + "\n")
    if traj:
        traj.close()
    print(json.dumps({"atoms": s.n, "steps": a.steps, "dt_ps": a.dt, "seconds": secs, "ns_per_day": a.steps * a.dt * 1e-3 / secs * 86400,
                      "platform": f"OpenMM {mm.__version__} {a.platform} {a.precision}"}))


if __name__ == "__main__":
    main()
