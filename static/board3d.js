import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { SVGLoader } from './vendor/SVGLoader.js';
import { drillContour, padContours } from './cad-drills.mjs';

/*
 * CAD-driven 3D renderer for the selected STM32F103ZET6 board.
 *
 * The model is deliberately made from primitives.  No board image is loaded
 * here: every board, connector contact, IC, switch, LED dome and wire is a
 * mesh.  `app.js` remains the owner of project persistence and the electrical
 * graph; this renderer consumes that state and sends user gestures back as
 * small DOM events.
 */
const root = document.getElementById('canvas3d');
const CAD = globalThis.OpenBoardData;
const BOARD = globalThis.OpenBoardMap || globalThis.EliteBoardMap;
const SIGNALS = globalThis.OnboardSignals;
const SX = 115 / 520;
const SZ = 117 / 524;
const SVG_CENTER = { x: 400, y: 327 };
const NATIVE = { width: 915, height: 922 };
const CAD_MM_TO_WORLD = CAD?.meta?.widthMm ? 1.8 : 1;
const CAD_WIDTH_MM = Number(CAD?.meta?.widthMm) || 56.098;
const CAD_HEIGHT_MM = Number(CAD?.meta?.heightMm) || 53.5;
const COLORS = Object.freeze({
  board: 0x0b4c91,
  boardEdge: 0x082e5b,
  silk: 0xb7e2d8,
  copper: 0xe8b94c,
  contact: 0xa5afb8,
  socket: 0xf1c32d,
  black: 0x101821,
  chip: 0x202a35,
  silver: 0xbfcbd1,
  white: 0xd9e7ee,
  red: 0xd6404b,
  green: 0x54be7a,
  yellow: 0xf0c52d,
  blue: 0x2c71c1,
  purple: 0x7052a7,
  component: 0x415568
});

let boardPowered = false;
try { boardPowered = sessionStorage.getItem('stm32-board-power') === 'on'; } catch {}
let cadPowerLed = null;
let cadPowerGlow = null;
let viewDistance = 1;
let resolveReady;
const ready = new Promise(resolve => { resolveReady = resolve; });
const api = {
  ready,
  sync,
  setView,
  zoom,
  screenToProject,
  setKeyState,
  setCopperLayer,
  setBoardPower,
  setComponentsVisible,
  selectNet,
  getDiagnostics: () => ({ ...diagnostics })
};
globalThis.Board3D = api;

const diagnostics = {
  renderer: 'pending',
  meshCount: 0,
  boardPinMeshes: 0,
  mcuLegMeshes: 0,
  componentMeshes: 0,
  status: 'loading'
};

let renderer;
let scene;
let camera;
let controls;
let raycaster;
let pointer;
let boardRoot;
let staticTargets = [];
let pinTargets = [];
let moduleTargets = [];
let wireTargets = [];
let wireGroup;
let moduleGroup;
let cadTopGroup;
let cadBottomGroup;
let cadComponentGroup;
let moduleMeshes = new Map();
let pinMeshes = new Map();
let canonicalPins = new Map();
let endpointWorld = new Map();
let ledRefs = new Map();
let ledPortWorld = new Map();
let keyRefs = new Map();
let keyTargets = [];
let cadTrackTargets = [];
let cadPadTargets = [];
let cadGraphicTargets = [];
let cadNetSelection = null;
let copperLayer = 'both';
let cadComponentsVisible = true;
let inventory = [];
let lastState = null;
let pendingState = null;
let modulesSignature = '';
let wiresSignature = '';
let emissionSignature = '';
let pointerDown = null;
let drag = null;
let sceneReady = false;
let initialFitPending = true;
let hintTimer;

function dispatch(name, detail) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function nativeToWorld(nativeX, nativeY, y = 1.1) {
  return new THREE.Vector3(
    (Number(nativeX) / NATIVE.width - 0.5) * 115,
    y,
    (Number(nativeY) / NATIVE.height - 0.5) * 117
  );
}

function cadToWorld(mmX, mmY, y = 1.1) {
  return new THREE.Vector3(
    (Number(mmX) - CAD_WIDTH_MM / 2) * CAD_MM_TO_WORLD,
    y,
    (CAD_HEIGHT_MM / 2 - Number(mmY)) * CAD_MM_TO_WORLD
  );
}

function isCadBoard() {
  return Boolean(CAD?.meta && Array.isArray(CAD.pads) && Array.isArray(CAD.components));
}

function svgToWorld(x, y, height = 3) {
  return new THREE.Vector3((Number(x) - SVG_CENTER.x) * SX, height, (Number(y) - SVG_CENTER.y) * SZ);
}

function worldToSvg(point) {
  return { x: point.x / SX + SVG_CENTER.x, y: point.z / SZ + SVG_CENTER.y };
}

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.6,
    metalness: options.metalness ?? 0.08,
    transparent: options.transparent ?? false,
    opacity: options.opacity ?? 1,
    emissive: options.emissive ?? 0x000000,
    emissiveIntensity: options.emissiveIntensity ?? 0,
    side: options.side ?? THREE.FrontSide
  });
}

function mesh(geometry, mat, position, parent = boardRoot, userData = {}) {
  const object = new THREE.Mesh(geometry, mat);
  object.position.copy(position);
  object.userData = { ...userData };
  object.castShadow = true;
  object.receiveShadow = true;
  parent.add(object);
  return object;
}

function disposeGroup(group) {
  if (!group) return;
  while (group.children.length) {
    const object = group.children.pop();
    object.traverse(child => {
      child.geometry?.dispose?.();
      if (Array.isArray(child.material)) child.material.forEach(value => value.dispose?.());
      else child.material?.dispose?.();
    });
  }
}

function textSprite(text, color = '#b7e2d8', size = 3, scale = 1) {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 96;
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.font = '600 42px system-ui, sans-serif';
  context.fillStyle = color;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(String(text), canvas.width / 2, canvas.height / 2);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(size * 4.6 * scale, size * scale, 1);
  return sprite;
}

// Board silkscreen is fixed to the PCB plane so it remains legible when the
// user rotates the camera. Sprites are useful for floating component labels,
// but a camera-facing sprite made the physical board markings appear tiny and
// detached from the board.
function silkPlane(text, color = '#b7e2d8', size = 2.7, scale = 1, laser = false) {
  const fontPx = Math.max(36, Math.round(60 * scale));
  const probeCanvas = document.createElement('canvas');
  const probe = probeCanvas.getContext('2d');
  probe.font = ` ${laser ? 400 : 700} ${fontPx}px ${laser ? "monospace" : "system-ui, sans-serif"}`;
  const measuredWidth = Math.max(1, probe.measureText(String(text)).width);
  const paddingX = Math.ceil(fontPx * 0.28);
  const paddingY = Math.ceil(fontPx * 0.22);
  // Tight per-label canvases keep short labels from being shrunk by the
  // unused width of a shared 512×96 atlas. The plane's glyph height is kept
  // at roughly 1.2 mm for pin names and at least 3 mm for major markings.
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(measuredWidth + paddingX * 2);
  canvas.height = Math.ceil(fontPx + paddingY * 2);
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.font = ` ${laser ? 400 : 700} ${fontPx}px ${laser ? "monospace" : "system-ui, sans-serif"}`;
  context.fillStyle = color;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.strokeStyle = 'rgba(4,22,38,.7)';
  context.lineWidth = 3;
  if (!laser) context.strokeText(String(text), canvas.width / 2, canvas.height / 2 + fontPx * 0.04);
  context.fillText(String(text), canvas.width / 2, canvas.height / 2 + fontPx * 0.04);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  const height = Math.max(1.5, Number(size) * 1.25);
  const width = Math.max(height * 1.2, height * (canvas.width / canvas.height));
  const plane = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, side: THREE.DoubleSide })
  );
  plane.rotation.x = -Math.PI / 2;
  plane.userData = { type: 'silkscreen', label: String(text), static: true };
  // Silk is visual reference text; it must not occlude a nearby physical
  // contact in the raycaster.
  plane.raycast = () => {};
  return plane;
}

function addSilk(text, nativeX, nativeY, size = 2.7, color = '#b7e2d8') {
  const label = silkPlane(text, color, size);
  label.position.copy(nativeToWorld(nativeX, nativeY, 2.25));
  boardRoot.add(label);
  staticTargets.push(label);
  return label;
}

function registerInventory(entry) {
  inventory.push(Object.freeze({ ...entry }));
}

function addPin(hole) {
  const point = nativeToWorld(hole.nativeX, hole.nativeY, 2.35);
  const pin = mesh(
    new THREE.CylinderGeometry(0.76, 0.76, 0.72, 10),
    material(COLORS.copper, { metalness: 0.82, roughness: 0.28 }),
    point,
    boardRoot,
    { type: 'board-pin', endpointId: hole.id, canonical: hole.canonical, address: hole.address, header: hole.header, signal: hole.signal }
  );
  pinMeshes.set(hole.id, pin);
  if (!canonicalPins.has(hole.canonical)) canonicalPins.set(hole.canonical, pin);
  endpointWorld.set(hole.id, point.clone());
  endpointWorld.set(hole.canonical, endpointWorld.get(hole.canonical) || point.clone());
  pinTargets.push(pin);
  if (hole.header === 'P1' || hole.header === 'P2') {
    const inward = hole.header === 'P1' ? -42 : 42;
    addSilk(hole.signal, hole.nativeX + inward, hole.nativeY, 1.15, '#a9d5bc');
  } else if (hole.header === 'P3' || hole.header === 'P5' || hole.header === 'VOUT1' || hole.header === 'VOUT2') {
    addSilk(hole.signal, hole.nativeX + 18, hole.nativeY, 1.08, '#d9d39b');
  }
}

function addHeaderGroup(header, holes, color = COLORS.socket) {
  if (!holes.length) return;
  const points = holes.map(hole => nativeToWorld(hole.nativeX, hole.nativeY, 1.45));
  const minX = Math.min(...points.map(point => point.x));
  const maxX = Math.max(...points.map(point => point.x));
  const minZ = Math.min(...points.map(point => point.z));
  const maxZ = Math.max(...points.map(point => point.z));
  const width = Math.max(4.8, maxX - minX + 3.0);
  const depth = Math.max(4.8, maxZ - minZ + 3.0);
  mesh(new THREE.BoxGeometry(width, 2.1, depth), material(color, { roughness: 0.48 }), new THREE.Vector3((minX + maxX) / 2, 1.45, (minZ + maxZ) / 2), boardRoot, { type: 'header-body', header });
  holes.forEach(addPin);
  addSilk(header, ((minX + maxX) / 2) / SX + SVG_CENTER.x, ((minZ + maxZ) / 2) / SZ + SVG_CENTER.y - 7, 2.2, '#f6db8a');
  registerInventory({ id: header, label: `${header} · ${holes.length} mapped contacts`, category: 'physical header', electrical: header === 'P1' || header === 'P2' || header === 'P3' || header === 'P5' ? 'pin selectable' : 'power aliases' });
}

function addMountingHole(nativeX, nativeY) {
  const position = nativeToWorld(nativeX, nativeY, 1.08);
  mesh(new THREE.CylinderGeometry(3, 3, 0.28, 24), material(COLORS.copper, { metalness: 0.8, roughness: 0.24 }), position, boardRoot, { type: 'mounting-ring' });
  mesh(new THREE.CylinderGeometry(1.9, 1.9, 0.38, 24), material(COLORS.black, { roughness: 0.85 }), new THREE.Vector3(position.x, 1.18, position.z), boardRoot, { type: 'mounting-hole' });
}

function addMcu() {
  const center = nativeToWorld(457, 462, 3.0);
  const group = new THREE.Group();
  group.name = 'STM32F103ZET6-LQFP144';
  group.position.copy(center);
  group.rotation.y = Math.PI / 4;
  boardRoot.add(group);
  const body = mesh(new THREE.BoxGeometry(27, 3.0, 27), material(COLORS.chip, { roughness: 0.52, metalness: 0.16 }), new THREE.Vector3(0, 0, 0), group, { type: 'mcu-body', label: 'STM32F103ZET6 · LQFP-144' });
  body.castShadow = true;
  for (let index = 0; index < 36; index += 1) {
    const offset = -12.95 + index * (25.9 / 35);
    for (const side of [-1, 1]) {
      const leg = mesh(new THREE.BoxGeometry(2.2, 0.62, 0.56), material(COLORS.contact, { metalness: 0.86, roughness: 0.28 }), new THREE.Vector3(offset, 0.15, side * 14.35), group, { type: 'mcu-leg', legIndex: index + (side === 1 ? 36 : 0) });
      leg.rotation.y = 0;
      const leg2 = mesh(new THREE.BoxGeometry(0.56, 0.62, 2.2), material(COLORS.contact, { metalness: 0.86, roughness: 0.28 }), new THREE.Vector3(side * 14.35, 0.15, offset), group, { type: 'mcu-leg', legIndex: index + 72 + (side === 1 ? 36 : 0) });
      leg2.rotation.y = 0;
      diagnostics.mcuLegMeshes += 2;
    }
  }
  const mark = mesh(new THREE.CylinderGeometry(1.2, 1.2, 0.2, 20), material(COLORS.silver, { metalness: 0.65 }), new THREE.Vector3(-10, 1.62, -10), group, { type: 'mcu-pin-one' });
  mark.rotation.x = 0;
  const label = textSprite('STM32F103ZET6', '#dce6ee', 2.4, 0.9);
  label.position.set(0, 1.75, 0);
  label.rotation.y = -Math.PI / 4;
  group.add(label);
  registerInventory({ id: 'mcu', label: 'STM32F103ZET6 · LQFP-144', category: 'MCU', electrical: 'GPIO trace supported' });
}

