// WebGL2: atoms as sphere impostors (point sprites shaded as spheres, sized
// by perspective) and bonds as lines.

import type { Mat4 } from "./math.js";
import type { Geometry } from "./molecule.js";

const SPHERE_VS = `#version 300 es
in vec4 a; // x y z radius
in vec3 col;
uniform mat4 mvp;
uniform float viewport_h; // pixels
uniform float proj_y;     // projection[1][1]
out vec3 v_col;
void main() {
  gl_Position = mvp * vec4(a.xyz, 1.0);
  gl_PointSize = max(2.0, 2.0 * a.w * proj_y * viewport_h * 0.5 / gl_Position.w);
  v_col = col;
}`;

const SPHERE_FS = `#version 300 es
precision mediump float;
in vec3 v_col;
out vec4 color;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float r2 = dot(p, p);
  if (r2 > 1.0) discard;
  vec3 n = vec3(p.x, -p.y, sqrt(1.0 - r2));
  float diffuse = max(dot(n, normalize(vec3(0.4, 0.6, 0.7))), 0.0);
  float rim = pow(1.0 - n.z, 3.0);
  color = vec4(v_col * (0.35 + 0.75 * diffuse) + 0.15 * rim, 1.0);
}`;

const LINE_VS = `#version 300 es
in vec3 pos;
in vec3 col;
uniform mat4 mvp;
out vec3 v_col;
void main() { gl_Position = mvp * vec4(pos, 1.0); v_col = col; }`;

const LINE_FS = `#version 300 es
precision mediump float;
in vec3 v_col;
out vec4 color;
void main() { color = vec4(v_col, 1.0); }`;

function program(gl: WebGL2RenderingContext, vs: string, fs: string): WebGLProgram {
  const p = gl.createProgram()!;
  for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]] as const) {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
    gl.attachShader(p, s);
  }
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "link");
  return p;
}

export class Renderer {
  private gl: WebGL2RenderingContext;
  private sphereProg: WebGLProgram;
  private lineProg: WebGLProgram;
  private sphereBuf: WebGLBuffer;
  private lineBuf: WebGLBuffer;
  private nSpheres = 0;
  private nLines = 0;

  constructor(private canvas: HTMLCanvasElement) {
    const gl = canvas.getContext("webgl2", { antialias: true });
    if (!gl) throw new Error("WebGL2 is not available");
    this.gl = gl;
    this.sphereProg = program(gl, SPHERE_VS, SPHERE_FS);
    this.lineProg = program(gl, LINE_VS, LINE_FS);
    this.sphereBuf = gl.createBuffer()!;
    this.lineBuf = gl.createBuffer()!;
    gl.enable(gl.DEPTH_TEST);
  }

  upload(g: Geometry) {
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.sphereBuf);
    gl.bufferData(gl.ARRAY_BUFFER, g.spheres, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuf);
    gl.bufferData(gl.ARRAY_BUFFER, g.lines, gl.DYNAMIC_DRAW);
    this.nSpheres = g.spheres.length / 7;
    this.nLines = g.lines.length / 6;
  }

  draw(mvp: Mat4, projY: number, background: [number, number, number]) {
    const gl = this.gl;
    const dpr = window.devicePixelRatio || 1;
    const w = Math.round(this.canvas.clientWidth * dpr), h = Math.round(this.canvas.clientHeight * dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    gl.viewport(0, 0, w, h);
    gl.clearColor(background[0], background[1], background[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (this.nLines) {
      gl.useProgram(this.lineProg);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.lineProg, "mvp"), false, mvp);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.lineBuf);
      this.attrib(this.lineProg, "pos", 3, 24, 0);
      this.attrib(this.lineProg, "col", 3, 24, 12);
      gl.drawArrays(gl.LINES, 0, this.nLines);
    }
    if (this.nSpheres) {
      gl.useProgram(this.sphereProg);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.sphereProg, "mvp"), false, mvp);
      gl.uniform1f(gl.getUniformLocation(this.sphereProg, "viewport_h"), h);
      gl.uniform1f(gl.getUniformLocation(this.sphereProg, "proj_y"), projY);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.sphereBuf);
      this.attrib(this.sphereProg, "a", 4, 28, 0);
      this.attrib(this.sphereProg, "col", 3, 28, 16);
      gl.drawArrays(gl.POINTS, 0, this.nSpheres);
    }
  }

  private attrib(p: WebGLProgram, name: string, size: number, stride: number, offset: number) {
    const gl = this.gl;
    const loc = gl.getAttribLocation(p, name);
    if (loc < 0) return;
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, offset);
  }
}
