#!/usr/bin/env python3
"""
audit_setup.py -- does what was actually RUN match what the Methods SAY?

For every system (Run1-4 and the negative control) it reads the real .tpr (via `gmx dump`) and the real
trajectory header (via MDAnalysis) and prints:

  A. composition: protein atoms, ligand, Zn, waters, ions, net charge, total atoms, box edge, protein/wall gap
  B. MD parameters from the .tpr (integrator, dt, run length, thermostat, barostat, cut-offs, constraints, ...)
     side by side, with a '*' on every parameter that is NOT identical in all systems
  C. a PASS/FAIL check of each parameter against the statements in the Methods
     (2 fs, LINCS on h-bonds, PME, 1.0 nm cut-offs, V-rescale, Parrinello-Rahman, 300 K, 1 bar, 20 ns)

Usage
-----
    conda activate tp53_md
    cd ~/tp53_md_project
    python audit_setup.py 2>&1 | tee audit_setup_report.txt
    python audit_setup.py --only Run1 NegCtrl
    python audit_setup.py --extra npt run1_20ns/npt.tpr --extra nvt nvt.tpr     # also dump equilibration tprs

Needs numpy, MDAnalysis and `gmx` on the PATH (the same environment as the other scripts).
Read-only.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from tp53_checks import DEFAULT_SYSTEMS
except Exception:                                                     # pragma: no cover
    DEFAULT_SYSTEMS = {}

KEYS = ["integrator", "dt", "nsteps", "continuation", "comm-mode",
        "tcoupl", "nsttcouple", "pcoupl", "pcoupltype", "nstpcouple", "tau-p",
        "cutoff-scheme", "coulombtype", "rcoulomb", "vdwtype", "vdw-modifier", "rvdw", "DispCorr",
        "fourierspacing", "pme-order", "ewald-rtol",
        "constraint-algorithm", "constraints", "lincs-order", "lincs-iter",
        "ld-seed", "gen-vel", "gen-temp", "gen-seed", "nstcalcenergy",
        "nstxout-compressed", "compressed-x-precision", "nstlist", "rlist"]
GRP_KEYS = ["ref-t", "tau-t", "nrdf", "ref-p"]

# statements of the Methods (Sci Rep / JMGM manuscript) -> expected value
CLAIMS = [
    ("integrator", "md", "leap-frog MD integrator"),
    ("dt", 0.002, "2-fs time step"),
    ("tcoupl", "V-rescale", "V-rescale thermostat"),
    ("pcoupl", "Parrinello-Rahman", "Parrinello-Rahman barostat (production)"),
    ("coulombtype", "PME", "PME electrostatics"),
    ("rcoulomb", 1.0, "1.0-nm electrostatic real-space cut-off"),
    ("rvdw", 1.0, "1.0-nm van der Waals cut-off"),
    ("constraints", "h-bonds", "constraints on hydrogen-containing bonds"),
    ("constraint-algorithm", "Lincs", "LINCS"),
]


def gmx_dump(tpr):
    if shutil.which("gmx") is None:
        sys.exit("gmx not found on PATH (conda activate tp53_md / install GROMACS)")
    r = subprocess.run(["gmx", "dump", "-s", tpr], capture_output=True, text=True)
    return r.stdout + "\n" + r.stderr


def parse_dump(text):
    vals, grp = {}, {}
    for line in text.splitlines():
        m = re.match(r"^\s+([A-Za-z0-9_\-]+)\s*=\s*(.*?)\s*$", line)
        if m and m.group(1) in KEYS and m.group(1) not in vals:
            vals[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^\s+(ref-t|tau-t|nrdf):\s*(.*?)\s*$", line)
        if m and m.group(1) not in grp:
            grp[m.group(1)] = re.sub(r"\s+", " ", m.group(2))
        m = re.match(r"^\s+ref-p\s*\(3x3\):\s*$", line)
    # reference pressure / compressibility are printed over several lines: take the first value after the key
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s+ref-p\s*\(3x3\):", line) and i + 1 < len(lines) and "ref-p" not in grp:
            grp["ref-p"] = re.sub(r"\s+", " ", lines[i + 1].strip())
    return vals, grp


def as_float(x):
    try:
        return float(str(x).split()[0])
    except (ValueError, IndexError):
        return None


def composition(top, traj):
    import MDAnalysis as mda
    u = mda.Universe(top, traj)
    prot = u.select_atoms("protein or resname HIE HID HIP HISE HISD HISH CYM CYX ASH GLH LYN")
    rn = np.array([r.resname for r in u.residues])
    comp = {"total atoms": len(u.atoms), "protein atoms": len(prot), "protein residues": len(prot.residues)}
    for nm in ("SOL", "CL", "NA", "ZN"):
        comp[f"n {nm}"] = int((rn == nm).sum())
    others = sorted(set(rn) - set(prot.resnames) - {"SOL", "CL", "NA", "ZN"})
    comp["ligand residue(s)"] = ",".join(others) if others else "none"
    for o in others:
        comp[f"atoms of {o}"] = int(len(u.select_atoms(f"resname {o}")))
    comp["net charge (e)"] = round(float(u.atoms.charges.sum()), 3) if hasattr(u.atoms, "charges") else "n/a"
    comp["protein net charge (e)"] = round(float(prot.charges.sum()), 3) if hasattr(prot, "charges") else "n/a"
    ts = u.trajectory[0]
    box = ts.dimensions[:3] / 10.0
    comp["box edge frame 0 (nm)"] = "x".join(f"{b:.3f}" for b in box)
    hp = u.select_atoms(f"({'protein'}) and not name H*").positions / 10.0
    comp["protein-to-wall gap, frame 0 (nm)"] = round(float(np.min(box - (hp.max(0) - hp.min(0)))) / 2.0, 3)
    comp["trajectory frames"] = len(u.trajectory)
    return comp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="~/tp53_md_project")
    ap.add_argument("--system", nargs=3, action="append", metavar=("NAME", "TOP", "TRAJ"))
    ap.add_argument("--extra", nargs=2, action="append", metavar=("NAME", "TPR"),
                    help="additional .tpr to dump (parameters only), e.g. equilibration runs")
    ap.add_argument("--only", nargs="+")
    a = ap.parse_args()

    root = os.path.expanduser(a.root)
    systems = {k: (os.path.join(root, v[0]), os.path.join(root, v[1])) for k, v in DEFAULT_SYSTEMS.items()}
    for nm, top, trj in (a.system or []):
        systems[nm] = (os.path.expanduser(top), os.path.expanduser(trj))
    if a.only:
        systems = {k: v for k, v in systems.items() if k in a.only}

    # ------------------------------------------------------------------ A. composition
    print("=" * 100)
    print("A. COMPOSITION OF THE SIMULATED SYSTEMS (from the .tpr and the first trajectory frame)")
    print("=" * 100)
    comps = {}
    for nm, (top, trj) in systems.items():
        if not (os.path.exists(top) and os.path.exists(trj)):
            print(f"[{nm}] skipped: file not found ({top} / {trj})")
            continue
        try:
            comps[nm] = composition(top, trj)
        except Exception as e:                                          # pragma: no cover
            print(f"[{nm}] composition failed: {e}")
    if comps:
        keys = list(next(iter(comps.values())).keys())
        for nm in comps:
            for k in comps[nm]:
                if k not in keys:
                    keys.append(k)
        w = 22
        print(f"{'':36s}" + "".join(f"{n:>{w}s}" for n in comps))
        for k in keys:
            row = [comps[n].get(k, "-") for n in comps]
            flag = "*" if len({str(r) for r in row}) > 1 and k not in ("trajectory frames",) else " "
            print(f"{flag} {k:34s}" + "".join(f"{str(r):>{w}s}" for r in row))
        print("  (* = differs between systems; Methods say: 46,082 atoms, 5 Cl-, 194 residues / 3010 protein atoms, "
              "7.72-nm cubic box, 1.2-nm minimum solute-wall distance)")

    # ------------------------------------------------------------------ B. parameters
    print("\n" + "=" * 100)
    print("B. MD PARAMETERS STORED IN THE .tpr FILES (gmx dump)")
    print("=" * 100)
    dumps = {}
    for nm, (top, trj) in systems.items():
        if top.endswith(".tpr") and os.path.exists(top):
            dumps[nm] = parse_dump(gmx_dump(top))
    for nm, tpr in (a.extra or []):
        p = os.path.expanduser(tpr)
        if os.path.exists(p):
            dumps[nm] = parse_dump(gmx_dump(p))
        else:
            print(f"[{nm}] extra tpr not found: {p}")
    if dumps:
        w = 22
        print(f"{'':30s}" + "".join(f"{n:>{w}s}" for n in dumps))
        for k in KEYS + GRP_KEYS:
            row = []
            for n in dumps:
                v, g = dumps[n]
                row.append(v.get(k, g.get(k, "-")))
            if all(r == "-" for r in row):
                continue
            flag = "*" if len({str(r) for r in row}) > 1 else " "
            print(f"{flag} {k:28s}" + "".join(f"{str(r)[:w-1]:>{w}s}" for r in row))
        for n in dumps:
            v = dumps[n][0]
            ns, dt = as_float(v.get("nsteps")), as_float(v.get("dt"))
            if ns is not None and dt is not None:
                print(f"  run length of {n}: nsteps x dt = {ns * dt:.1f} ps")

    # ------------------------------------------------------------------ C. claims
    print("\n" + "=" * 100)
    print("C. METHODS STATEMENTS vs THE .tpr FILES OF THE PRODUCTION RUNS")
    print("=" * 100)
    prod = [n for n in dumps if n in systems]
    fails = 0
    for key, exp, text in CLAIMS:
        for n in prod:
            got = dumps[n][0].get(key)
            if got is None:
                print(f"  ?     {n:8s} {text}: '{key}' not found in the dump")
                continue
            ok = (abs(as_float(got) - exp) < 1e-6) if isinstance(exp, float) else (str(got).lower() == str(exp).lower())
            fails += 0 if ok else 1
            print(f"  {'PASS' if ok else 'FAIL':5s} {n:8s} {text}: tpr says {got}")
    for n in prod:
        v, g = dumps[n]
        ns, dt = as_float(v.get("nsteps")), as_float(v.get("dt"))
        if ns is not None and dt is not None:
            ok = abs(ns * dt - 20000.0) < 1.0
            fails += 0 if ok else 1
            print(f"  {'PASS' if ok else 'FAIL':5s} {n:8s} 20-ns production: nsteps x dt = {ns * dt:.1f} ps")
        for k, exp in (("ref-t", 300.0), ):
            vals = [as_float(x) for x in g.get(k, "").split() if as_float(x) is not None]
            if vals:
                ok = all(abs(x - exp) < 1e-6 for x in vals)
                fails += 0 if ok else 1
                print(f"  {'PASS' if ok else 'FAIL':5s} {n:8s} reference temperature 300 K: tpr says {g.get(k)}")
    print(f"\nTOTAL FAIL: {fails}  (each FAIL is a place where the Methods text must be corrected, or the run repeated)")
    print("Note: 'differing only in the random seed' cannot be proven from the tpr alone; compare ld-seed/gen-seed above "
          "and run your compare_tpr_velocities.py / compare_initial_states.py (they test the velocities directly).")


if __name__ == "__main__":
    main()