function addChip(id, label, nativeX, nativeY, width, depth, legs = 8, color = COLORS.chip) {
  const center = nativeToWorld(nativeX, nativeY, 2.35);
  const group = new THREE.Group();
  group.position.copy(center);
  group.name = id;
  boardRoot.add(group);
  mesh(new THREE.BoxGeometry(width, 2.0, depth), material(color, { roughness: 0.53, metalness: 0.18 }), new THREE.Vector3(), group, { type: 'ic-body', id, label });
  const legCount = Math.max(2, Math.ceil(legs / 2));
  for (let i = 0; i < legCount; i += 1) {
    const x = (i - (legCount - 1) / 2) * Math.min(1.05, width / (legCount + 1));
    for (const side of [-1, 1]) mesh(new THREE.BoxGeometry(0.42, 0.55, 1.6), material(COLORS.contact, { metalness: 0.78, roughness: 0.32 }), new THREE.Vector3(x, 0, side * (depth / 2 + 0.8)), group, { type: 'ic-leg', id });
  }
  const silk = textSprite(label, '#a9cec9', 1.4, 0.68);
  silk.position.set(0, 1.4, 0);
  group.add(silk);
  staticTargets.push(group);
  registerInventory({ id, label, category: 'IC package', electrical: 'geometry only' });
  diagnostics.componentMeshes += 1;
  return group;
}

function addDiscrete(id, label, nativeX, nativeY, width = 2.7, depth = 1.8, color = COLORS.component, shape = 'box') {
  const position = nativeToWorld(nativeX, nativeY, 2.0);
  let geometry;
  if (shape === 'cylinder') geometry = new THREE.CylinderGeometry(Math.min(width, depth) / 2, Math.min(width, depth) / 2, 1.7, 12);
  else geometry = new THREE.BoxGeometry(width, 1.5, depth);
  const object = mesh(geometry, material(color, { roughness: 0.48, metalness: shape === 'cylinder' ? 0.3 : 0.12 }), position, boardRoot, { type: 'discrete', id, label });
  if (shape === 'cylinder') object.rotation.z = Math.PI / 2;
  // Small discrete parts expose two plated solder pads beneath the body. The
  // pads are a visual package cue, not a fabricated electrical net.
  if (width <= 12 && depth <= 8) {
    const offset = Math.max(1.2, width * 0.58);
    for (const side of [-1, 1]) {
      mesh(new THREE.BoxGeometry(Math.min(1.25, width * 0.24), 0.18, Math.min(1.05, depth * 0.46)), material(COLORS.copper, { roughness: 0.3, metalness: 0.75 }), new THREE.Vector3(position.x + side * offset, 1.33, position.z), boardRoot, { type: 'solder-pad', parentId: id, label: `${label} solder pad` });
    }
  }
  registerInventory({ id, label, category: 'visible component', electrical: 'geometry only' });
  diagnostics.componentMeshes += 1;
  return object;
}

function addTactile(id, label, nativeX, nativeY, color, signal = null, activeLevel = null) {
  const position = nativeToWorld(nativeX, nativeY, 3.2);
  const keyData = { type: 'tactile-body', id, label, keyId: id, signal, activeLevel };
  const body = mesh(new THREE.BoxGeometry(5.7, 3.0, 5.7), material(COLORS.black, { roughness: 0.7 }), position, boardRoot, keyData);
  const cap = mesh(new THREE.CylinderGeometry(2.2, 2.2, 1.4, 16), material(color, { roughness: 0.3 }), new THREE.Vector3(position.x, 5.0, position.z), boardRoot, { ...keyData, type: 'tactile-cap' });
  staticTargets.push(body);
  keyTargets.push(body, cap);
  keyRefs.set(id, { body, cap, signal, activeLevel, restY: 5.0, pressed: false });
  registerInventory({ id, label, category: 'tactile switch', electrical: signal ? `${signal} sampled on next run · active-${activeLevel ? 'high' : 'low'}` : 'reset control' });
  diagnostics.componentMeshes += 2;
}

function setKeyState(id, pressed) {
  const ref = keyRefs.get(id);
  if (!ref) return;
  ref.pressed = Boolean(pressed);
  ref.cap.position.y = ref.restY + (ref.pressed ? -0.72 : 0);
  ref.cap.material.emissive.set(ref.pressed ? 0x2d2410 : 0x000000);
  ref.cap.material.emissiveIntensity = ref.pressed ? 0.22 : 0;
}

function addConnector(id, label, nativeX, nativeY, rows, cols, color = COLORS.socket) {
  const spacing = 2.54;
  const width = Math.max(4.2, (cols - 1) * spacing + 3.3);
  const depth = Math.max(4.2, (rows - 1) * spacing + 3.3);
  const center = nativeToWorld(nativeX, nativeY, 1.45);
  mesh(new THREE.BoxGeometry(width, 2.0, depth), material(color, { roughness: 0.48 }), center, boardRoot, { type: 'unmapped-header', id, label });
  for (let row = 0; row < rows; row += 1) {
    for (let col = 0; col < cols; col += 1) {
      const contact = new THREE.Vector3(center.x + (col - (cols - 1) / 2) * spacing, 2.55, center.z + (row - (rows - 1) / 2) * spacing);
      mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.72, 8), material(COLORS.contact, { metalness: 0.78, roughness: 0.3 }), contact, boardRoot, { type: 'unmapped-contact', id, row, col });
    }
  }
  addSilk(label, nativeX, nativeY - 5, 1.7, '#e9d885');
  registerInventory({ id, label, category: 'header / module', electrical: 'not GPIO-injected' });
}

function addOnboardLed(signal, label, nativeX, nativeY, color) {
  const base = nativeToWorld(nativeX, nativeY, 2.0);
  const body = mesh(new THREE.CylinderGeometry(1.25, 1.25, 1.15, 20), material(COLORS.black, { roughness: 0.72 }), base, boardRoot, { type: 'onboard-led-body', signal, label });
  const domeMaterial = material(color, { roughness: 0.2, transparent: true, opacity: 0.38, emissive: color, emissiveIntensity: 0 });
  const dome = mesh(new THREE.SphereGeometry(1.2, 20, 12), domeMaterial, new THREE.Vector3(base.x, 3.0, base.z), boardRoot, { type: 'onboard-led-dome', signal, label });
  dome.scale.y = 0.72;
  const light = new THREE.PointLight(color, 0, 16, 2);
  light.position.set(base.x, 3.2, base.z);
  boardRoot.add(light);
  const port = new THREE.Vector3(base.x, 2.85, base.z);
  ledRefs.set(signal, { body, dome, light, label, color, brightness: 0 });
  ledPortWorld.set(signal, port);
  addSilk(label, nativeX, nativeY + 7, 1.35, color);
  registerInventory({ id: signal, label, category: 'on-board LED', electrical: `${signal} active-low · trace driven` });
}

function buildPcbSurfaceOverlay() {
  const data = globalThis.PcbSurfaceData;
  if (!data || typeof data !== 'object') return;
  const traces = Array.isArray(data.traces) ? data.traces : [];
  const vias = Array.isArray(data.vias) ? data.vias : [];
  for (const [index, trace] of traces.entries()) {
    const points = (Array.isArray(trace?.points) ? trace.points : []).map(value => {
      const x = Array.isArray(value) ? value[0] : value?.x;
      const y = Array.isArray(value) ? value[1] : value?.y;
      const side = Array.isArray(value) ? trace.side : value?.side || trace.side;
      return { point: nativeToWorld(x, y, side === 'bottom' ? -1.08 : 2.18), side };
    }).filter(item => Number.isFinite(item.point.x) && Number.isFinite(item.point.z));
    if (points.length < 2) continue;
    const curve = new THREE.CatmullRomCurve3(points.map(item => item.point), false, 'centripetal', 0.2);
    const color = trace.side === 'bottom' ? 0x8b5f2f : (trace.color || COLORS.copper);
    const width = Number.isFinite(Number(trace.width)) ? Math.max(0.08, Math.min(0.5, Number(trace.width))) : 0.18;
    const surfaceTrace = mesh(new THREE.TubeGeometry(curve, Math.max(4, points.length * 5), width, 6, false), material(color, { roughness: 0.32, metalness: 0.7, emissive: color, emissiveIntensity: 0.04 }), new THREE.Vector3(), boardRoot, { type: 'pcb-trace', traceIndex: index, label: trace.label || `PCB trace ${index + 1}`, static: true });
    staticTargets.push(surfaceTrace);
  }
  for (const [index, via] of vias.entries()) {
    const x = Array.isArray(via) ? via[0] : via?.nativeX ?? via?.x;
    const y = Array.isArray(via) ? via[1] : via?.nativeY ?? via?.y;
    if (!Number.isFinite(Number(x)) || !Number.isFinite(Number(y))) continue;
    const pad = mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.18, 10), material(COLORS.copper, { roughness: 0.28, metalness: 0.8 }), nativeToWorld(x, y, 2.3), boardRoot, { type: 'pcb-via', viaIndex: index, label: via.label || 'PCB via', static: true });
    staticTargets.push(pad);
  }
  if (traces.length || vias.length) registerInventory({ id: 'pcb-surface-data', label: `PCB copper overlay · ${traces.length} traces · ${vias.length} vias`, category: 'evidence-based surface data', electrical: 'visual reference only' });
}

function cadLayerName(layer) {
  const value = String(layer || '').toLowerCase();
  const numeric = Number(layer);
  if ([2, 4, 6, 8].includes(numeric)) return 'bottom';
  if ([1, 3, 5, 7].includes(numeric)) return 'top';
  return value.includes('bottom') || value === 'b' || value.includes('blayer') ? 'bottom' : 'top';
}

function cadLayerGroup(layer) {
  return cadLayerName(layer) === 'bottom' ? cadBottomGroup : cadTopGroup;
}

// EasyEDA layer 11 is a through-hole / multilayer pad.  It must be drawn on
// both copper faces: placing the contact on the top group only makes H1-H9
// and the through-hole vias disappear when the user inspects the underside.
function cadPadLayers(pad) {
  const value = String(pad?.layer ?? '').toLowerCase();
  const numeric = Number(pad?.layer);
  if (numeric === 11 || value.includes('multi') || value.includes('through') || value === 'all') return ['top', 'bottom'];
  return [cadLayerName(pad?.layer)];
}

function cadEndpointForPad(pad) {
  const map = globalThis.OpenBoardMap;
  if (typeof map?.endpointForPad === 'function') return map.endpointForPad(pad.id);
  if (map?.padEndpoints && typeof map.padEndpoints === 'object') return map.padEndpoints[pad.id] || null;
  if (typeof pad.endpointId === 'string') return pad.endpointId;
  const net = String(pad.net || '').trim();
  if (!net || !BOARD) return null;
  const candidate = net.startsWith('board:') ? net : `board:${net}`;
  return BOARD.isSupportedGpio?.(candidate) || ['board:GND', 'board:3V3', 'board:5V'].includes(candidate) ? candidate : null;
}

function cadPadGeometry(pad) {
  const contours = padContours(pad);
  const shape = new THREE.Shape(contours.outer.map(([x,y]) => new THREE.Vector2(x*CAD_MM_TO_WORLD,-y*CAD_MM_TO_WORLD)));
  if (contours.hole.length) shape.holes.push(new THREE.Path(contours.hole.map(([x,y]) => new THREE.Vector2(x*CAD_MM_TO_WORLD,-y*CAD_MM_TO_WORLD))));
  const geometry = new THREE.ExtrudeGeometry(shape, { depth:0.46, bevelEnabled:false, curveSegments:32 });
  geometry.translate(0,0,-0.23);
  geometry.rotateX(Math.PI/2);
  return geometry;
}

function cadPadPosition(pad, side = cadLayerName(pad?.layer)) {
  return cadToWorld(pad.x, pad.y, side === 'bottom' ? -1.08 : 1.08);
}

function addCadPad(pad) {
  const endpointId = cadEndpointForPad(pad);
  const objects = [];
  for (const side of cadPadLayers(pad)) {
    const position = cadPadPosition(pad, side);
    const padObject = mesh(
      cadPadGeometry(pad),
      material(pad.net ? 0xd9a94d : COLORS.contact, { metalness: 0.82, roughness: 0.27 }),
      position,
      cadLayerGroup(side),
      { type: 'cad-pad', padId: pad.id, layer: side, endpointId: endpointId || undefined, canonical: endpointId ? BOARD.normalizeEndpoint?.(endpointId) : undefined, net: pad.net || null, ref: pad.ref || '', label: `${pad.ref || 'pad'} · ${pad.number || pad.id}${pad.net ? ` · ${pad.net}` : ''}`, source: 'PE.JADO EasyEDA PCB' }
    );
    padObject.rotation.y = THREE.MathUtils.degToRad(Number(pad.rotation) || 0);
    cadPadTargets.push(padObject);
    staticTargets.push(padObject);
    objects.push(padObject);
    if (endpointId) {
      pinTargets.push(padObject);
      pinMeshes.set(endpointId, pinObjectForEndpoint(endpointId, padObject));
      const canonical = BOARD.normalizeEndpoint?.(endpointId) || endpointId;
      if (!canonicalPins.has(canonical)) canonicalPins.set(canonical, padObject);
      // Keep the first face as the canonical wire endpoint; both face meshes
      // remain pickable for inspection and pin-pair wiring.
      if (!endpointWorld.has(endpointId)) endpointWorld.set(endpointId, position.clone());
      if (!endpointWorld.has(canonical)) endpointWorld.set(canonical, position.clone());
    }
  }
  return objects[0] || null;
}

