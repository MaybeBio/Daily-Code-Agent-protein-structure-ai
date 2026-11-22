// The page: pick a system, orbit, play the trajectory, show or hide water.

import { bounds, OrbitCamera } from "./math.js";
import { composition, ELEMENTS, frameGeometry, type Options, type Scene } from "./molecule.js";
import { Renderer } from "./render.js";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const canvas = $<HTMLCanvasElement>("view");
const camera = new OrbitCamera();
let renderer: Renderer;
let scene: Scene | null = null;
let frame = 0;
let playing = false;
let last = 0;
let acc = 0;
const opts: Options = { water: true, scale: 0.3 };

function rebuild() {
  if (!scene) return;
  renderer.upload(frameGeometry(scene, frame, opts));
  $("frame").textContent = `${scene.times[frame].toFixed(0)} ps (${frame + 1}/${scene.frames.length})`;
  $<HTMLInputElement>("time").value = String(frame);
}

async function load(file: string) {
  scene = (await (await fetch(`data/${file}`)).json()) as Scene;
  frame = 0;
  const slider = $<HTMLInputElement>("time");
  slider.max = String(scene.frames.length - 1);
  const b = bounds(scene.frames[0]);
  camera.fit(b.min, b.max);
  const c = composition(scene);
  const parts = Object.entries(c.counts).map(([e, n]) => `${n} ${e}`).join(", ");
  $("info").textContent = `${scene.elements.length} atoms (${parts}), ${c.waters} waters, box ${scene.box.map((v) => v.toFixed(2)).join(" × ")} nm`;
  $("notes").textContent = scene.notes ?? "";
  rebuild();
}

function loop(now: number) {
  if (playing && scene) {
    acc += now - last;
    if (acc > 60) {
      acc = 0;
      frame = (frame + 1) % scene.frames.length;
      rebuild();
    }
  }
  last = now;
  const aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
  renderer.draw(camera.matrix(aspect), 1 / Math.tan(camera.fovy / 2), [0.06, 0.07, 0.09]);
  requestAnimationFrame(loop);
}

function controls() {
  let drag: { x: number; y: number; pan: boolean } | null = null;
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (drag.pan) camera.pan(dx / canvas.clientHeight, dy / canvas.clientHeight);
    else camera.rotate(-dx * 0.008, dy * 0.008);
  });
  canvas.addEventListener("pointerup", () => (drag = null));
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    camera.zoom(Math.exp(e.deltaY * 0.001));
  }, { passive: false });
  $("play").addEventListener("click", () => {
    playing = !playing;
    $("play").textContent = playing ? "Pause" : "Play";
  });
  $<HTMLInputElement>("time").addEventListener("input", (e) => {
    frame = Number((e.target as HTMLInputElement).value);
    rebuild();
  });
  $<HTMLInputElement>("water").addEventListener("change", (e) => {
    opts.water = (e.target as HTMLInputElement).checked;
    rebuild();
  });
  $<HTMLSelectElement>("style").addEventListener("change", (e) => {
    opts.scale = Number((e.target as HTMLSelectElement).value);
    rebuild();
  });
  $("legend").innerHTML = Object.entries(ELEMENTS)
    .map(([e, v]) => `<li><span class="dot" style="background:rgb(${v.color.map((c) => Math.round(c * 255)).join(",")})"></span>${e}</li>`)
    .join("");
}

async function main() {
  try {
    renderer = new Renderer(canvas);
  } catch (err) {
    $("info").textContent = String(err);
    return;
  }
  controls();
  const index = (await (await fetch("data/index.json")).json()) as { file: string; name: string }[];
  const select = $<HTMLSelectElement>("scene");
  for (const s of index) {
    const o = document.createElement("option");
    o.value = s.file;
    o.textContent = s.name;
    select.appendChild(o);
  }
  select.addEventListener("change", () => load(select.value));
  await load(select.value);
  requestAnimationFrame(loop);
}

main();
