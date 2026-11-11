import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

const $ = (id) => document.getElementById(id);
const state = { printers: [], examples: [], params: {}, lastBuild: null };

// ------------------------------------------------------------------ viewer
const viewer = $("viewer");
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
viewer.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1e23);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.up.set(0, 0, 1); // Z is up, like a printer
camera.position.set(200, -250, 180);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0, 50);
scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.2);
sun.position.set(150, -100, 300);
scene.add(sun);

const modelGroup = new THREE.Group();
const volumeGroup = new THREE.Group();
scene.add(modelGroup, volumeGroup);

function resize() {
  const w = viewer.clientWidth, h = viewer.clientHeight;
  if (w === 0 || h === 0) return;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(viewer);
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();

function clearGroup(g) {
  for (const child of [...g.children]) {
    g.remove(child);
    child.geometry?.dispose();
    child.material?.dispose();
  }
}

function drawBuildVolume(printer) {
  clearGroup(volumeGroup);
  const [x, y, z] = printer.volume;
  const box = new THREE.BoxGeometry(x, y, z);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box), new THREE.LineBasicMaterial({ color: 0x3b82f6 }));
  edges.position.set(0, 0, z / 2);
  const bed = new THREE.GridHelper(Math.max(x, y), 10, 0x3b82f6, 0x343a44);
  bed.rotation.x = Math.PI / 2;
  volumeGroup.add(edges, bed);
  box.dispose();
}

function drawMesh(mesh, overhangFaces) {
  clearGroup(modelGroup);
  const v = mesh.vertices, idx = mesh.indices, faceCount = idx.length / 3;
  const bad = new Set(overhangFaces);
  const pos = new Float32Array(faceCount * 9), col = new Float32Array(faceCount * 9);
  let minZ = Infinity, minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (let i = 0; i < v.length; i += 3) {
    minX = Math.min(minX, v[i]); maxX = Math.max(maxX, v[i]);
    minY = Math.min(minY, v[i + 1]); maxY = Math.max(maxY, v[i + 1]);
    minZ = Math.min(minZ, v[i + 2]);
  }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  for (let f = 0; f < faceCount; f++) {
    const c = bad.has(f) ? [0.94, 0.27, 0.27] : [0.6, 0.69, 0.78];
    for (let k = 0; k < 3; k++) {
      const vi = idx[f * 3 + k] * 3, o = f * 9 + k * 3;
      pos[o] = v[vi] - cx; pos[o + 1] = v[vi + 1] - cy; pos[o + 2] = v[vi + 2] - minZ; // drop onto the bed
      col[o] = c[0]; col[o + 1] = c[1]; col[o + 2] = c[2];
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.computeVertexNormals();
  modelGroup.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.05 })));
}

// ------------------------------------------------------------------ UI helpers
function option(select, value, label) {
  const o = document.createElement("option");
  o.value = value; o.textContent = label;
  select.appendChild(o);
}

function setStatus(text, isError = false) {
  const s = $("status");
  s.textContent = text;
  s.classList.toggle("error", isError);
}

function row(label, value, cls = "") {
  const tr = document.createElement("tr");
  const a = document.createElement("td"), b = document.createElement("td");
  a.textContent = label; b.textContent = value;
  if (cls) b.className = cls;
  tr.append(a, b);
  return tr;
}

function renderAnalysis(a) {
  const root = $("analysis");
  root.replaceChildren();
  const t = document.createElement("table");
  const s = a.bounding_box.size;
  t.append(
    row("Size (mm)", `${s[0].toFixed(1)} x ${s[1].toFixed(1)} x ${s[2].toFixed(1)}`),
    row("Volume", `${(a.volume / 1000).toFixed(2)} cm3`),
    row("Weight (solid)", `${a.weight.solid_grams.toFixed(1)} g`),
    row("Weight (est.)", `${a.weight.estimated_grams.toFixed(1)} g @ ${(a.weight.infill * 100).toFixed(0)}% infill`),
    row("Watertight", a.watertight ? "yes" : "NO", a.watertight ? "good" : "warn"),
    row("Manifold", a.manifold ? "yes" : "NO", a.manifold ? "good" : "warn"),
    row("Fits printer", a.build_volume.fits ? "yes" : (a.build_volume.fits_rotated ? "if rotated" : "NO"), a.build_volume.fits ? "good" : "warn"),
    row("Overhang area", `${(a.overhang.fraction * 100).toFixed(1)}%`),
    row("Min wall (est.)", a.min_wall_thickness == null ? "n/a" : `${a.min_wall_thickness.toFixed(2)} mm`),
    row("Best orientation", a.orientation.best),
    row("Triangles", String(a.triangle_count)),
  );
  root.appendChild(t);
  if (a.warnings.length) {
    const ul = document.createElement("ul");
    ul.className = "warnings";
    for (const w of a.warnings) { const li = document.createElement("li"); li.textContent = w; ul.appendChild(li); }
    root.appendChild(ul);
  }
}