function pinObjectForEndpoint(endpointId, candidate) {
  const current = pinMeshes.get(endpointId);
  return current || candidate;
}

const cadSvgLoader = new SVGLoader();
function addCadSvgGraphic(graphic, index) {
  const layer = Number(graphic.layer);
  if (![1,2,3,4].includes(layer) || !graphic.pathRaw) return;
  const silk = layer === 3 || layer === 4;
  const side = cadLayerName(layer);
  const filled = (graphic.kind === 'text' && /z/i.test(graphic.pathRaw)) || graphic.kind === 'solid-region';
  // COPPERAREA is a pour boundary, not the final cleared copper. Display its
  // outline only; final solid regions carry the generated copper geometry.
  const color = silk ? 0xcbd6cb : side === 'top' ? 0xb7934c : 0xa56c3b;
  const unit = CAD.meta.unitsMmPerRaw * CAD_MM_TO_WORLD;
  const origin = CAD.meta.coordinateTransform.rawOrigin;
  const widthRaw = Math.max(0.05, (graphic.width || 0.12) / CAD.meta.unitsMmPerRaw);
  const path = String(graphic.pathRaw).replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg"><path d="${path}" fill="${filled ? '#ffffff' : 'none'}" stroke="${filled ? 'none' : '#ffffff'}" stroke-width="${widthRaw}"/></svg>`;
  const parsed = cadSvgLoader.parse(svg);
  for (const contour of parsed.paths) {
    const geometries = filled
      ? SVGLoader.createShapes(contour).map(shape => new THREE.ShapeGeometry(shape, 12))
      : contour.subPaths.map(subpath => SVGLoader.pointsToStroke(subpath.getPoints(16), contour.userData.style)).filter(Boolean);
    for (const geometry of geometries) {
      geometry.scale(unit, unit, 1);
      geometry.translate(-origin[0]*unit-CAD_WIDTH_MM*CAD_MM_TO_WORLD/2, -origin[1]*unit+CAD_HEIGHT_MM*CAD_MM_TO_WORLD/2, 0);
      const object = new THREE.Mesh(geometry, material(color, {side:THREE.DoubleSide, roughness:silk ? 0.9 : 0.5, metalness:silk ? 0 : 0.5}));
      object.rotation.x = Math.PI/2;
      object.position.y = side === 'top' ? (silk ? 1.25 : 0.91) : (silk ? -1.25 : -0.91);
      object.userData = {type:silk ? 'cad-silkscreen' : 'cad-copper-fill', graphicIndex:index, net:graphic.net || null, label:graphic.text || graphic.ref || graphic.kind, source:'PE.JADO PCB vector geometry'};
      cadLayerGroup(side).add(object);
      cadGraphicTargets.push(object);
      if (!silk) staticTargets.push(object);
    }
  }
}

function cadGraphicPoints(graphic) {
  if (Array.isArray(graphic?.pointsMM)) return graphic.pointsMM.map(point => Array.isArray(point) ? point : [point.x, point.y]).filter(point => Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1])));
  return [];
}

function cadPolylineCurve(points) {
  const path = new THREE.CurvePath();
  for (let index = 1; index < points.length; index += 1) {
    path.add(new THREE.LineCurve3(points[index - 1], points[index]));
  }
  return path;
}

function addCadGraphic(graphic, index) {
  if (graphic.visible === false || graphic.kind === 'hole') return;
  // A source cutout removes copper; it must never be painted as a solid face.
  if (graphic.kind === 'solid-region' && ['cutout','npth'].includes(graphic.sourceRaw?.split('~')[4])) return;
  if (graphic.pathRaw) { addCadSvgGraphic(graphic, index); return; }
  if (![1,2,3,4].includes(Number(graphic.layer))) return;
  const points = cadGraphicPoints(graphic);
  const kind = String(graphic?.kind || '').toLowerCase();
  const layer = cadLayerName(graphic?.layer);
  const parent = cadLayerGroup(layer);
  if (kind === 'circle' && Number.isFinite(Number(graphic?.x)) && Number.isFinite(Number(graphic?.y))) {
    const radius = Math.max(0.12, Number(graphic.diameter) || 1) * CAD_MM_TO_WORLD / 2;
    const width = Math.max(0.04, Number(graphic.width) || 0.2) * CAD_MM_TO_WORLD / 2;
    const side = layer === 'bottom' ? 'bottom' : 'top';
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius, width, 8, 32), material(side === 'bottom' ? 0xb59a6a : 0xe9e0ae, { roughness: 0.52, metalness: 0.24, side: THREE.DoubleSide }));
    ring.rotation.x = Math.PI / 2;
    ring.position.copy(cadToWorld(graphic.x, graphic.y, side === 'bottom' ? -0.99 : 0.99));
    ring.userData = { type: 'cad-silk-circle', graphicIndex: index, ref: graphic.ref || '', label: `${graphic.ref || 'CAD'} source circle`, source: 'PE.JADO EasyEDA/Gerber' };
    parent.add(ring);
    cadGraphicTargets.push(ring);
    staticTargets.push(ring);
    return;
  }
  if (points.length >= 2) {
    const worldPoints = points.map(point => cadToWorld(point[0], point[1], layer === 'bottom' ? -0.98 : 0.98));
    if (kind.includes('copper') || kind.includes('fill') || kind.includes('solid') || (kind === 'rect' && [1,2].includes(Number(graphic.layer)))) {
      const shape = new THREE.Shape();
      // ShapeGeometry is laid out in local XY and rotated onto the board's
      // XZ plane below.  Keep the already-transformed CAD Z coordinate here;
      // negating it mirrors copper pours across the board center.
      shape.moveTo(worldPoints[0].x, worldPoints[0].z);
      worldPoints.slice(1).forEach(point => shape.lineTo(point.x, point.z));
      shape.closePath();
      const fillColor = kind.includes('copper') ? (layer === 'bottom' ? 0x70451f : 0x9a6a28) : (graphic.net ? 0x315c48 : 0x8e8e75);
      const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), material(fillColor, { transparent: true, opacity: 0.24, roughness: 0.72, metalness: 0.22, side: THREE.DoubleSide, emissive: 0x000000 }));
      fill.rotation.x = Math.PI / 2;
      fill.position.y = layer === 'bottom' ? -0.94 : 0.94;
      fill.userData = { type: 'cad-copper-fill', graphicIndex: index, net: graphic.net || null, label: graphic.label || 'CAD copper fill', source: 'PE.JADO Gerber/EasyEDA' };
      parent.add(fill);
      cadGraphicTargets.push(fill);
      staticTargets.push(fill);
    } else {
      const curve = cadPolylineCurve(worldPoints);
      const line = mesh(new THREE.TubeGeometry(curve, Math.max(1, worldPoints.length * 2), Math.max(0.035, Number(kind === 'rect' ? graphic.strokeWidth || 0.15 : graphic.width) || 0.08) * CAD_MM_TO_WORLD / 2, 5, false), material([3,4].includes(Number(graphic.layer)) ? 0xcbd6cb : layer === 'bottom' ? 0x8b5f2f : 0xb89c63, { roughness: [3,4].includes(Number(graphic.layer)) ? 0.9 : 0.38, metalness: [3,4].includes(Number(graphic.layer)) ? 0 : 0.55 }), new THREE.Vector3(), parent, { type: 'cad-graphic', graphicIndex: index, net: graphic.net || null, label: graphic.text || graphic.label || 'CAD silk graphic', source: 'PE.JADO EasyEDA/Gerber' });
      cadGraphicTargets.push(line);
      staticTargets.push(line);
    }
  } else if (graphic?.text) {
    const text = silkPlane(graphic.text, layer === 'bottom' ? '#c8a46d' : '#e9e0ae', Math.max(1.2, Number(graphic.height) || 1.5));
    text.position.copy(cadToWorld(graphic.x, graphic.y, layer === 'bottom' ? -0.96 : 1.0));
    // EasyEDA stores text orientation in board coordinates.  Preserve the
    // source rotation so the long pin labels remain aligned with their edge.
    text.rotateY(-THREE.MathUtils.degToRad(Number(graphic.rotation) || 0));
    text.userData = { type: 'cad-silk-text', graphicIndex: index, label: graphic.text, source: 'PE.JADO EasyEDA/Gerber', static: true };
    parent.add(text);
    cadGraphicTargets.push(text);
    staticTargets.push(text);
  }
}

function cadComponentBounds(component, padById) {
  const pads = (component.padIds || []).map(id => padById.get(id)).filter(Boolean);
  const xs = pads.map(pad => Number(pad.x)).filter(Number.isFinite);
  const ys = pads.map(pad => Number(pad.y)).filter(Number.isFinite);
  const spanX = xs.length ? Math.max(...xs) - Math.min(...xs) : 2;
  const spanY = ys.length ? Math.max(...ys) - Math.min(...ys) : 2;
  const packageName = String(component.package || '').toUpperCase();
  let width = Math.max(1.6, spanX + 1.2);
  let depth = Math.max(1.6, spanY + 1.2);
  let dimensionsSource = 'pad envelope + package family';
  // Several source package names encode their mechanical envelope directly
  // (for example LQFP-144_L20.0-W20.0 and HC-49S_L11.4-W4.8).  Use those
  // dimensions instead of inventing a box from the footprint span.
  const encodedDimensions = packageName.match(/L(\d+(?:\.\d+)?)[-_]W(\d+(?:\.\d+)?)/i);
  if (encodedDimensions) {
    width = Number(encodedDimensions[1]);
    depth = Number(encodedDimensions[2]);
    dimensionsSource = 'source package L/W envelope';
  }
  if (packageName.includes('LQFP') || pads.length >= 100) {
    const body = encodedDimensions ? Math.max(width, depth) : Math.max(7, Math.min(18, Math.max(spanX, spanY) * 0.78));
    width = body;
    depth = body;
    dimensionsSource = encodedDimensions ? 'source LQFP package envelope' : 'LQFP pad envelope (approximate)';
  } else if (packageName.includes('HDR') || packageName.includes('HEADER')) {
    if (!encodedDimensions) {
      width = spanX + 2.5;
      depth = spanY + 2.5;
    }
    dimensionsSource = encodedDimensions ? 'source header L/W envelope' : 'header pad envelope (approximate)';
  } else if (packageName.includes('USB') || packageName.includes('MICRO')) {
    width = Math.max(width, 7.5);
    depth = Math.max(depth, 6.0);
    dimensionsSource = encodedDimensions ? 'source USB package L/W envelope' : 'USB package family envelope (approximate)';
  } else {
    width = Math.min(16, width);
    depth = Math.min(16, depth);
  }
  return { width: width * CAD_MM_TO_WORLD, depth: depth * CAD_MM_TO_WORLD, pads, approximate: true, dimensionsSource };
}

function addCadLeg(pad, center, bodyWidth, bodyDepth, parent) {
  const foot = cadPadPosition(pad).clone();
  foot.y = 0.98;
  const delta = foot.clone().sub(center);
  const horizontal = Math.abs(delta.x) > Math.abs(delta.z);
  const outward = new THREE.Vector3(horizontal ? Math.sign(delta.x) : 0, 0, horizontal ? 0 : Math.sign(delta.z));
  const shoulder = foot.clone();
  if (horizontal) shoulder.x = center.x + outward.x * bodyWidth/2;
  else shoulder.z = center.z + outward.z * bodyDepth/2;
  shoulder.y = center.y + 0.05;
  const heel = shoulder.clone().addScaledVector(outward, 0.48);
  heel.y = shoulder.y;
  const toe = foot.clone().addScaledVector(outward, -0.32);
  const points = [shoulder, heel, toe, foot];
  let first;
  for (let i=1; i<points.length; i++) {
    const direction = points[i].clone().sub(points[i-1]);
    if (direction.length()<0.01) continue;
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.22*CAD_MM_TO_WORLD,0.13,direction.length()), material(COLORS.contact,{metalness:0.88,roughness:0.25}));
    leg.position.copy(points[i].clone().add(points[i-1]).multiplyScalar(0.5));
    leg.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),direction.normalize());
    leg.userData = {type:'cad-mcu-leg',padId:pad.id,net:pad.net || null,label:`${pad.ref || 'U2'} pad ${pad.number || ''}`};
    parent.add(leg);
    first ||= leg;
  }
  return first;
}

