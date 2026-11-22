// Molecules as exported by eval/export_viewer.py, and the geometry of one
// frame: spheres (atoms) and line segments (bonds). No DOM or WebGL here.

import { hex, type RGB } from "./math.js";

export interface Scene {
  name: string;
  elements: string[];
  residues: string[]; // residue name of every atom
  bonds: number[]; // flat pairs of atom indices
  frames: number[][]; // flat x, y, z (nm) per frame
  times: number[]; // ps
  box: number[];
  notes?: string;
}

/** CPK-like colors and van der Waals radii (nm). */
export const ELEMENTS: Record<string, { color: RGB; radius: number }> = {
  H: { color: hex("#e8e8e8"), radius: 0.11 },
  C: { color: hex("#7f8a96"), radius: 0.17 },
  N: { color: hex("#3b6fd8"), radius: 0.155 },
  O: { color: hex("#e0453a"), radius: 0.152 },
  S: { color: hex("#e8c33a"), radius: 0.18 },
  Na: { color: hex("#8d5bd6"), radius: 0.227 },
  Cl: { color: hex("#3fb37f"), radius: 0.175 },
};
const UNKNOWN = { color: hex("#d050d0"), radius: 0.15 };

export const isWater = (res: string) => res === "HOH" || res === "WAT";

export interface Options {
  water: boolean;
  scale: number; // fraction of the van der Waals radius (0.25: ball and stick)
}

export interface Geometry {
  spheres: Float32Array; // per atom: x y z radius r g b
  lines: Float32Array; // per vertex: x y z r g b
}

/** The atoms shown and their spheres, and the bonds between shown atoms, for one frame. */
export function frameGeometry(s: Scene, frame: number, o: Options): Geometry {
  const x = s.frames[Math.max(0, Math.min(frame, s.frames.length - 1))];
  const shown = s.elements.map((_, i) => o.water || !isWater(s.residues[i]));
  const sph: number[] = [];
  for (let i = 0; i < s.elements.length; i++) {
    if (!shown[i]) continue;
    const e = ELEMENTS[s.elements[i]] ?? UNKNOWN;
    sph.push(x[3 * i], x[3 * i + 1], x[3 * i + 2], e.radius * o.scale, ...e.color);
  }
  const lin: number[] = [];
  for (let k = 0; k + 1 < s.bonds.length; k += 2) {
    const a = s.bonds[k], b = s.bonds[k + 1];
    if (!shown[a] || !shown[b]) continue;
    // half a bond in each atom's color; skip bonds broken by the periodic box
    const pa = [x[3 * a], x[3 * a + 1], x[3 * a + 2]], pb = [x[3 * b], x[3 * b + 1], x[3 * b + 2]];
    if (Math.hypot(pa[0] - pb[0], pa[1] - pb[1], pa[2] - pb[2]) > 0.3) continue;
    const mid = [(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2, (pa[2] + pb[2]) / 2];
    const ca = (ELEMENTS[s.elements[a]] ?? UNKNOWN).color, cb = (ELEMENTS[s.elements[b]] ?? UNKNOWN).color;
    lin.push(...pa, ...ca, ...mid, ...ca, ...mid, ...cb, ...pb, ...cb);
  }
  return { spheres: new Float32Array(sph), lines: new Float32Array(lin) };
}

/** Composition: atom count per element and the number of waters. */
export function composition(s: Scene): { counts: Record<string, number>; waters: number } {
  const counts: Record<string, number> = {};
  for (const e of s.elements) counts[e] = (counts[e] ?? 0) + 1;
  const waters = s.residues.filter((r, i) => isWater(r) && s.elements[i] === "O").length;
  return { counts, waters };
}
