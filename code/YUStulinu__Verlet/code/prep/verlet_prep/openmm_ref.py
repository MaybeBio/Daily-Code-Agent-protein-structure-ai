"""OpenMM as the reference: the same system built from our parameters (to
check the engine), or by OpenMM's own ForceField from the PDB (to check our
parameter assignment). OpenMM is used only for comparison."""

from __future__ import annotations

import glob
import os
import site

import numpy as np


def _dll_dirs():
    # pip's CUDA libraries are not on the DLL search path on Windows
    if os.name == "nt":
        for sp in site.getsitepackages():
            for d in glob.glob(os.path.join(sp, "nvidia", "*", "bin")):
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]


_dll_dirs()
import openmm as mm  # noqa: E402
import openmm.app as app  # noqa: E402
import openmm.unit as u  # noqa: E402

from .forcefield import System  # noqa: E402

# OpenMM's value of 1/(4 pi eps0) in kJ mol^-1 nm e^-2
ONE_4PI_EPS0 = 138.935456


def openmm_system(s: System, cutoff=0.9, method="PME", ewald_tol=5e-4, dispersion=True) -> mm.System:
    """An OpenMM System with exactly our parameters, one force group per term."""
    sysm = mm.System()
    for m in s.mass:
        sysm.addParticle(m)
    sysm.setDefaultPeriodicBoxVectors(mm.Vec3(s.box[0], 0, 0), mm.Vec3(0, s.box[1], 0), mm.Vec3(0, 0, s.box[2]))
    hb = mm.HarmonicBondForce()
    for i, j, r0, k in s.bonds:
        hb.addBond(i, j, r0, k)
    ha = mm.HarmonicAngleForce()
    for i, j, k, th, kk in s.angles:
        ha.addAngle(i, j, k, th, kk)
    pt = mm.PeriodicTorsionForce()
    for i, j, k, l, n, ph, kk in s.torsions:
        pt.addTorsion(i, j, k, l, n, ph, kk)
    nb = mm.NonbondedForce()
    nb.setNonbondedMethod({"PME": mm.NonbondedForce.PME, "NoCutoff": mm.NonbondedForce.NoCutoff, "Ewald": mm.NonbondedForce.Ewald}[method])
    if method != "NoCutoff":
        nb.setCutoffDistance(cutoff)
        nb.setEwaldErrorTolerance(ewald_tol)
    nb.setUseDispersionCorrection(dispersion)
    for q, sg, e in zip(s.charge, s.sigma, s.epsilon):
        nb.addParticle(q, sg, e)
    p14 = {(i, j): (q, sg, e) for i, j, q, sg, e in s.pairs14}
    for i, j in s.exclusions:
        q, sg, e = p14.get((i, j), (0.0, 1.0, 0.0))
        nb.addException(i, j, q, sg, e)
    for k, f in enumerate((hb, ha, pt, nb)):
        f.setForceGroup(k)
        sysm.addForce(f)
    for i, j, d in s.constraints:
        sysm.addConstraint(i, j, d)
    doh, dhh = s.water_geometry
    for o, h1, h2 in s.waters:
        sysm.addConstraint(o, h1, doh)
        sysm.addConstraint(o, h2, doh)
        sysm.addConstraint(h1, h2, dhh)
    return sysm


def platform(name="CUDA"):
    return mm.Platform.getPlatformByName(name)


def energies(sysm: mm.System, xyz, box=None, platform_name="Reference", precision=None):
    """Energy of each force group (kJ/mol) and the forces (kJ/mol/nm)."""
    integ = mm.VerletIntegrator(0.001)
    props = {"Precision": precision} if precision else {}
    ctx = mm.Context(sysm, integ, platform(platform_name), props)
    if box is not None:
        ctx.setPeriodicBoxVectors(mm.Vec3(box[0], 0, 0), mm.Vec3(0, box[1], 0), mm.Vec3(0, 0, box[2]))
    ctx.setPositions(np.asarray(xyz))
    out = {}
    names = ["bond", "angle", "torsion", "nonbonded"]
    for g, name in enumerate(names):
        st = ctx.getState(getEnergy=True, groups={g})
        out[name] = st.getPotentialEnergy().value_in_unit(u.kilojoule_per_mole)
    st = ctx.getState(getEnergy=True, getForces=True)
    out["total"] = st.getPotentialEnergy().value_in_unit(u.kilojoule_per_mole)
    forces = st.getForces(asNumpy=True).value_in_unit(u.kilojoule_per_mole / u.nanometer)
    return out, np.asarray(forces)


def openmm_forcefield_system(pdb_path: str, ff_files, box=None, method="NoCutoff", cutoff=0.9):
    """OpenMM's own parameter assignment from a PDB (for checking ours)."""
    pdb = app.PDBFile(pdb_path)
    ff = app.ForceField(*ff_files)
    top = pdb.topology
    if box is not None:
        top.setPeriodicBoxVectors(((box[0], 0, 0), (0, box[1], 0), (0, 0, box[2])))
    kw = {"nonbondedMethod": getattr(app, method), "constraints": app.HBonds, "rigidWater": True}
    if method != "NoCutoff":
        kw["nonbondedCutoff"] = cutoff * u.nanometer
    sysm = ff.createSystem(top, **kw)
    for f in sysm.getForces():
        f.setForceGroup({"HarmonicBondForce": 0, "HarmonicAngleForce": 1, "PeriodicTorsionForce": 2, "NonbondedForce": 3}.get(type(f).__name__, 5))
    return sysm, pdb.positions