function addCadComponent(component, padById) {
  const bounds = cadComponentBounds(component, padById);
  const center = cadToWorld(component.x, component.y, 1.55);
  const group = new THREE.Group();
  group.name = `cad-${component.ref || component.id}`;
  group.position.copy(center);
  group.rotation.y = -THREE.MathUtils.degToRad(Number(component.rotation) || 0);
  group.userData = { type: 'cad-component', componentId: component.id, ref: component.ref, label: `${component.ref || ''} ${component.value || component.package || ''}`.trim(), source: 'PE.JADO EasyEDA' };
  const packageName = String(component.package || '').toUpperCase();
  const header = packageName.includes('HDR') || packageName.includes('HEADER');
  const passive = /^[CRF]\d+$/.test(component.ref || '');
  if (bounds.dimensionsSource.includes('pad envelope')) group.rotation.y = 0;
  if (passive) { bounds.width = (packageName.includes('0805') ? 2 : 1.6)*CAD_MM_TO_WORLD; bounds.depth = (packageName.includes('0805') ? 1.25 : 0.8)*CAD_MM_TO_WORLD; group.rotation.y = -THREE.MathUtils.degToRad(Number(component.rotation)||0); }
  let color = /^C/.test(component.ref || '') ? 0x987f55 : COLORS.component;
  if (header) color = 0x171c20;
  else if (packageName.includes('USB')) color = COLORS.black;
  else if (packageName.includes('LQFP')) color = COLORS.chip;
  else if (packageName.includes('LED')) color = component.ref === 'LED1' ? COLORS.red : COLORS.green;
  const mountingMarker = packageName.includes('M3') || /^TP[1-9]$/i.test(String(component.ref || ''));
  const body = mountingMarker ? null : mesh(new THREE.BoxGeometry(bounds.width, header ? 2.6 : passive ? 0.75 : packageName.includes('LQFP') ? 2.1 : 1.4, bounds.depth), material(color, { roughness: 0.52, metalness: 0.16 }), new THREE.Vector3(), group, { type: 'cad-component-body', componentId: component.id, ref: component.ref, label: group.userData.label, source: 'PE.JADO EasyEDA', approximate: true, dimensionsSource: bounds.dimensionsSource });
  if (packageName.includes('LED')) {
    // LED0603 is a rectangular SMD package, not a through-hole dome.
    const ledColor = component.ref === 'LED1' ? COLORS.red : COLORS.green;
    const ledWidth=1.6*CAD_MM_TO_WORLD, ledDepth=0.8*CAD_MM_TO_WORLD;
    body.geometry.dispose();
    body.geometry = new THREE.BoxGeometry(ledWidth,0.65,ledDepth);
    body.material = material(0xd8d4c3,{roughness:0.6});
    for (const sign of [-1,1]) mesh(new THREE.BoxGeometry(ledWidth*0.18,0.67,ledDepth),material(COLORS.silver,{metalness:0.85,roughness:0.25}),new THREE.Vector3(sign*ledWidth*0.42,0,0),group,{type:'led-termination',ref:component.ref});
    const lens = mesh(new THREE.BoxGeometry(ledWidth*0.60,0.22,ledDepth*0.80),material(ledColor,{roughness:0.25,emissive:ledColor,emissiveIntensity:0,transparent:true,opacity:0.4}),new THREE.Vector3(0,0.4,0),group,{type:'cad-led-lens',ref:component.ref,label:group.userData.label});
    if (component.ref==='LED1') {
      cadPowerLed = lens;
      cadPowerGlow = new THREE.PointLight(0xff3030,0,6,2);
      cadPowerGlow.position.set(0,1,0);
      group.add(cadPowerGlow);
    }
  }
  if (header) {
    group.position.y = 2.3;
    for (const pad of bounds.pads) {
      const endpointId = cadEndpointForPad(pad);
      const position = cadToWorld(pad.x,pad.y,3.66);
      const contact = mesh(new THREE.CylinderGeometry(0.65,0.65,0.14,16),material(0xd7b971,{metalness:0.8}),position,cadComponentGroup,{type:'header-contact',endpointId:endpointId || undefined,net:pad.net,ref:component.ref,label:`${component.ref}-${pad.number} · ${pad.net || 'NC'}`});
      mesh(new THREE.CylinderGeometry(0.34,0.34,0.16,12),material(0x080b0d),new THREE.Vector3(position.x,3.70,position.z),cadComponentGroup,{type:'header-hole',endpointId:endpointId || undefined,net:pad.net,ref:component.ref,label:contact.userData.label});
      if(endpointId) { pinTargets.push(contact); endpointWorld.set(endpointId,position.clone()); const canonical=BOARD.normalizeEndpoint(endpointId); if(endpointId===canonical) endpointWorld.set(canonical,position.clone()); }
      staticTargets.push(contact);
    }
  } else if (passive && body) {
    for(const sign of [-1,1]) mesh(new THREE.BoxGeometry(bounds.width*0.22,0.78,bounds.depth*1.03),material(0xb8bdc0,{metalness:0.85,roughness:0.25}),new THREE.Vector3(sign*bounds.width*0.4,0,0),group,{type:'passive-termination',ref:component.ref});
  } else if (packageName.includes('USB') && body) {
    body.material = material(0xbfc3c5,{metalness:0.85,roughness:0.3});
    mesh(new THREE.BoxGeometry(bounds.width*0.72,0.95,0.45),material(0x101518),new THREE.Vector3(0,0,bounds.depth/2+0.03),group,{type:'usb-opening',ref:component.ref});
  } else if (packageName.includes('HC-49') && body) {
    body.material = material(0xc0c5c9,{metalness:0.85,roughness:0.27});
  } else if (packageName.includes('SW-') && body) {
    mesh(new THREE.BoxGeometry(bounds.width*0.42,1.3,bounds.depth*0.4),material(0x171c20),new THREE.Vector3(0,1.1,0),group,{type:'switch-actuator',ref:component.ref});
  }
  cadComponentGroup.add(group);
  if (body) staticTargets.push(body);
  const isMcu = packageName.includes('LQFP') || (component.ref || '').toUpperCase() === 'U2';
  if (isMcu) {
    // Package marking belongs to the physical body, not the PCB silk layer.
    // Model is known from the BOM; lot/date codes vary and are omitted.
    const logoPaths = new SVGLoader().parse('<svg fill="#a7aaa6" role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>STMicroelectronics</title><path d="M 23.818 5.61 L 6.402 5.61 C 5.125 5.609 3.968 6.362 3.452 7.529 L 0.014 15.811 C -0.036 15.931 0.052 16.063 0.182 16.061 L 8.046 16.061 C 8.601 16.061 8.848 15.523 8.412 15.093 L 5.524 12.388 C 4.008 10.9 4.658 7.45 7.81 7.45 L 23.206 7.45 C 23.283 7.451 23.352 7.402 23.378 7.329 L 23.987 5.857 C 23.996 5.835 24.001 5.811 24 5.787 C 23.997 5.689 23.917 5.61 23.818 5.61 M 22.082 9.826 L 19.126 9.826 C 18.932 9.825 18.756 9.94 18.681 10.118 L 15.369 18.118 C 15.355 18.144 15.347 18.173 15.347 18.202 C 15.348 18.302 15.429 18.383 15.529 18.381 L 16.632 18.381 C 17.93 18.387 19.105 17.613 19.612 16.418 L 22.244 10.063 C 22.252 10.042 22.257 10.019 22.257 9.996 C 22.253 9.902 22.176 9.828 22.082 9.826 M 16.271 10.005 C 16.271 9.905 16.189 9.825 16.089 9.825 L 7.706 9.825 C 7.251 9.825 6.853 10.38 7.335 10.825 L 10.104 13.404 C 10.104 13.404 11.224 14.437 10.984 15.916 C 10.778 17.219 9.889 18.016 9.241 18.302 C 9.208 18.31 9.196 18.351 9.219 18.376 C 9.23 18.387 9.246 18.392 9.261 18.388 L 12.489 18.388 C 12.683 18.39 12.859 18.275 12.934 18.095 L 16.256 10.068 C 16.266 10.049 16.271 10.027 16.271 10.005"/></svg>');
    for (const path of logoPaths.paths) for (const shape of SVGLoader.createShapes(path)) {
      const geometry = new THREE.ShapeGeometry(shape);
      geometry.scale(0.38, -0.38, 1);
      geometry.translate(-4.56, 4.56, 0);
      const logo = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color:0xa7aaa6,side:THREE.DoubleSide}));
      logo.rotation.x = -Math.PI/2;
      logo.position.set(0,1.08,-bounds.depth*0.26);
      logo.raycast = () => {};
      group.add(logo);
    }
    for (const [text, z, size] of [['STM32F103', -bounds.depth * 0.04, 3.0], ['ZET6', bounds.depth * 0.13, 3.0], ['ARM', bounds.depth * 0.30, 2.4]]) {
      const marking = silkPlane(text, '#a7aaa6', size, 2, true);
      marking.position.set(0, 1.065, z);
      marking.userData.label = `U2 package marking · ${text}`;
      group.add(marking);
    }
    mesh(new THREE.CylinderGeometry(0.6, 0.6, 0.035, 24), material(0x161b1e, {roughness: 0.9}), new THREE.Vector3(-bounds.width*0.40, 1.07, -bounds.depth*0.40), group, {type: 'package-pin-one', ref: component.ref, label: 'LQFP pin 1 orientation dot'});
    for (const pad of bounds.pads) addCadLeg(pad, center, bounds.width, bounds.depth, cadComponentGroup);
    diagnostics.mcuLegMeshes += bounds.pads.length;
  }
  diagnostics.componentMeshes += 1;
  registerInventory({ id: component.id, label: `${component.ref || ''} ${component.value || component.package || ''}`.trim(), category: isMcu ? 'MCU / CAD package' : 'CAD component', electrical: component.ref === 'LED1' ? '3V3 power indicator' : 'geometry with named pads' });
}

function buildCadBoard() {
  boardRoot = new THREE.Group();
  boardRoot.name = 'PE-JADO-F103ZE-CAD-board';
  scene.add(boardRoot);
  cadTopGroup = new THREE.Group();
  cadBottomGroup = new THREE.Group();
  cadComponentGroup = new THREE.Group();
  cadTopGroup.name = 'CAD-top-copper-and-silk';
  cadBottomGroup.name = 'CAD-bottom-copper-and-silk';
  cadComponentGroup.name = 'CAD-components';
  boardRoot.add(cadTopGroup, cadBottomGroup, cadComponentGroup);
  const outline = Array.isArray(CAD.outlineMM) && CAD.outlineMM.length >= 3 ? CAD.outlineMM : [[0, 0], [CAD_WIDTH_MM, 0], [CAD_WIDTH_MM, CAD_HEIGHT_MM], [0, CAD_HEIGHT_MM]];
  const shape = new THREE.Shape();
  shape.moveTo((outline[0][0] - CAD_WIDTH_MM / 2) * CAD_MM_TO_WORLD, -(outline[0][1] - CAD_HEIGHT_MM / 2) * CAD_MM_TO_WORLD);
  outline.slice(1).forEach(point => shape.lineTo((point[0] - CAD_WIDTH_MM / 2) * CAD_MM_TO_WORLD, -(point[1] - CAD_HEIGHT_MM / 2) * CAD_MM_TO_WORLD));
  shape.closePath();
  // Source drill diameters cut real holes through the PCB substrate.
  const drills = [...(CAD.pads || []), ...(CAD.vias || []), ...(CAD.graphics || []).filter(g => g.kind === 'hole')];
  const seenDrills = new Set();
  for (const drill of drills) {
    const diameter = Number(drill.drill ?? drill.diameter);
    if (!(diameter > 0) || !Number.isFinite(drill.x) || !Number.isFinite(drill.y)) continue;
    const key = JSON.stringify(drillContour(drill));
    if (seenDrills.has(key)) continue;
    seenDrills.add(key);
    const hole = new THREE.Path(drillContour(drill).map(([x,y]) => new THREE.Vector2((x-CAD_WIDTH_MM/2)*CAD_MM_TO_WORLD, -(y-CAD_HEIGHT_MM/2)*CAD_MM_TO_WORLD)));
    shape.holes.push(hole);
  }
  const pcb = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: 1.6, bevelEnabled: false }), material(0x126047, { roughness: 0.76, metalness: 0.05 }));
  pcb.rotation.x = Math.PI / 2;
  pcb.position.y = 0.8;
  pcb.userData = { type: 'cad-pcb', label: `${CAD.meta?.author || 'PE.JADO'} PCB ${CAD_WIDTH_MM}×${CAD_HEIGHT_MM} mm`, source: CAD.meta?.sourceUrl || '' };
  boardRoot.add(pcb);
  staticTargets.push(pcb);
  const padById = new Map((CAD.pads || []).map(pad => [pad.id, pad]));
  for (const pad of CAD.pads || []) addCadPad(pad);
  for (const via of CAD.vias || []) {
    const pointTop = cadToWorld(via.x, via.y, 1.13);
    const pointBottom = cadToWorld(via.x, via.y, -1.13);
    for (const [group, point, side] of [[cadTopGroup, pointTop, 'top'], [cadBottomGroup, pointBottom, 'bottom']]) {
      const ring = mesh(cadPadGeometry({x:via.x,y:via.y,width:Number(via.diameter),height:Number(via.diameter),shape:'ELLIPSE',drill:Number(via.drill),rotation:0}), material(COLORS.copper, { metalness: 0.8, roughness: 0.28 }), point, group, { type: 'cad-via', viaId: via.id, net: via.net || null, label: `${side} via · ${via.net || 'unnamed net'}`, source: 'PE.JADO EasyEDA/Gerber' });
      cadPadTargets.push(ring);
      staticTargets.push(ring);

    }
  }
  for (const track of CAD.tracks || []) {
    const points = (track.points || []).map(point => cadToWorld(point[0], point[1], cadLayerName(track.layer) === 'bottom' ? -0.98 : 0.98));
    if (points.length < 2) continue;
    const curve = cadPolylineCurve(points);
    const line = mesh(new THREE.TubeGeometry(curve, Math.max(4, points.length * 3), Math.max(0.05, Number(track.width) || 0.15) * CAD_MM_TO_WORLD / 2, 6, false), material(cadLayerName(track.layer) === 'bottom' ? 0x9b6430 : COLORS.copper, { roughness: 0.3, metalness: 0.7, emissive: cadLayerName(track.layer) === 'bottom' ? 0x241208 : 0x3e2a0b, emissiveIntensity: 0.08 }), new THREE.Vector3(), cadLayerGroup(track.layer), { type: 'cad-track', trackId: track.id, net: track.net || null, label: `${track.layer || 'copper'} · ${track.net || 'unnamed net'}`, source: 'PE.JADO EasyEDA/Gerber' });
    cadTrackTargets.push(line);
    staticTargets.push(line);
  }
  for (const [index, graphic] of (CAD.graphics || []).entries()) addCadGraphic(graphic, index);
  for (const component of CAD.components || []) addCadComponent(component, padById);
  registerInventory({ id: 'cad-source', label: `${CAD.meta?.author || 'PE.JADO'} · ${CAD_WIDTH_MM}×${CAD_HEIGHT_MM} mm · source-derived`, category: 'CAD board', electrical: 'named nets for inspection; no short-circuit simulation' });
  diagnostics.boardPinMeshes = pinTargets.length;
  updateCadLayerVisibility();
  updateCadNetHighlight();
}

