"""Export a system and its trajectory for the viewer (viewer/data/<name>.json).

    python eval/export_viewer.py SYSTEM.vsys TRAJ.vtrj NAME "Title" [--frames 60] [--notes "..."]

Molecules are made whole and put into the box, centered on the solute
(the non-water atoms) when there is one.
"""

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prep"))
from verlet_prep.topology import read_vsys  # noqa: E402


def read_vtrj(path, n):
    raw = open(path, "rb").read()
    assert raw[:4] == b"VTRJ" and int(np.frombuffer(raw[4:8], np.int32)[0]) == n
    size = 8 + 8 + 24 + 12 * n
    frames = []
    for off in range(8, len(raw) - size + 1, size):
        t = float(np.frombuffer(raw[off + 8 : off + 16], np.float64)[0])
        box = np.frombuffer(raw[off + 16 : off + 40], np.float64).copy()
        xyz = np.frombuffer(raw[off + 40 : off + size], np.float32).reshape(n, 3).astype(np.float64)
        frames.append((t, box, xyz))
    return frames


def wrap(s, xyz, box, center):
    x = xyz.copy()
    m = s.molecules
    for a, b in zip(m[:-1], m[1:]):
        d = x[a:b] - x[a]
        x[a:b] = x[a] + d - box * np.round(d / box)  # whole molecule
        c = x[a:b].mean(0)
        x[a:b] -= box * np.floor((c - center) / box + 0.5)  # its center into the box around `center`
    return x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vsys")
    ap.add_argument("traj")
    ap.add_argument("name")
    ap.add_argument("title")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--notes", default="")
    a = ap.parse_args()
    s = read_vsys(a.vsys)
    frames = read_vtrj(a.traj, s.n)
    keep = np.unique(np.linspace(0, len(frames) - 1, min(a.frames, len(frames))).astype(int))
    solute = [i for i in range(s.n) if s.resnames[i] not in ("HOH", "WAT")]
    out = []
    for k in keep:
        t, box, xyz = frames[k]
        center = xyz[solute].mean(0) if solute else box / 2
        x = wrap(s, xyz, box, center) - center + box / 2
        out.append([round(float(v), 3) for v in x.ravel()])
    # every chemical bond: harmonic bonds, constrained X-H bonds and the two O-H of each water
    pairs = [(i, j) for i, j, *_ in s.bonds] + [(i, j) for i, j, _ in s.constraints]
    for o, h1, h2 in s.waters:
        pairs += [(o, h1), (o, h2)]
    bonds = [int(v) for p in pairs for v in p]
    scene = {
        "name": a.title, "elements": s.elements, "residues": s.resnames, "bonds": bonds, "frames": out,
        "times": [round(frames[k][0], 2) for k in keep], "box": [round(float(v), 3) for v in frames[keep[-1]][1]], "notes": a.notes,
    }
    d = os.path.join(ROOT, "viewer", "data")
    os.makedirs(d, exist_ok=True)
    json.dump(scene, open(os.path.join(d, a.name + ".json"), "w"), separators=(",", ":"))
    idx_path = os.path.join(d, "index.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else []
    index = [e for e in index if e["file"] != a.name + ".json"] + [{"file": a.name + ".json", "name": a.title}]
    json.dump(index, open(idx_path, "w"), indent=1)
    print(f"{a.name}: {len(keep)} frames, {s.n} atoms")


if __name__ == "__main__":
    main()
