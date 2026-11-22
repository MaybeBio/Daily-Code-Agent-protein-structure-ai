#!/usr/bin/env python3
"""
check_stage_structures.py -- ligand-site distance and Zn2+ coordination in any stage structure (minimisation, NVT, NPT, complex.gro ...)

For every requested structure it prints
  * the distance (minimum image) between the centre of mass of the ligand and the centre of mass of the C-alpha atoms of the nine
    residues of the docked site (internal numbering 7, 9, 15, 16, 31, 36, 173, 174, 175 = PDB 102, 104, 110, 111, 126, 131, 268, 269, 270)
  * the minimum heavy-atom distance between the ligand and these nine residues
  * the minimum-image distances of the Zn2+ ion to Cys176 Sg, His179 Nd1, Cys238 Sg, Cys242 Sg and to the nearest protein atom

Usage (inside the conda environment tp53_md, in ~/tp53_md_project)
    python check_stage_structures.py --stage EM  negative_control/em.gro
    python check_stage_structures.py --stage NVT nvt.tpr nvt.trr --times 0 10 20 50 100
    python check_stage_structures.py --stage NPT npt.tpr npt.trr --times 0 50 100
A stage is: LABEL TOPOLOGY [TRAJECTORY].  Without a trajectory the single structure is used.  With a trajectory the frames nearest to
--times (ps) are used (default 0 10 20 50 100 200).  Read-only.
"""
import argparse
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tp53_checks import NOT_LIGAND, POCKET, PROT_SEL, resolve_numbering  # noqa: E402

ZN_LIG = [(176, "SG", "Cys176 SG"), (179, "ND1", "His179 ND1"), (238, "SG", "Cys238 SG"), (242, "SG", "Cys242 SG")]


def mic_vec(d, box):
    return d - box * np.round(d / box)


def mic_com(pos, mass, box):
    ref = pos[0]
    d = mic_vec(pos - ref, box)
    return ref + (mass[:, None] * d).sum(0) / mass.sum()


def mic_min_dist(a, b, box):
    best = 1e9
    for p in a:
        d = mic_vec(b - p, box)
        best = min(best, float(np.sqrt((d ** 2).sum(1)).min()))
    return best


def report(u, label, ts):
    box = ts.dimensions[:3].astype(float)
    shift, _, _ = resolve_numbering(u, POCKET)
    shift = 0 if shift is None else shift
    out = [f"  {label}  t = {ts.time:8.2f} ps   box {box[0] / 10:.3f} nm"]
    prot = u.select_atoms(PROT_SEL)
    lig = u.select_atoms(f"not ({NOT_LIGAND})")
    pk_res = " ".join(str(r - shift) for r in POCKET)
    ca = u.select_atoms(f"({PROT_SEL}) and resid {pk_res} and name CA")
    if len(lig) and len(ca):
        pos_l, pos_c = lig.positions.astype(float), ca.positions.astype(float)
        cl = mic_com(pos_l, np.maximum(lig.masses, 1e-3), box)
        cc = mic_com(pos_c, np.ones(len(ca)), box)
        spread = float(np.abs(mic_vec(pos_c - pos_c[0], box)).max()) / 10.0
        if spread > 0.45 * box.min() / 10.0:
            out.append(f"      [warning] the nine site residues are spread over {spread:.1f} nm (> 0.45 box): the minimum-image centre is unreliable here")
        d_com = float(np.linalg.norm(mic_vec(cl - cc, box))) / 10.0
        pk_heavy = u.select_atoms(f"({PROT_SEL}) and resid {pk_res} and not name H*").positions.astype(float)
        lig_heavy = lig.select_atoms("not name H*").positions.astype(float)
        d_min = mic_min_dist(lig_heavy, pk_heavy, box) / 10.0
        out.append(f"      ligand {lig.resnames[0]} ({len(lig)} atoms): COM distance to the site {d_com:.2f} nm; minimum heavy-atom distance to the nine residues {d_min:.2f} nm")
    else:
        out.append(f"      ligand/site not found (ligand atoms {len(lig)}, site C-alpha atoms {len(ca)})")
    zn = u.select_atoms("resname ZN")
    if len(zn) == 1:
        zp = zn.positions[0].astype(float)
        parts = []
        for pdb, an, name in ZN_LIG:
            g = u.select_atoms(f"({PROT_SEL}) and resid {pdb - shift} and name {an}")
            if len(g) == 1:
                parts.append(f"{name} {np.linalg.norm(mic_vec(g.positions[0].astype(float) - zp, box)):.2f}")
        heavy = u.select_atoms(f"({PROT_SEL}) and not name H*").positions.astype(float)
        near = float(np.sqrt((mic_vec(heavy - zp, box) ** 2).sum(1)).min())
        out.append("      Zn2+ distances (A): " + "  ".join(parts) + f"  | nearest protein atom {near:.2f}")
    else:
        out.append("      no single Zn2+ ion found")
    print("\n".join(out))


def main():
    import MDAnalysis as mda
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", nargs="+", action="append", metavar="ARG", help="LABEL TOPOLOGY [TRAJECTORY]")
    ap.add_argument("--times", nargs="+", type=float, default=[0, 10, 20, 50, 100, 200], help="ps, for trajectories")
    a = ap.parse_args()
    if not a.stage:
        ap.error("give at least one --stage")
    for st in a.stage:
        label, top = st[0], os.path.expanduser(st[1])
        traj = os.path.expanduser(st[2]) if len(st) > 2 else None
        for f in (top, traj):
            if f and not os.path.exists(f):
                print(f"[{label}] file not found: {f}   (find it with: find ~/tp53_md_project -name '{os.path.basename(f)}')")
                break
        else:
            u = mda.Universe(top, traj) if traj else mda.Universe(top)
            print(f"\n[{label}] {top}" + (f" + {traj}" if traj else ""))
            if not traj:
                report(u, label, u.trajectory.ts)
            else:
                times = np.array([ts.time for ts in u.trajectory])
                print(f"  trajectory: {len(times)} frames, {times[0]:.2f} to {times[-1]:.2f} ps")
                done = set()
                for t in a.times:
                    i = int(np.argmin(np.abs(times - t)))
                    if i in done:
                        continue
                    done.add(i)
                    report(u, label, u.trajectory[i])


if __name__ == "__main__":
    main()