function updateCadLayerVisibility() {
  if (cadTopGroup) cadTopGroup.visible = copperLayer === 'both' || copperLayer === 'top';
  if (cadBottomGroup) cadBottomGroup.visible = copperLayer === 'both' || copperLayer === 'bottom';
  if (cadComponentGroup) cadComponentGroup.visible = cadComponentsVisible;
}

function updateCadNetHighlight() {
  const all = [...cadTrackTargets, ...cadPadTargets, ...cadGraphicTargets];
  for (const object of all) {
    const active = cadNetSelection && object.userData?.net === cadNetSelection;
    const mat = object.material;
    if (!mat?.emissive) continue;
    if (active) {
      mat.emissive.set(0x73f3c4);
      mat.emissiveIntensity = 0.9;
    } else {
      mat.emissive.set(0x000000);
      mat.emissiveIntensity = object.userData?.type === 'cad-track' ? 0.08 : 0;
    }
  }
}

function setBoardPower(on) {
  boardPowered = Boolean(on);
  try { sessionStorage.setItem('stm32-board-power', boardPowered ? 'on' : 'off'); } catch {}
  if (cadPowerLed) { cadPowerLed.material.emissiveIntensity = boardPowered ? 3 : 0; cadPowerLed.material.opacity = boardPowered ? 1 : 0.4; }
  if (cadPowerGlow) cadPowerGlow.intensity = boardPowered ? 2 : 0;
  const button = document.getElementById('boardPower');
  if (button) { button.textContent = boardPowered ? '断电' : '通电'; button.setAttribute('aria-pressed', String(boardPowered)); }
  const readout = document.getElementById('ledreadout');
  if (readout) readout.textContent = boardPowered ? '已通电 · 3.3V · LED1 电源灯常亮（理想电源模型）' : '已断电 · LED1 熄灭';
}

function setCopperLayer(layer = 'both') {
  copperLayer = ['top', 'bottom', 'both'].includes(layer) ? layer : 'both';
  updateCadLayerVisibility();
  dispatch('board3d:copper-layer', { layer: copperLayer });
}

function setComponentsVisible(visible = true) {
  cadComponentsVisible = Boolean(visible);
  updateCadLayerVisibility();
  dispatch('board3d:components-visibility', { visible: cadComponentsVisible });
}

function selectNet(net) {
  cadNetSelection = net ? String(net) : null;
  updateCadNetHighlight();
  dispatch('board3d:net-select', { net: cadNetSelection });
}

function buildBoard() {
  boardRoot = new THREE.Group();
  boardRoot.name = 'Elite-V1-geometric-board';
  scene.add(boardRoot);
  mesh(new THREE.BoxGeometry(115, 1.6, 117), material(COLORS.board, { roughness: 0.72, metalness: 0.05 }), new THREE.Vector3(0, 0, 0), boardRoot, { type: 'pcb', label: 'Elite V1 PCB 115×117×1.6 mm' });
  mesh(new THREE.BoxGeometry(112, 0.22, 114), material(COLORS.boardEdge, { roughness: 0.85 }), new THREE.Vector3(0, -0.92, 0), boardRoot, { type: 'pcb-back' });
  [[32, 31], [883, 31], [32, 891], [883, 891]].forEach(([x, y]) => addMountingHole(x, y));

  const p1 = BOARD.holes.filter(hole => hole.header === 'P1');
  const p2 = BOARD.holes.filter(hole => hole.header === 'P2');
  const p3 = BOARD.holes.filter(hole => hole.header === 'P3');
  const p5 = BOARD.holes.filter(hole => hole.header === 'P5');
  const power = BOARD.holes.filter(hole => hole.header === 'VOUT1' || hole.header === 'VOUT2');
  addHeaderGroup('P1', p1);
  addHeaderGroup('P2', p2);
  addHeaderGroup('P3', p3);
  addHeaderGroup('P5', p5);
  addHeaderGroup('VOUT1', power.filter(hole => hole.header === 'VOUT1'), COLORS.socket);
  addHeaderGroup('VOUT2', power.filter(hole => hole.header === 'VOUT2'), COLORS.socket);
  // P3/P5 expose two additional alias/jumper contacts beside the mapped MCU
  // holes. They are visible geometry-only contacts, so they are not invented
  // as GPIO endpoints in board-map.js.
  addConnector('P3-aliases', 'P3 · CH340 aliases', 126, 469, 2, 2, COLORS.socket);
  addConnector('P5-jumpers', 'P5 · USART2 / RS485', 790, 29, 2, 2, COLORS.socket);
  addDiscrete('P5-jumpcap-1', 'P5 jumper 1–3', 786, 29, 2.8, 4.2, COLORS.yellow);
  addDiscrete('P5-jumpcap-2', 'P5 jumper 2–4', 795, 29, 2.8, 4.2, COLORS.yellow);

  addMcu();
  addConnector('tft', 'TFTLCD 2×17', 496, 65, 2, 17);
  addConnector('wireless', 'WIRELESS 2×4', 72, 100, 2, 4);
  addConnector('jtag', 'JTAG 2×10', 75, 215, 2, 10, COLORS.blue);
  addConnector('oled-camera', 'OLED / CAMERA 2×10', 214, 873, 2, 10);
  addConnector('ds18b20', 'DS18B20 / DHT11', 117, 35, 2, 3);
  addConnector('boot', 'BOOT 2×2', 821, 769, 2, 2, COLORS.socket);
  addConnector('atk', 'ATK MODULE', 865, 452, 1, 8, COLORS.socket);
  addConnector('adda', 'ADDA', 865, 569, 1, 8, COLORS.socket);
  addConnector('can', 'CAN / RS485', 100, 121, 2, 4, COLORS.blue);
  addConnector('buzzer-header', 'BEEP / IR', 481, 885, 2, 4, COLORS.socket);
  addConnector('sd-slot', 'SD SLOT · backside', 690, 877, 1, 8, COLORS.black);

  // The underside is intentionally modeled so an orbit reveals the SD slot
  // and regulator footprint rather than a blank card or a hidden texture.
  const sdBack = mesh(new THREE.BoxGeometry(30, 2.2, 13), material(COLORS.black, { roughness: 0.75 }), nativeToWorld(690, 877, -2.25), boardRoot, { type: 'backside-module', label: 'SD card slot · backside' });
  sdBack.rotation.y = Math.PI / 2;
  registerInventory({ id: 'sd-slot-back', label: 'SD card slot · backside visible on orbit', category: 'back side', electrical: 'not modeled' });

  addChip('w25q128', 'W25Q128', 193, 143, 7.8, 5.4, 8);
  addChip('eeprom-24c02', '24C02', 206, 255, 6.0, 4.6, 8);
  addChip('ch340g', 'CH340G', 187, 686, 9.4, 6.0, 16);
  addChip('can-transceiver', 'CAN IC', 145, 108, 9.5, 6.5, 16, COLORS.component);
  addChip('rs485-transceiver', 'RS485 IC', 127, 135, 9.5, 6.5, 16, COLORS.component);
  addChip('regulator', '3V3 switching regulator', 805, 245, 9, 7, 8, COLORS.component);
  addChip('usb-bridge', 'USB bridge', 168, 755, 9, 6, 16, COLORS.component);

  addDiscrete('dc-barrel', 'DC barrel jack', 853, 95, 9, 13, COLORS.black, 'cylinder');
  addDiscrete('power-toggle', 'power toggle switch', 873, 188, 5, 10, COLORS.black, 'box');
  addDiscrete('usb-mini-1', 'miniUSB · USB SLAVE', 54, 711, 11, 8, COLORS.black);
  addDiscrete('usb-mini-2', 'miniUSB · USB 232', 54, 798, 11, 8, COLORS.black);
  addDiscrete('inductor', 'L1 power inductor', 755, 222, 7, 7, COLORS.silver, 'cylinder');
  addDiscrete('crystal-8mhz', 'Y2 8 MHz crystal', 585, 582, 8, 3, COLORS.silver, 'cylinder');
  addDiscrete('crystal-32khz', 'Y1 32.768 kHz crystal', 567, 642, 7, 2.8, COLORS.silver, 'cylinder');
  addDiscrete('ch340-can', 'CH340 12 MHz metal can', 204, 665, 8, 4, COLORS.silver, 'cylinder');
  addDiscrete('coin-holder', 'CR1220 coin battery holder', 438, 652, 18, 18, COLORS.silver, 'cylinder');
  addDiscrete('buzzer', 'buzzer', 407, 875, 14, 14, COLORS.white, 'cylinder');
  addDiscrete('infrared', 'infrared receiver', 528, 875, 8, 4, COLORS.black);
  addDiscrete('power-led', 'PWR LED', 857, 353, 2.8, 2.8, COLORS.red, 'cylinder');
  addDiscrete('diode-bank', 'switching diodes', 752, 281, 11, 4, COLORS.white);
  addDiscrete('electrolytic-c1', 'electrolytic capacitor', 788, 302, 5, 8, COLORS.silver, 'cylinder');
  addDiscrete('electrolytic-c2', 'electrolytic capacitor', 811, 315, 5, 8, COLORS.silver, 'cylinder');
  const passivePositions = [[320,320], [355,290], [596,287], [630,318], [365,548], [623,550], [710,480], [712,510], [275,754], [690,737], [743,610], [735,657]];
  passivePositions.forEach(([x, y], index) => addDiscrete(`passive-${index + 1}`, `R/C passive ${index + 1}`, x, y, 3.5, 1.8, index % 2 ? COLORS.silver : COLORS.component));

  addTactile('key-up', 'KEY_UP / WK_UP · PA0 · active-high', 868, 636, COLORS.yellow, 'PA0', 1);
  addTactile('key0', 'KEY0 · PE4 · active-low', 868, 688, COLORS.yellow, 'PE4', 0);
  addTactile('key1', 'KEY1 · PE3 · active-low', 868, 739, COLORS.yellow, 'PE3', 0);
  addTactile('reset', 'RESET · red', 868, 790, COLORS.red);
  addOnboardLed('PB5', 'LED0 / DS0 · PB5 · active-low', 856, 389, COLORS.red);
  addOnboardLed('PE5', 'LED1 / DS1 · PE5 · active-low', 856, 421, COLORS.green);

  addSilk('ALIENTEK', 456, 170, 5.5, '#f2f2e9');
  addSilk('ELITE STM32F103', 456, 197, 3.5, '#f2f2e9');
  addSilk('STM32F1 精英版', 456, 224, 2.1, '#d9e7ee');
  addSilk('U1', 430, 508, 1.5, '#d9e7ee');
  addSilk('P2', 248, 180, 2.3, '#f6db8a');
  addSilk('P1', 774, 180, 2.3, '#f6db8a');
  addSilk('TFTLCD', 480, 97, 2.8, '#f6db8a');
  addSilk('3V3', 874, 328, 2.0, '#d4eacb');
  addSilk('5V', 874, 274, 2.0, '#d4eacb');
  // Connector and control markings follow the documented V1 component
  // locations. They are silk labels only; the optional copper overlay below
  // is populated exclusively from supplied board data.
  addSilk('USB_SLAVE', 55, 688, 1.65, '#e8d99a');
  addSilk('USB_232', 55, 820, 1.65, '#e8d99a');
  addSilk('USART1', 190, 622, 1.55, '#e8d99a');
  addSilk('USART2', 780, 67, 1.55, '#e8d99a');
  addSilk('JTAG', 82, 248, 1.75, '#e8d99a');
  addSilk('ATK_MODULE', 826, 492, 1.55, '#e8d99a');
  addSilk('ADDA', 826, 608, 1.65, '#e8d99a');
  addSilk('BOOT', 821, 804, 1.55, '#e8d99a');
  addSilk('VOUT1', 876, 312, 1.35, '#d9d39b');
  addSilk('VOUT2', 876, 258, 1.35, '#d9d39b');
  addSilk('LED0', 823, 389, 1.35, '#f19a98');
  addSilk('LED1', 823, 421, 1.35, '#9de2b0');
  addSilk('KEY_UP', 812, 636, 1.25, '#f2df8d');
  addSilk('KEY0', 823, 688, 1.25, '#f2df8d');
  addSilk('KEY1', 823, 739, 1.25, '#f2df8d');
  addSilk('RESET', 823, 790, 1.25, '#f19a98');
  addSilk('W25Q128', 193, 124, 1.25, '#b7e2d8');
  addSilk('24C02', 206, 237, 1.25, '#b7e2d8');
  addSilk('CH340G', 187, 664, 1.25, '#b7e2d8');
  addSilk('CAN', 145, 87, 1.25, '#b7e2d8');
  addSilk('RS485', 127, 155, 1.25, '#b7e2d8');
  addSilk('PWR', 858, 336, 1.15, '#f19a98');
  buildPcbSurfaceOverlay();
  registerInventory({ id: 'pcb', label: 'PCB 115×117×1.6 mm · geometric mesh', category: 'board', electrical: 'physical endpoint map' });
  diagnostics.boardPinMeshes = pinMeshes.size;
  diagnostics.componentMeshes = inventory.length;
}

