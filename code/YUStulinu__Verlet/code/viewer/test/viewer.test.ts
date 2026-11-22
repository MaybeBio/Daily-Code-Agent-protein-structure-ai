import { test } from "node:test";
import assert from "node:assert/strict";

import { composition, frameGeometry, type Scene } from "../src/molecule.js";

// a water and a methane-like fragment
const scene: Scene = {
  name: "t",
  elements: ["O", "H", "H", "C", "H"],
  residues: ["HOH", "HOH", "HOH", "MET", "MET"],
  bonds: [0, 1, 0, 2, 3, 4],
  frames: [[0, 0, 0, 0.096, 0, 0, -0.024, 0.093, 0, 1, 1, 1, 1.109, 1, 1], [0, 0, 0, 0.096, 0, 0, -0.024, 0.093, 0, 1, 1, 1, 3, 3, 3]],
  times: [0, 1],
  box: [4, 4, 4],
};

test("every atom is a sphere and every bond two half segments", () => {
  const g = frameGeometry(scene, 0, { water: true, scale: 1 });
  assert.equal(g.spheres.length / 7, 5);
  assert.equal(g.lines.length / 6, 3 * 4);
  // the oxygen's radius and color come from the element table
  assert.ok(Math.abs(g.spheres[3] - 0.152) < 1e-6);
  assert.ok(g.spheres[4] > g.spheres[5]);
});

test("hiding water removes its atoms and bonds", () => {
  const g = frameGeometry(scene, 0, { water: false, scale: 0.5 });
  assert.equal(g.spheres.length / 7, 2);
  assert.equal(g.lines.length / 6, 4);
  assert.ok(Math.abs(g.spheres[3] - 0.17 * 0.5) < 1e-6);
});

test("bonds stretched across the periodic box are not drawn", () => {
  const g = frameGeometry(scene, 1, { water: false, scale: 1 });
  assert.equal(g.lines.length, 0);
});

test("frame index is clamped and composition counts waters", () => {
  assert.equal(frameGeometry(scene, 99, { water: true, scale: 1 }).spheres[4 * 7], 3); // last frame: the 5th atom at x = 3
  const c = composition(scene);
  assert.deepEqual(c.counts, { O: 1, H: 3, C: 1 });
  assert.equal(c.waters, 1);
});
