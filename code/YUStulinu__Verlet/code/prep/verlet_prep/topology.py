"""The engine's input: a plain-text topology (.vsys) with every parameter and
the starting positions. Units: nm, amu, e, kJ/mol, radians."""

from __future__ import annotations

import numpy as np

from .forcefield import System

MAGIC = "verlet-system 1"


def write_vsys(path: str, s: System):
    with open(path, "w") as f:
        f.write(MAGIC + "\n")
        f.write("box %.10f %.10f %.10f\n" % tuple(s.box))
        f.write(f"atoms {s.n}\n")
        for i in range(s.n):
            f.write("%s %s %d %s %s %.6f %.8f %.10f %.10f %.6f %.6f %.6f\n" % (
                s.names[i], s.resnames[i], s.resids[i], s.chains[i].strip() or "_", s.elements[i], s.mass[i], s.charge[i],
                s.sigma[i], s.epsilon[i], *s.xyz[i]))
        f.write(f"bonds {len(s.bonds)}\n")
        for i, j, r0, k in s.bonds:
            f.write(f"{i} {j} {r0:.10f} {k:.6f}\n")
        f.write(f"angles {len(s.angles)}\n")
        for i, j, k, th, kk in s.angles:
            f.write(f"{i} {j} {k} {th:.12f} {kk:.6f}\n")
        f.write(f"torsions {len(s.torsions)}\n")
        for i, j, k, l, n, ph, kk in s.torsions:
            f.write(f"{i} {j} {k} {l} {n} {ph:.12f} {kk:.6f}\n")
        f.write(f"pairs14 {len(s.pairs14)}\n")
        for i, j, q, sg, e in s.pairs14:
            f.write(f"{i} {j} {q:.10f} {sg:.10f} {e:.10f}\n")
        f.write(f"exclusions {len(s.exclusions)}\n")
        for i, j in s.exclusions:
            f.write(f"{i} {j}\n")
        f.write(f"constraints {len(s.constraints)}\n")
        for i, j, d in s.constraints:
            f.write(f"{i} {j} {d:.10f}\n")
        f.write(f"waters {len(s.waters)} {s.water_geometry[0]:.10f} {s.water_geometry[1]:.10f}\n")
        for o, h1, h2 in s.waters:
            f.write(f"{o} {h1} {h2}\n")
        f.write(f"molecules {len(s.molecules) - 1}\n")
        f.write(" ".join(str(m) for m in s.molecules) + "\n")


def read_vsys(path: str) -> System:
    with open(path) as f:
        lines = f.read().split("\n")
    assert lines[0] == MAGIC
    p = 1
    box = np.array([float(x) for x in lines[p].split()[1:]])
    p += 1
    n = int(lines[p].split()[1])
    p += 1
    rows = [lines[p + i].split() for i in range(n)]
    p += n
    s = System(
        names=[r[0] for r in rows], resnames=[r[1] for r in rows], resids=[int(r[2]) for r in rows], chains=[r[3] for r in rows],
        elements=[r[4] for r in rows], mass=np.array([float(r[5]) for r in rows]), charge=np.array([float(r[6]) for r in rows]),
        sigma=np.array([float(r[7]) for r in rows]), epsilon=np.array([float(r[8]) for r in rows]),
        xyz=np.array([[float(x) for x in r[9:12]] for r in rows]), box=box,
    )

    def section(name, conv):
        nonlocal p
        head = lines[p].split()
        assert head[0] == name, (head, name)
        m = int(head[1])
        out = [tuple(c(x) for c, x in zip(conv, lines[p + 1 + i].split())) for i in range(m)]
        p += 1 + m
        return out, head

    s.bonds, _ = section("bonds", (int, int, float, float))
    s.angles, _ = section("angles", (int, int, int, float, float))
    s.torsions, _ = section("torsions", (int, int, int, int, int, float, float))
    s.pairs14, _ = section("pairs14", (int, int, float, float, float))
    s.exclusions, _ = section("exclusions", (int, int))
    s.constraints, _ = section("constraints", (int, int, float))
    s.waters, head = section("waters", (int, int, int))
    s.water_geometry = (float(head[2]), float(head[3]))
    s.molecules = [int(x) for x in lines[p + 1].split()]
    return s


def with_positions(s: System, xyz: np.ndarray, box=None) -> System:
    import copy

    t = copy.copy(s)
    t.xyz = np.asarray(xyz, float)
    if box is not None:
        t.box = np.asarray(box, float)
    return t