function partDefinition(part) {
  const found = globalThis.lab?.catalogue?.find?.(definition => definition.type === part.type);
  if (found) return found;
  const defaults = {
    led: { name: 'LED', pins: ['A', 'K'], color: '#be4444' }, resistor: { name: 'resistor', pins: ['1', '2'], color: '#977950' },
    button: { name: 'button', pins: ['1', '2'], color: '#556478' }, sensor: { name: 'sensor', pins: ['VCC', 'GND', 'OUT'], color: '#386a8c' },
    uart: { name: 'UART', pins: ['TX', 'RX', 'GND'], color: '#3c587c' }, servo: { name: 'servo', pins: ['V+', 'GND', 'PWM'], color: '#366c9b' }, motor: { name: 'motor', pins: ['M+', 'M-', 'VCC', 'GND', 'ENC_A', 'ENC_B'], color: '#827142' }
  };
  return defaults[part.type] || { name: part.type, pins: ['1', '2'], color: '#415568' };
}

function partHeight(definition) {
  return Math.max(75, 45 + definition.pins.length * 18) + (definition.response ? 24 : 0);
}

function clearDynamicGroup(group) {
  if (!group) return;
  while (group.children.length) {
    const object = group.children.pop();
    object.traverse(child => {
      child.geometry?.dispose?.();
      if (Array.isArray(child.material)) child.material.forEach(value => value.dispose?.());
      else child.material?.dispose?.();
    });
  }
}

function addExternalResponseMesh(part, definition, group, width, depth) {
  const result = { partId: part.id, type: part.type, horn: null, rotor: null, dome: null, light: null };
  if (part.type === 'servo') {
    const horn = new THREE.Group();
    horn.position.set(width * 0.28, 4.5, 0);
    const base = mesh(new THREE.CylinderGeometry(3.7, 3.7, 1.0, 24), material(0x26384c, { roughness: 0.42 }), new THREE.Vector3(), horn, { type: 'servo-horn', partId: part.id, label: `${definition.name} horn` });
    const arm = mesh(new THREE.BoxGeometry(1.25, 0.85, 12), material(0xe5e9ef, { roughness: 0.34, metalness: 0.18 }), new THREE.Vector3(0, 0.8, 5.0), horn, { type: 'servo-horn-arm', partId: part.id, label: `${definition.name} horn` });
    base.userData.responsePart = part.id;
    arm.userData.responsePart = part.id;
    group.add(horn);
    result.horn = horn;
  } else if (part.type === 'motor') {
    const rotor = new THREE.Group();
    rotor.position.set(width * 0.27, 4.2, 0);
    mesh(new THREE.CylinderGeometry(6.2, 6.2, 1.35, 24), material(0x18202b, { roughness: 0.32, metalness: 0.42 }), new THREE.Vector3(), rotor, { type: 'motor-rotor', partId: part.id, label: `${definition.name} rotor` });
    mesh(new THREE.CylinderGeometry(1.4, 1.4, 1.8, 16), material(0xbcc8d0, { roughness: 0.25, metalness: 0.75 }), new THREE.Vector3(0, 0.8, 0), rotor, { type: 'motor-hub', partId: part.id, label: `${definition.name} rotor` });
    mesh(new THREE.BoxGeometry(0.9, 0.7, 10.0), material(0x9ce4c6, { roughness: 0.28, metalness: 0.12 }), new THREE.Vector3(0, 1.0, 3.6), rotor, { type: 'motor-rotor-mark', partId: part.id, label: `${definition.name} rotor` });
    group.add(rotor);
    result.rotor = rotor;
  } else if (part.type === 'led') {
    const ledColor = new THREE.Color(definition.color || '#be4444');
    const domeMaterial = material(ledColor, { roughness: 0.22, transparent: true, opacity: 0.38, emissive: ledColor, emissiveIntensity: 0 });
    const dome = mesh(new THREE.SphereGeometry(4.4, 20, 12), domeMaterial, new THREE.Vector3(width * 0.28, 4.7, 0), group, { type: 'external-led-dome', partId: part.id, label: `${definition.name} dome` });
    dome.scale.y = 0.72;
    const light = new THREE.PointLight(ledColor, 0, 22, 2);
    light.position.set(width * 0.28, 5.2, 0);
    group.add(light);
    result.dome = dome;
    result.light = light;
  }
  return result;
}

function updateEndpointMapForOnboard(parts) {
  for (const part of Array.isArray(parts) ? parts : []) {
    if (!part.onboard || !part.signal || !ledPortWorld.has(part.signal)) continue;
    const port = ledPortWorld.get(part.signal);
    endpointWorld.set(`${part.id}:A`, port.clone());
    endpointWorld.set(`${part.id}:K`, new THREE.Vector3(port.x, port.y - 0.3, port.z + 1.8));
  }
}

function buildModules(parts) {
  clearDynamicGroup(moduleGroup);
  moduleMeshes = new Map();
  moduleTargets = [];
  updateEndpointMapForOnboard(parts);
  for (const part of Array.isArray(parts) ? parts : []) {
    if (part.onboard) continue;
    const definition = partDefinition(part);
    const width = 145 * SX;
    const heightSvg = partHeight(definition);
    const depth = heightSvg * SZ;
    const bodyMaterial = material(new THREE.Color(definition.color || '#415568'), { roughness: 0.58, metalness: 0.08 });
    const group = new THREE.Group();
    group.name = `module-${part.id}`;
    group.userData = { type: 'module', partId: part.id, label: definition.name };
    // Keep the library readable beside the physical board without letting a
    // rectangular module body dominate the default board fit.
    group.scale.setScalar(0.66);
    const center = svgToWorld(Number(part.x) + 72.5, Number(part.y) + heightSvg / 2, 4.0);
    group.position.copy(center);
    moduleGroup.add(group);
    const body = mesh(new THREE.BoxGeometry(width, 5.6, depth), bodyMaterial, new THREE.Vector3(0, 0, 0), group, { type: 'module-body', partId: part.id, label: definition.name });
    const title = textSprite(definition.name, '#eef5fa', 2.0, 0.75);
    title.position.set(0, 3.15, -depth / 2 + 4.1);
    title.rotation.x = -Math.PI / 2;
    group.add(title);
    const responseMesh = addExternalResponseMesh(part, definition, group, width, depth);
    const endpoints = new Map();
    definition.pins.forEach((name, index) => {
      const pinZ = -depth / 2 + (53 + index * 18) * SZ;
      const pin = mesh(new THREE.CylinderGeometry(0.72, 0.72, 1.3, 10), material(COLORS.copper, { metalness: 0.84, roughness: 0.25 }), new THREE.Vector3(-width / 2 - 0.5, 2.9, pinZ), group, { type: 'module-pin', partId: part.id, endpointId: `${part.id}:${name}`, label: `${definition.name} · ${name}` });
      endpoints.set(name, pin);
      moduleTargets.push(pin);
      endpointWorld.set(`${part.id}:${name}`, new THREE.Vector3());
    });
    moduleTargets.push(body);
    moduleMeshes.set(part.id, { group, body, endpoints, part, definition, width, depth, heightSvg, responseMesh });
  }
  updateModuleWorldEndpoints();
  updateSelection();
}

function updateModuleWorldEndpoints() {
  for (const entry of moduleMeshes.values()) {
    for (const [name, pin] of entry.endpoints.entries()) {
      pin.getWorldPosition(endpointWorld.get(`${entry.part.id}:${name}`));
    }
  }
}

function endpointPosition(id) {
  if (endpointWorld.has(id)) return endpointWorld.get(id).clone();
  const normalized = BOARD?.normalizeEndpoint?.(id) || id;
  if (endpointWorld.has(normalized)) return endpointWorld.get(normalized).clone();
  if (canonicalPins.has(normalized)) return canonicalPins.get(normalized).position.clone();
  return null;
}

function buildWires(wires) {
  clearDynamicGroup(wireGroup);
  wireTargets = [];
  (Array.isArray(wires) ? wires : []).forEach((wire, index) => {
    const start = endpointPosition(wire.a);
    const end = endpointPosition(wire.b);
    if (!start || !end) return;
    const mid = start.clone().lerp(end, 0.5);
    const rise = Math.max(7, Math.min(26, 7 + start.distanceTo(end) * 0.14));
    const curve = new THREE.CatmullRomCurve3([
      start.setY(Math.max(start.y, 3.0)),
      new THREE.Vector3(mid.x, rise, mid.z),
      end.setY(Math.max(end.y, 3.0))
    ], false, 'centripetal', 0.35);
    const wireMaterial = material(wire.color || '#50c9ef', { roughness: 0.4, metalness: 0.18, emissive: wire.color || '#50c9ef', emissiveIntensity: 0.08 });
    const tube = mesh(new THREE.TubeGeometry(curve, 18, 0.34, 8, false), wireMaterial, new THREE.Vector3(), wireGroup, { type: 'wire', wireIndex: index, endpoints: [wire.a, wire.b] });
    wireTargets.push(tube);
  });
  updateSelection();
}

function updateSelection() {
  const selected = lastState?.selected;
  for (const [id, entry] of moduleMeshes.entries()) {
    const active = selected === id;
    entry.body.material.emissive.set(active ? 0x65d9ba : 0x000000);
    entry.body.material.emissiveIntensity = active ? 0.45 : 0;
  }
  wireTargets.forEach(target => {
    const active = selected === `wire:${target.userData.wireIndex}`;
    target.material.emissive.set(active ? 0xffffff : target.material.color);
    target.material.emissiveIntensity = active ? 0.85 : 0.08;
  });
  pinTargets.forEach(target => {
    const active = target.userData.endpointId === lastState?.pending;
    target.material.emissive.set(active ? 0x66f1cf : 0x000000);
    target.material.emissiveIntensity = active ? 0.75 : 0;
  });
}

function updateExternalResponseMeshes(state) {
  const actuatorStates = state?.actuatorStates || {};
  const ledOn = state?.ledOn || {};
  for (const entry of moduleMeshes.values()) {
    const response = entry.responseMesh;
    if (!response) continue;
    const sample = actuatorStates[entry.part.id] || {};
    if (response.horn) {
      const angle = Number.isFinite(Number(sample.angleDeg)) ? Number(sample.angleDeg) : 90;
      response.horn.rotation.y = THREE.MathUtils.degToRad(Math.max(0, Math.min(180, angle)) - 90);
    }
    if (response.rotor) {
      const count = Number.isFinite(Number(sample.encoderCount)) ? Number(sample.encoderCount) : 0;
      response.rotor.rotation.y = (count % 40) * (Math.PI * 2 / 40);
    }
    if (response.dome) {
      const on = Boolean(ledOn[entry.part.id]);
      response.dome.material.emissiveIntensity = on ? 2.5 : 0;
      response.dome.material.opacity = on ? 0.92 : 0.28;
      if (response.light) response.light.intensity = on ? 2.0 : 0;
    }
  }
}

function updateLedEmission(trace, playTime, durationMs) {
  if (isCadBoard()) {
    const readout = document.getElementById('ledreadout');
    if (readout) readout.textContent = boardPowered ? '已通电 · 3.3V · LED1 电源灯常亮（理想电源模型）' : '已断电 · LED1 熄灭';
    return;
  }
  if (!SIGNALS) return;
  const stamp = `${trace?.length || 0}:${playTime}:${durationMs}`;
  if (stamp === emissionSignature) return;
  emissionSignature = stamp;
  const rows = [];
  for (const [pin, ref] of ledRefs.entries()) {
    const brightness = SIGNALS.brightnessAt(trace, pin, playTime, durationMs, 20);
    ref.brightness = brightness;
    ref.dome.material.emissiveIntensity = brightness * 2.4;
    ref.dome.material.opacity = 0.25 + brightness * 0.68;
    ref.light.intensity = brightness * 2.2;
    rows.push(`${ref.label.split(' · ')[0]} ${Math.round(brightness * 100)}%`);
  }
  const readout = document.getElementById('ledreadout');
  if (readout) readout.textContent = rows.length ? rows.join('  ·  ') : '板载 LED 等待真实 GPIO 轨迹';
}

