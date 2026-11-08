import * as THREE from 'three';
import { on } from './bus';
import type { MapViewer, MapCellsPayload, HazardRecord, CasualtyRecord } from './map';
import './interior.css';

const CAPACITY = 60000;
const colors = { surface: 0x94a3b8, free: 0x38bdf8, risk: 0xf59e0b, collapsed: 0xef4444, exclusion: 0xc084fc };
const finite3 = (v: unknown): v is [number, number, number] => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);

/** An observation layer only: unseen space is never filled from scene geometry. */
export function setupInterior(viewer: MapViewer): void {
  const panel = document.createElement('details');
  panel.id = 'interior-panel';
  panel.open = true;
  panel.innerHTML = `<summary>Observed interior · AFTERLIGHT</summary>
    <p id="interior-source">Awaiting scan-derived map</p>
    <div class="interior-actions">
      <label><input id="interior-show-free" type="checkbox" checked> Observed free space</label>
      <label><input id="interior-show-surfaces" type="checkbox" checked> Surfaces</label>
      <button id="interior-frame" type="button">Frame observations</button>
    </div>
    <label>Height slice <select id="interior-layer" aria-label="Interior height slice"><option value="all">All observed heights</option></select></label>
    <output id="interior-counts" aria-live="polite">No observations</output>
    <p class="interior-key"><span>Blue: observed free space</span> · grey: measured surface · amber/red: risk/collapse estimate · purple: keep out</p>
    <p>Free space is a measured void candidate, not a clearance certificate. Blank space is unknown. No simulation geometry is used.</p>
    <ul id="interior-casualties" aria-label="Casualty observation locations"></ul>`;
  document.querySelector('#map-panel')!.append(panel);
  const source = panel.querySelector<HTMLElement>('#interior-source')!;
  const counts = panel.querySelector<HTMLOutputElement>('#interior-counts')!;
  const layer = panel.querySelector<HTMLSelectElement>('#interior-layer')!;
  const showFree = panel.querySelector<HTMLInputElement>('#interior-show-free')!;
  const showSurfaces = panel.querySelector<HTMLInputElement>('#interior-show-surfaces')!;
  const list = panel.querySelector<HTMLUListElement>('#interior-casualties')!;
  const group = new THREE.Group();
  group.name = 'observed-interior';
  viewer.scene.add(group);
  const cube = new THREE.BoxGeometry(1, 1, 1);
  const free = new THREE.InstancedMesh(cube, new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.16, depthWrite: false }), CAPACITY);
  const surfaces = new THREE.InstancedMesh(cube, new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95 }), CAPACITY);
  free.name = 'observed-free-voids';
  surfaces.name = 'observed-interior-surfaces';
  for (const mesh of [free, surfaces]) {
    mesh.count = 0;
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    mesh.frustumCulled = false;
    group.add(mesh);
  }
  let cells: MapCellsPayload['cells'] = [];
  let resolution = 0.05;
  let hazards = new Map<string, HazardRecord & { exclusion?: boolean }>();
  let casualties: CasualtyRecord[] = [];
  let scheduled = false;
  let lastT = 0;
  const transform = new THREE.Object3D();
  const tint = new THREE.Color();
  let bounds = new THREE.Box3();

  function visible(z: number): boolean {
    return layer.value === 'all' || Math.floor(z / resolution) === Number(layer.value);
  }
  function render(): void {
    scheduled = false;
    let nf = 0, ns = 0;
    let inferred = 0;
    let clipped = 0;
    bounds = new THREE.Box3();
    for (const c of cells) {
      if (c.state !== 'seen') { if (c.state === 'inferred') inferred++; continue; }
      const [i, j, k] = c.cell;
      if (!visible((k + 0.5) * resolution)) continue;
      const mesh = c.occupied ? surfaces : free;
      const n = c.occupied ? ns : nf;
      if (n >= CAPACITY) { clipped++; continue; }
      const p = new THREE.Vector3((i + 0.5) * resolution, (j + 0.5) * resolution, (k + 0.5) * resolution);
      bounds.expandByPoint(p);
      const hazard = hazards.get(c.cell.join(','));
      const color = hazard?.exclusion ? colors.exclusion : hazard?.status === 'collapsed' ? colors.collapsed : hazard?.status === 'at_risk' ? colors.risk : c.occupied ? colors.surface : colors.free;
      transform.position.copy(p);
      transform.scale.setScalar(resolution * (c.occupied ? 0.95 : 0.82));
      transform.updateMatrix();
      mesh.setMatrixAt(n, transform.matrix);
      mesh.setColorAt(n, tint.setHex(color));
      if (c.occupied) ns++; else nf++;
    }
    for (const [mesh, n] of [[free, nf], [surfaces, ns]] as const) {
      mesh.count = n;
      mesh.instanceMatrix.needsUpdate = true;
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
    viewer.renderer.clippingPlanes = layer.value === 'all' ? [] : [
      new THREE.Plane(new THREE.Vector3(0, 0, 1), -Number(layer.value) * resolution),
      new THREE.Plane(new THREE.Vector3(0, 0, -1), (Number(layer.value) + 1) * resolution),
    ];
    free.visible = showFree.checked;
    surfaces.visible = showSurfaces.checked;
    counts.textContent = `${ns.toLocaleString()} surfaces · ${nf.toLocaleString()} observed free cells · ${inferred.toLocaleString()} inferred not counted${clipped ? ` · ${clipped} over display cap` : ''}`;
    source.textContent = `Scan-derived map · t=${lastT.toFixed(1)} s · ${resolution.toFixed(3)} m cells`;
    list.replaceChildren();
    for (const casualty of casualties) {
      if (!finite3(casualty.pos) || !visible(casualty.pos[2])) continue;
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = `${casualty.id} · ${Math.round(casualty.confidence * 100)}% estimate · z ${casualty.pos[2].toFixed(2)} m`;
      button.addEventListener('click', () => frame(new THREE.Box3().setFromCenterAndSize(new THREE.Vector3(...casualty.pos), new THREE.Vector3(1.5, 1.5, 1.5))));
      item.append(button);
      list.append(item);
    }
  }
  function schedule(): void {
    if (!scheduled) { scheduled = true; requestAnimationFrame(render); }
  }
  function frame(box: THREE.Box3): void {
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(0.5, box.getSize(new THREE.Vector3()).length() / 2);
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(viewer.camera.fov / 2)) * Math.max(1, 1 / viewer.camera.aspect);
    const direction = viewer.camera.position.clone().sub(viewer.controls.target).normalize();
    if (!direction.lengthSq()) direction.set(1, -1, 1).normalize();
    viewer.controls.target.copy(center);
    viewer.camera.position.copy(center).addScaledVector(direction, distance * 1.2);
    viewer.camera.far = Math.max(100, distance * 8);
    viewer.camera.updateProjectionMatrix();
    viewer.controls.update();
  }
  panel.querySelector('#interior-frame')!.addEventListener('click', () => frame(bounds));
  layer.addEventListener('change', schedule);
  showFree.addEventListener('change', schedule);
  showSurfaces.addEventListener('change', schedule);
  on('map/cells', data => {
    const map = data as MapCellsPayload;
    if (!map || !Array.isArray(map.cells) || !Number.isFinite(map.res) || map.res <= 0) return;
    cells = map.cells.filter(c => finite3(c.cell) && c.cell.every(Number.isInteger));
    resolution = map.res;
    lastT = Number.isFinite(map.t) ? map.t : 0;
    const previous = layer.value;
    layer.replaceChildren(new Option('All observed heights', 'all'));
    for (const k of [...new Set(cells.filter(c => c.state === 'seen').map(c => c.cell[2]))].sort((a,b) => a-b)) {
      layer.add(new Option(`z ${((k + 0.5) * resolution).toFixed(2)} m`, String(k)));
    }
    layer.value = [...layer.options].some(o => o.value === previous) ? previous : 'all';
    schedule();
  });
  on('map/hazards', data => {
    if (!Array.isArray(data)) return;
    hazards = new Map(data.filter(h => h && finite3(h.cell)).map(h => [h.cell.join(','), h]));
    schedule();
  });
  on('map/casualties', data => {
    if (!Array.isArray(data)) return;
    casualties = data;
    schedule();
  });
}
