import * as THREE from 'three';

// Original procedural illustration: not a protein structure or a prediction.
export function createWorld(container, reduced) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' }); }
  catch { document.body.classList.add('fallback'); return { setProgress() {}, dispose() {} }; }
  renderer.setPixelRatio(Math.min(devicePixelRatio, innerWidth < 768 ? 1.25 : 1.75));
  renderer.setSize(innerWidth, innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2('#deb7b1', .027);
  const camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, .1, 100);
  camera.position.set(0, 2, 16);
  scene.add(new THREE.HemisphereLight('#fff2da', '#6d675c', 3));
  const key = new THREE.DirectionalLight('#fff1de', 5); key.position.set(-5, 8, 6); scene.add(key);
  const rim = new THREE.DirectionalLight('#eda5ac', 3); rim.position.set(5, 2, -5); scene.add(rim);
  const world = new THREE.Group(); scene.add(world);
  const pearl = new THREE.MeshStandardMaterial({ color: '#b7bd99', metalness: .38, roughness: .23 });
  const pink = new THREE.MeshStandardMaterial({ color: '#dba78e', metalness: .35, roughness: .28 });
  const bondMaterial = new THREE.MeshStandardMaterial({ color: '#c5ba98', metalness: .65, roughness: .27 });
  const sphere = new THREE.SphereGeometry(1, 32, 24);
  const cylinder = new THREE.CylinderGeometry(.045, .045, 1, 8);
  const positions = [];
  for (let i = 0; i < 34; i++) {
    const t = i * .66;
    const r = 2.1 + .55 * Math.sin(i * 1.7);
    const p = new THREE.Vector3(Math.cos(t) * r, (i / 33 - .5) * 5.8, Math.sin(t) * r);
    positions.push(p);
    const atom = new THREE.Mesh(sphere, i % 5 === 0 ? pink : pearl);
    atom.position.copy(p); atom.scale.setScalar(.28 + .23 * (.5 + .5 * Math.sin(i * 2.4)));
    world.add(atom);
    if (i > 0) connect(positions[i - 1], p);
    if (i > 8 && i % 3 === 0) connect(positions[i - 8], p);
  }
  function connect(a, b) {
    const bond = new THREE.Mesh(cylinder, bondMaterial);
    bond.position.copy(a).add(b).multiplyScalar(.5);
    bond.scale.y = a.distanceTo(b);
    bond.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
    world.add(bond);
  }
  const archMaterial = new THREE.MeshStandardMaterial({ color: '#c0baa0', roughness: .65 });
  const arch = new THREE.Mesh(new THREE.TorusGeometry(5.1, .3, 16, 100, Math.PI), archMaterial);
  arch.position.set(0, -2.5, -3); scene.add(arch);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(50, 64), new THREE.MeshStandardMaterial({ color: '#d4b1a1', roughness: .9 }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -4; scene.add(floor);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(3.6, .018, 6, 100), bondMaterial);
  ring.rotation.x = 1.2; world.add(ring);
  const dustGeometry = new THREE.BufferGeometry();
  const dust = new Float32Array(180 * 3);
  let seed = 19;
  const random = () => ((seed = (seed * 16807) % 2147483647) - 1) / 2147483646;
  for (let i = 0; i < dust.length; i++) dust[i] = (random() - .5) * 24;
  dustGeometry.setAttribute('position', new THREE.BufferAttribute(dust, 3));
  const particles = new THREE.Points(dustGeometry, new THREE.ShaderMaterial({ transparent: true, depthWrite: false,
    uniforms: { time: { value: 0 } },
    vertexShader: 'uniform float time; varying float alpha; void main(){vec3 p=position;p.y+=sin(time*.2+p.x)*.2;vec4 v=modelViewMatrix*vec4(p,1.);alpha=clamp(1.-(-v.z)/30.,0.,1.);gl_PointSize=clamp(28./(-v.z),1.,4.);gl_Position=projectionMatrix*v;}',
    fragmentShader: 'varying float alpha;void main(){float d=length(gl_PointCoord-.5);gl_FragColor=vec4(1.,.93,.8,(1.-smoothstep(.1,.5,d))*alpha*.65);}'
  })); scene.add(particles);
  let progress = 0, pointerX = 0, pointerY = 0, rotation = 0, dragging = false, lastX = 0, frame, disposed = false;
  function move(e) { pointerX = (e.clientX / innerWidth - .5) * 2; pointerY = (e.clientY / innerHeight - .5) * 2; if (dragging) { rotation += (e.clientX - lastX) * .008; lastX = e.clientX; } }
  function down(e) { if (e.clientY < innerHeight && !e.target.closest('a,button,input,textarea')) { dragging = true; lastX = e.clientX; } }
  function up() { dragging = false; }
  window.addEventListener('pointermove', move); window.addEventListener('pointerdown', down); window.addEventListener('pointerup', up); window.addEventListener('pointercancel', up);
  function resize() { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); if (reduced) draw(); }
  window.addEventListener('resize', resize);
  let lastTime = 0;
  function draw(ms = 0) {
    if (disposed) return;
    if (!document.hidden && scrollY < innerHeight * 2) {
      const dt = Math.min((ms - lastTime) / 1000, .05); lastTime = ms;
      const t = reduced ? 0 : ms * .001;
      world.rotation.y += ((rotation + t * .1 + progress * 2) - world.rotation.y) * .035;
      world.rotation.z = -.35 + (reduced ? 0 : Math.sin(t * .3) * .045);
      world.position.y = reduced ? 0 : Math.sin(t * .5) * .13;
      camera.position.x += (((reduced ? 0 : pointerX * .7) + progress * 2) - camera.position.x) * Math.min(dt * 3, 1);
      camera.position.y += ((1 + (reduced ? 0 : pointerY * .35) + progress * 2) - camera.position.y) * .04;
      camera.position.z = (innerWidth < 768 ? 20 : 16) - progress * 3;
      camera.lookAt(0, -.1, 0); particles.material.uniforms.time.value = t;
      renderer.render(scene, camera);
    }
    if (!reduced) frame = requestAnimationFrame(draw);
  }
  draw();
  return { setProgress(value) { progress = value; if (reduced) draw(); }, dispose() {
    disposed = true; cancelAnimationFrame(frame);
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerdown', down); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up); window.removeEventListener('resize', resize);
    const geometries = new Set(), materials = new Set(); scene.traverse(obj => { if (obj.geometry) geometries.add(obj.geometry); if (obj.material) materials.add(obj.material); });
    geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); renderer.dispose(); renderer.domElement.remove();
  } };
}