function updateInventory(state) {
  const panel = document.getElementById('board3d-inventory');
  if (!panel) return;
  const duty = SIGNALS && state?.trace ? SIGNALS.summarize(state.trace, state.durationMs) : null;
  if (isCadBoard()) {
    panel.innerHTML = `
      <summary><strong>${CAD.meta?.author || 'PE.JADO'} · CAD TRUE 3D</strong><span>${CAD.pads?.length || 0} pads · ${CAD.tracks?.length || 0} tracks · ${CAD.components?.length || 0} footprints</span></summary>
      <div class="inventory-body">
        <span class="coverage-line">${CAD_WIDTH_MM.toFixed(3)} × ${CAD_HEIGHT_MM.toFixed(3)} mm · EasyEDA/Gerber source</span>
        <span class="coverage-line">U2 LQFP-144 · ${diagnostics.mcuLegMeshes || 144} source-coordinate legs</span>
        <span class="coverage-line led-line">LED1 is 3V3 power indicator; PB5/PE5 outputs remain external modules</span>
        <span class="coverage-line">Copper: ${copperLayer} · components: ${cadComponentsVisible ? 'visible' : 'hidden'} · net: ${cadNetSelection || 'none'}</span>
        <details><summary>CAD coverage and limits</summary><p>Source-derived pads, named nets, silkscreen graphics, copper tracks, vias and component positions are selectable. Package bodies are approximate where the source omits mechanical dimensions.</p><p>Net highlighting supports engineering inspection only. Crossing traces on different copper layers do not imply a short circuit; no current, clearance or full electrical simulation is claimed.</p><p>Source: <a href="${CAD.meta?.sourceUrl || 'https://oshwhub.com/PE.JADO/stm32f103zet6'}" target="_blank" rel="noreferrer">PE.JADO F103ZE</a> · ${CAD.meta?.license || 'GPL-3.0-only'}.</p></details>
      </div>`;
    return;
  }
  panel.innerHTML = `
    <summary><strong>布局原型 · 非 CAD 还原</strong><span>${BOARD?.holes?.length || 0}/124 pins · 144 MCU legs</span></summary>
    <div class="inventory-body">
      <span class="coverage-line">PCB mesh · ${inventory.length} named physical items</span>
      <span class="coverage-line">orbit reveals backside SD slot</span>
      <span class="coverage-line led-line">LED0 PB5 ${duty ? Math.round(duty.PB5.lowDuty * 100) : 0}% low duty · LED1 PE5 ${duty ? Math.round(duty.PE5.lowDuty * 100) : 0}% low duty</span>
      <details><summary>Model coverage and limits</summary><p>Independent meshes cover connectors, sockets, IC packages, clocks, switches, passives, battery, buzzer, IR receiver and backside slot. GPIO pin picking and wire endpoints are physical contacts.</p><p>GPIO trace support is limited to the firmware runner’s ordinary events; CAN, USB, SDIO, I²C sensors and analogue behaviour remain geometry-only.</p></details>
    </div>`;
}

function sync(next = {}) {
  pendingState = { ...(pendingState || {}), ...next };
  if (!sceneReady) return ready;
  lastState = { parts: [], wires: [], selected: null, pending: null, trace: [], playTime: 0, durationMs: 2000, ...pendingState };
  pendingState = null;
  const parts = Array.isArray(lastState.parts) ? lastState.parts : [];
  const wires = Array.isArray(lastState.wires) ? lastState.wires : [];
  const nextModulesSignature = parts.map(part => `${part.id}:${part.type}:${part.x}:${part.y}:${part.onboard ? 1 : 0}`).join('|');
  const nextWiresSignature = wires.map(wire => `${wire.a},${wire.b},${wire.color}`).join('|') + `#${nextModulesSignature}`;
  if (nextModulesSignature !== modulesSignature) {
    modulesSignature = nextModulesSignature;
    buildModules(parts);
  } else updateModuleWorldEndpoints();
  if (nextWiresSignature !== wiresSignature) {
    wiresSignature = nextWiresSignature;
    buildWires(wires);
  }
  updateSelection();
  updateExternalResponseMeshes(lastState);
  updateLedEmission(lastState.trace, lastState.playTime, lastState.durationMs);
  updateInventory(lastState);
  if (initialFitPending) {
    fitCameraToContent();
    initialFitPending = false;
  }
  if (scene) {
    let count = 0;
    scene.traverse(object => { if (object.isMesh) count += 1; });
    diagnostics.meshCount = count;
  }
}

function setView(view) {
  if (!camera || !controls) return;
  if (view === 'top' || view === 'board') {
    // Native board Y increases toward the USB edge. With -Z as screen-up,
    // USB_SLAVE/USB_232 remain at the lower-left in the documented top view.
    camera.up.set(0, 0, -1);
    camera.position.set(0, 260, 0.01);
  } else {
    camera.up.set(0, 1, 0);
    if (view === 'isometric' || view === 'iso') camera.position.set(132, 118, 150);
    else camera.position.set(120, 105, 130);
  }
  controls.target.set(18, 0, 0);
  fitCameraToContent(view !== 'board');
  controls.update();
}

function zoom(factor) {
  if (!camera || !controls) return;
  const direction = camera.position.clone().sub(controls.target);
  camera.position.copy(controls.target.clone().add(direction.multiplyScalar(1 / factor)));
  controls.update();
  const zoomLabel = document.getElementById('zoomLevel');
  if (zoomLabel) zoomLabel.textContent = `${Math.round(100 * viewDistance / camera.position.distanceTo(controls.target))}%`;
}

function resize() {
  if (!renderer || !camera || !root) return;
  const width = Math.max(1, root.clientWidth);
  const height = Math.max(1, root.clientHeight);
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

// Fit both horizontal and vertical extents. This is essential when the work
// pane is narrow or portrait shaped: fitting only the desktop vertical FOV
// crops the long P1/P2 headers.
function fitCameraToContent(includeModules = true) {
  if (!camera || !controls || !boardRoot || !scene) return;
  scene.updateMatrixWorld(true);
  // Fit the physical board and any user-placed modules together. Wires stay
  // inside this envelope because their endpoints are on these two groups;
  // excluding them avoids a long lifted tube making the board unnecessarily
  // small in a narrow pane.
  const box = new THREE.Box3().setFromObject(boardRoot);
  if (includeModules && moduleGroup) box.expandByObject(moduleGroup);
  if (box.isEmpty()) return;
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const target = box.getCenter(new THREE.Vector3());
  const direction = camera.position.clone().sub(controls.target);
  if (direction.lengthSq() < 0.001) direction.set(1, 0.82, 1.12);
  direction.normalize();
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * Math.max(0.18, camera.aspect));
  const distance = Math.max(
    sphere.radius / Math.tan(verticalFov / 2),
    sphere.radius / Math.tan(horizontalFov / 2)
  ) * 1.08;
  controls.maxDistance = Math.max(420, distance * 2);
  viewDistance = distance;
  const zoomLabel = document.getElementById('zoomLevel');
  if (zoomLabel) zoomLabel.textContent = '100%';
  controls.target.copy(target);
  camera.position.copy(target).add(direction.multiplyScalar(distance));
  controls.minDistance = Math.max(28, distance * 0.22);
  controls.maxDistance = Math.max(420, distance * 4.5);
  controls.update();
}

function showHint(text) {
  const hint = document.getElementById('hint');
  if (!hint) return;
  hint.textContent = text;
  clearTimeout(hintTimer);
  hintTimer = setTimeout(() => { hint.textContent = '左键空白旋转 · 中键平移 · 滚轮缩放 · 点击物理孔位接线'; }, 2600);
}

function raycast(event) {
  if (!renderer || !camera) return [];
  const bounds = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  return raycaster.intersectObjects([...pinTargets, ...moduleTargets, ...wireTargets, ...staticTargets], true);
}

function firstHit(event) {
  const intersections = raycast(event);
  for (const hit of intersections) {
    let object = hit.object;
    // Preserve index 0 and static labels while walking from a child mesh to
    // its semantic target.  A falsy wire index used to make the first wire
    // impossible to select, and unlabeled child meshes climbed too far.
    while (object && object.parent &&
      !object.userData?.endpointId &&
      object.userData?.wireIndex === undefined &&
      !object.userData?.partId &&
      !object.userData?.label &&
      !object.userData?.keyId &&
      !object.userData?.type) object = object.parent;
    if (object) return { hit, object };
  }
  return null;
}

function screenToProject(clientX, clientY) {
  if (!renderer || !camera) return null;
  const bounds = renderer.domElement.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return null;
  pointer.x = ((clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -3);
  const worldPoint = new THREE.Vector3();
  if (!raycaster.ray.intersectPlane(plane, worldPoint)) return null;
  const project = worldToSvg(worldPoint);
  return {
    x: Math.max(0, Math.min(850, project.x - 72.5)),
    y: Math.max(45, Math.min(620, project.y - 45))
  };
}

function dragPoint(event) {
  const bounds = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1;
  pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -3);
  const point = new THREE.Vector3();
  return raycaster.ray.intersectPlane(plane, point) ? point : null;
}

function onPointerDown(event) {
  pointerDown = { x: event.clientX, y: event.clientY, button: event.button };
  if (event.button !== 0) return;
  const hit = firstHit(event);
  if (hit?.object.userData?.partId && hit.object.userData.type === 'module-body') {
    const entry = moduleMeshes.get(hit.object.userData.partId);
    if (entry) {
      const point = dragPoint(event);
      drag = { entry, start: pointerDown, offset: point ? entry.group.position.clone().sub(point) : new THREE.Vector3() };
      controls.enabled = false;
      dispatch('board3d:select', { id: entry.part.id });
    }
  } else if (hit?.object.userData?.keyId) {
    controls.enabled = false;
  } else if (hit?.object.userData?.endpointId) controls.enabled = false;
  else if (hit?.object.userData?.wireIndex !== undefined) controls.enabled = false;
  else if (hit?.object.userData?.net) controls.enabled = false;
}

function onPointerMove(event) {
  const hit = firstHit(event);
  if (!drag) {
    if (hit?.object.userData?.endpointId) showHint(hit.object.userData.address || hit.object.userData.label || hit.object.userData.endpointId);
    else if (hit?.object.userData?.wireIndex !== undefined) showHint(`导线 ${Number(hit.object.userData.wireIndex) + 1} · 点击选中，Delete 删除`);
    else if (hit?.object.userData?.net) showHint(`${hit.object.userData.source || 'CAD'} · net ${hit.object.userData.net} · 点击高亮同网对象`);
    else if (hit?.object.userData?.label) showHint(hit.object.userData.label);
    return;
  }
  const start = pointerDown;
  if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 5) return;
  const point = dragPoint(event);
  if (!point) return;
  drag.entry.group.position.copy(point.add(drag.offset));
  const svg = worldToSvg(drag.entry.group.position);
  drag.entry.part.x = svg.x - 72.5;
  drag.entry.part.y = svg.y - drag.entry.heightSvg / 2;
  updateModuleWorldEndpoints();
  buildWires(lastState?.wires || []);
  dispatch('board3d:part-move', { part: drag.entry.part, committed: false });
}

function onPointerUp(event) {
  const wasDrag = drag;
  if (drag) {
    drag = null;
    controls.enabled = true;
    dispatch('board3d:part-move', { part: wasDrag.entry.part, committed: true });
  }
  const down = pointerDown;
  pointerDown = null;
  if (!down || down.button !== 0 || wasDrag) {
    controls.enabled = true;
    return;
  }
  controls.enabled = true;
  if (Math.hypot(event.clientX - down.x, event.clientY - down.y) >= 5) return;
  const hit = firstHit(event);
  if (hit?.object.userData?.endpointId) {
    dispatch('board3d:pin-click', { id: hit.object.userData.endpointId, address: hit.object.userData.address });
    return;
  }
  if (hit?.object.userData?.wireIndex !== undefined) {
    dispatch('board3d:select', { id: `wire:${hit.object.userData.wireIndex}` });
    return;
  }
  if (hit?.object.userData?.net) {
    selectNet(hit.object.userData.net);
    return;
  }
  if (hit?.object.userData?.keyId) {
    const { keyId, signal, activeLevel } = hit.object.userData;
    const current = keyRefs.get(keyId)?.pressed || false;
    const pressed = !current;
    setKeyState(keyId, pressed);
    dispatch('board3d:key-toggle', { id: keyId, signal, activeLevel, pressed });
    return;
  }
  if (hit?.object.userData?.partId) dispatch('board3d:select', { id: hit.object.userData.partId });
}

let pcbAuditOverlay = null;
let pcbAuditRestore = null;