function renderParams(params) {
  const root = $("params");
  root.replaceChildren();
  if (!params.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "This script declares no parameters.";
    root.appendChild(p);
    return;
  }
  for (const p of params) {
    const wrap = document.createElement("label");
    wrap.className = "param";
    const name = document.createElement("span");
    name.textContent = p.name;
    const input = document.createElement("input");
    if (p.type === "bool") { input.type = "checkbox"; input.checked = !!p.value; }
    else if (p.type === "str") { input.type = "text"; input.value = p.value; }
    else {
      input.type = "number"; input.value = p.value;
      input.step = p.type === "int" ? 1 : "any";
      if (p.min != null) input.min = p.min;
      if (p.max != null) input.max = p.max;
    }
    input.addEventListener("change", () => {
      state.params[p.name] = p.type === "bool" ? input.checked : input.value;
      run();
    });
    wrap.append(name, input);
    root.appendChild(wrap);
  }
}

// ------------------------------------------------------------------ actions
function request() {
  return {
    script: $("editor").value,
    params: state.params,
    printer: $("printer").value,
    material: $("material").value,
    overhang_angle: Number($("angle").value),
    infill: Number($("infill").value) / 100,
  };
}

async function errorText(res) {
  try { const j = await res.json(); return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); }
  catch { return `${res.status} ${res.statusText}`; }
}

async function run() {
  setStatus("Running...");
  try {
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request()) });
    if (!res.ok) { setStatus(await errorText(res), true); return; }
    const data = await res.json();
    state.lastBuild = data;
    drawMesh(data.mesh, data.overhang_faces);
    renderAnalysis(data.analysis);
    renderParams(data.params);
    setStatus(data.stdout || "OK");
  } catch (err) {
    setStatus(String(err), true);
  }
}

async function download(fmt) {
  setStatus(`Exporting ${fmt.toUpperCase()}...`);
  const res = await fetch(`/api/export/${fmt}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request()) });
  if (!res.ok) { setStatus(await errorText(res), true); return; }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = `model.${fmt}`;
  a.click();
  URL.revokeObjectURL(url);
  setStatus(`Exported model.${fmt}`);
}

function selectedPrinter() {
  return state.printers.find((p) => p.key === $("printer").value);
}

async function init() {
  const [printers, materials, examples] = await Promise.all(
    ["printers", "materials", "examples"].map((n) => fetch(`/api/${n}`).then((r) => r.json())),
  );
  state.printers = printers; state.examples = examples;
  printers.forEach((p) => option($("printer"), p.key, `${p.name} (${p.x}x${p.y}x${p.z})`));
  materials.forEach((m) => option($("material"), m.key, m.name));
  examples.forEach((e) => option($("example"), e.name, e.title));
  $("printer").value = "prusa_mk4";
  drawBuildVolume(selectedPrinter());
  loadExample();
  resize();
  run();
}

function loadExample() {
  const ex = state.examples.find((e) => e.name === $("example").value);
  if (ex) { $("editor").value = ex.script; state.params = {}; }
}

$("example").addEventListener("change", () => { loadExample(); run(); });
$("printer").addEventListener("change", () => { drawBuildVolume(selectedPrinter()); run(); });
$("material").addEventListener("change", run);
$("angle").addEventListener("change", run);
$("infill").addEventListener("change", run);
$("run").addEventListener("click", run);
document.querySelectorAll("[data-export]").forEach((b) => b.addEventListener("click", () => download(b.dataset.export)));
$("editor").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
  if (e.key === "Tab") {
    e.preventDefault();
    const t = e.target, s = t.selectionStart;
    t.value = t.value.slice(0, s) + "    " + t.value.slice(t.selectionEnd);
    t.selectionStart = t.selectionEnd = s + 4;
  }
});

init().catch((err) => setStatus(`Failed to initialise: ${err}`, true));