function clearPcbAuditHighlight() {
  if (pcbAuditOverlay) {
    pcbAuditOverlay.traverse(object => {
      object.geometry?.dispose();
      object.material?.dispose();
    });
    boardRoot.remove(pcbAuditOverlay);
    pcbAuditOverlay = null;
  }
  if (pcbAuditRestore) {
    setComponentsVisible(pcbAuditRestore.components);
    setCopperLayer(pcbAuditRestore.layer);
    camera.position.copy(pcbAuditRestore.position);
    controls.target.copy(pcbAuditRestore.target);
    controls.update();
    const label = document.getElementById('zoomLevel');
    if (label) label.textContent = `${Math.round(100*viewDistance/camera.position.distanceTo(controls.target))}%`;
    pcbAuditRestore = null;
  }
}

function highlightPcbCluster(cluster) {
  clearPcbAuditHighlight();
  if (!cluster || !boardRoot) return;
  pcbAuditRestore = {components:cadComponentsVisible, layer:copperLayer,
    position:camera.position.clone(), target:controls.target.clone()};
  setComponentsVisible(false);
  const layer = cluster.geometry[0].layer;
  setCopperLayer(layer === 2 ? 'bottom' : 'top');
  pcbAuditOverlay = new THREE.Group();
  boardRoot.add(pcbAuditOverlay);
  const bounds = new THREE.Box3();
  for (const polygon of cluster.geometry) {
    const points = polygon.exterior.map(([x,y]) => new THREE.Vector2(
      (x-CAD_WIDTH_MM/2)*CAD_MM_TO_WORLD,(y-CAD_HEIGHT_MM/2)*CAD_MM_TO_WORLD));
    const shape = new THREE.Shape(points);
    for (const ring of polygon.holes) shape.holes.push(new THREE.Path(ring.map(([x,y]) => new THREE.Vector2(
      (x-CAD_WIDTH_MM/2)*CAD_MM_TO_WORLD,(y-CAD_HEIGHT_MM/2)*CAD_MM_TO_WORLD))));
    const surface = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({
      color:0xff5cd1,side:THREE.DoubleSide,transparent:true,opacity:0.85,depthTest:false,depthWrite:false}));
    surface.rotation.x = -Math.PI/2;
    surface.position.y = polygon.layer === 2 ? -1.25 : 1.25;
    surface.renderOrder = 100;
    surface.raycast = () => {};
    pcbAuditOverlay.add(surface);
    for (const [x,y] of polygon.exterior) bounds.expandByPoint(cadToWorld(x,y,0));
  }
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const fov = THREE.MathUtils.degToRad(camera.fov);
  const extent = Math.max(size.x/Math.max(.2,camera.aspect),size.z,12);
  const distance = Math.max(controls.minDistance, extent/Math.tan(fov/2));
  controls.target.copy(center);
  camera.position.copy(center).add(new THREE.Vector3(0,layer === 2 ? -distance : distance,.001));
  controls.update();
  const label = document.getElementById('zoomLevel');
  if (label) label.textContent = `${Math.round(100*viewDistance/distance)}%`;
  showHint('粉色为实际 Gerber 铜轮廓 · 临时隐藏元件 · 尚未判定故障');
}

function createPcbAuditPanel() {
  if (!isCadBoard()) return;
  const panel = document.createElement('details');
  panel.className = 'pcb-audit-panel';
  panel.innerHTML = '<summary>PCB 铜层检查</summary><div class="pcb-audit-body"><p class="pcb-audit-status">正在读取本地报告…</p><p class="pcb-audit-netlist"></p><label>定位未匹配铜块<select aria-label="定位未匹配铜块" disabled><option value="">请选择铜块</option></select></label><p class="pcb-audit-selection">选中后临时隐藏元件，显示真实铜轮廓。</p><p class="pcb-audit-evidence"></p><div class="pcb-audit-actions"><button type="button" class="pcb-audit-clear">清除高亮</button><button type="button" class="pcb-audit-reload">刷新检查</button></div><p>未匹配网络 ≠ 已确认短路。当前仅做铜几何连通性检查，不代表整板可用。</p></div>';
  root.append(panel);
  const select = panel.querySelector('select');
  const status = panel.querySelector('.pcb-audit-status');
  const detail = panel.querySelector('.pcb-audit-selection');
  const evidence = panel.querySelector('.pcb-audit-evidence');
  const categories = {'unnamed-pad':'无网焊盘','copper-text':'铜层文字',mixed:'混合来源',unresolved:'来源待核查'};
  let clusters = [];
  let schematicByPad = new Map();
  const netlistStatus = panel.querySelector('.pcb-audit-netlist');
  const clear = () => { clearPcbAuditHighlight();select.value='';evidence.textContent='';detail.textContent='选中后临时隐藏元件，显示真实铜轮廓。'; };
  select.addEventListener('change', () => {
    const cluster = clusters.find(item => item.id === select.value);
    if (!cluster) { clear();return; }
    highlightPcbCluster(cluster);
    const provenance = cluster.provenance;
    if (provenance) {
      const sources = provenance.evidence.map(item => item.kind === 'unnamed-pad'
        ? `${item.ref || '焊盘'}-${item.number} (${item.id})${item.plannedDrillMm > 0 ? `，计划孔径 ${item.plannedDrillMm.toFixed(3)} mm` : ''}`
        : `铜层文字“${item.text.replaceAll('\\n',' / ')}” (${item.id})`);
      evidence.textContent = `来源：${categories[provenance.category] || '待核查'} · 覆盖 ${(provenance.coveredFraction*100).toFixed(1)}% · ${sources.join('；') || '无几何匹配'}。`;
      const matched = provenance.evidence.map(item => schematicByPad.get(item.id)).filter(Boolean);
      if (matched.length) {
        const statuses = {'explicit-no-connect':'明确 NC（原设计意图，未验证器件要求）',mapped:'已匹配原理图网络','missing-pcb-net':'原理图引脚缺少 PCB 网络',mismatch:'原理图与 PCB 不一致'};
        evidence.textContent += ' 原理图：' + [...new Set(matched.map(item => `${item.terminal} · ${statuses[item.state] || '待核查'}`))].join('；') + '。';
      }
    } else evidence.textContent = '报告尚无来源证据，请重新生成检查报告。';
    detail.textContent = `${cluster.id} · ${cluster.geometry[0].layer === 2 ? '底层' : '顶层'} · ${cluster.areaMm2.toFixed(6)} mm² · 粉色铜轮廓，尚待核查`;
  });
  const load = async () => {
    clear();select.disabled=true;status.textContent='正在读取本地报告…';
    schematicByPad = new Map();netlistStatus.textContent='正在读取原理图核对…';
    select.replaceChildren(new Option('请选择铜块',''));
    try {
      const response = await fetch('/api/pcb-check', {cache:'no-store'});
      const report = await response.json();
      if (!response.ok) throw new Error(report.hint || report.error || '无法读取检查报告');
      if (Math.abs(report.boardSizeMm.width-CAD_WIDTH_MM)>.001 || Math.abs(report.boardSizeMm.height-CAD_HEIGHT_MM)>.001) throw new Error('报告板尺寸与当前板不符，请重新生成');
      if (CAD.meta?.sourceSha256 && report.inputHashes?.[CAD.meta.sourceDocument] !== CAD.meta.sourceSha256) throw new Error('报告与当前3D源数据不符，请重新转换板数据');
      clusters = [...report.unassignedClusters].sort((a,b)=>b.areaMm2-a.areaMm2);
      status.textContent = `网络冲突 ${report.summary.netConflictClusters} · 断连候选 ${report.summary.unconnectedNets} · 未匹配网络 ${clusters.length}`;
      const pth = report.gerberCoverage?.['Gerber_Drill_PTH.DRL'];
      const npth = report.gerberCoverage?.['Gerber_Drill_NPTH.DRL'];
      if (pth && npth) status.textContent += `。已扣除 ${pth.hits+npth.hits} 个钻孔（含 ${pth.slots+npth.slots} 个槽孔）`;
      for (const cluster of clusters) select.add(new Option(`${cluster.id} · ${cluster.geometry[0].layer === 2 ? '底层' : '顶层'} · ${cluster.areaMm2.toFixed(3)} mm² · ${categories[cluster.provenance?.category] || '来源待核查'}`,cluster.id));
      select.disabled=false;
      try {
        const response = await fetch('/api/schematic-check',{cache:'no-store'});
        const schematic = await response.json();
        if (!response.ok) throw new Error(schematic.hint || schematic.error || '原理图报告不可用');
        if (CAD.meta?.sourceSha256 && schematic.inputHashes?.[CAD.meta.sourceDocument] !== CAD.meta.sourceSha256) throw new Error('原理图报告与当前板源数据不符');
        for (const item of schematic.terminalStatus) for (const id of item.padIds) schematicByPad.set(id,item);
        const summary = schematic.summary;
        netlistStatus.textContent = `原理图：匹配 ${summary.matchedTerminals}/${summary.schematicPins} 引脚 · NC ${summary.explicitNoConnectMatched} · 网络差异 ${summary.networkIssues} · 标记异常 ${summary.schematicIssues}。仍待核查：${schematic.missingPcbTerminals.join('、') || '无未匹配位号'}；${summary.unmappedPcbPads} 个焊盘缺元件引用；${summary.labelAliasGroups} 组标签共用连接。`;
        if (select.value) select.dispatchEvent(new Event('change'));
      } catch(error) { netlistStatus.textContent=error.message; }
    } catch(error) { status.textContent=error.message;netlistStatus.textContent='原理图核对未加载'; }
  };
  panel.querySelector('.pcb-audit-clear').addEventListener('click',clear);
  panel.querySelector('.pcb-audit-reload').addEventListener('click',load);
  panel.addEventListener('toggle',()=>{ if (!panel.open) clear(); });
  load();
}

function bindControls() {
  const canvas = renderer.domElement;
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  document.getElementById('viewTop')?.addEventListener('click', () => setView('top'));
  document.getElementById('viewIso')?.addEventListener('click', () => setView('isometric'));
  document.getElementById('viewReset')?.addEventListener('click', () => setView('board'));
  document.getElementById('zoomIn')?.addEventListener('click', () => zoom(1.22));
  document.getElementById('zoomOut')?.addEventListener('click', () => zoom(0.82));
  document.getElementById('zoomReset')?.addEventListener('click', () => setView('reset'));
  document.getElementById('boardPower')?.addEventListener('click', () => setBoardPower(!boardPowered));
  document.getElementById('copperTop')?.addEventListener('click', () => setCopperLayer('top'));
  document.getElementById('copperBottom')?.addEventListener('click', () => setCopperLayer('bottom'));
  document.getElementById('copperBoth')?.addEventListener('click', () => setCopperLayer('both'));
  document.getElementById('toggleCadComponents')?.addEventListener('click', () => setComponentsVisible(!cadComponentsVisible));
  window.addEventListener('resize', resize);
}

function showError(error) {
  diagnostics.renderer = 'unavailable';
  diagnostics.status = 'unsupported';
  if (root) {
    root.innerHTML = '<div class="board3d-error"><strong>WebGL 3D renderer unavailable</strong><span>启用浏览器 WebGL 后才能查看真实几何板卡。没有使用平面照片回退。</span></div>';
  }
  dispatch('board3d:error', { error });
  resolveReady(api);
}

function init() {
  if (!root || !BOARD) {
    showError(new Error('canvas3d or EliteBoardMap is missing'));
    return;
  }
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    diagnostics.renderer = `Three.js r160 · WebGL`;
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0c1722);
    camera = new THREE.PerspectiveCamera(34, 1, 0.1, 800);
    camera.position.set(120, 105, 130);
    raycaster = new THREE.Raycaster();
    pointer = new THREE.Vector2();
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.enablePan = true;
    controls.minDistance = 60;
    controls.maxDistance = 420;
    controls.target.set(18, 0, 0);
    scene.add(new THREE.HemisphereLight(0xbfd9ee, 0x101722, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 3.0);
    key.position.set(80, 180, 90);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0x6aa4d9, 1.3);
    fill.position.set(-120, 70, -160);
    scene.add(fill);
    const underside = new THREE.DirectionalLight(0xd6e7fa, 1.8);
    underside.position.set(20, -120, 40);
    scene.add(underside);
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.MeshStandardMaterial({ color: 0x0a1017, roughness: 0.91, metalness: 0.04 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -4;
    ground.receiveShadow = true;
    scene.add(ground);
    scene.add(new THREE.GridHelper(480, 48, 0x243746, 0x172631));
    if (isCadBoard()) { buildCadBoard(); setBoardPower(boardPowered); }
    else buildBoard();
    moduleGroup = new THREE.Group();
    moduleGroup.name = 'external-modules';
    scene.add(moduleGroup);
    wireGroup = new THREE.Group();
    wireGroup.name = 'wire-tubes';
    scene.add(wireGroup);
    root.replaceChildren(renderer.domElement);
    root.classList.add('ready');
    const panel = document.createElement('details');
    panel.id = 'board3d-inventory';
    panel.className = 'board3d-inventory';
    root.append(panel);
    const ledreadout = document.createElement('div');
    ledreadout.id = 'ledreadout';
    ledreadout.className = 'ledreadout';
    ledreadout.textContent = '板载 LED 等待真实 GPIO 轨迹';
    root.append(ledreadout);
    bindControls();
    createPcbAuditPanel();
    resize();
    sceneReady = true;
    diagnostics.status = 'ready';
    resolveReady(api);
    dispatch('board3d:ready', { api, diagnostics });
    if (pendingState) sync(pendingState);
    const animate = () => {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();
  } catch (error) {
    showError(error);
  }
}

init();
