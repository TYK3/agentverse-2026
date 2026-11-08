// A1: free 3D assets for the demo (built by sim/assets/build_glb.py, credits in public/models/CREDITS.json).
//
// - robots.glb (small) loads at idle time in every scene. aftershock.glb (the tower) and the HDRI load only
//   the first time the tower is shown: parsing them costs seconds in software GL, and other scenes never
//   need them. In software WebGL (no GPU, e.g. CI) the tower is aftershock_lite.glb (same nodes, no textures,
//   from sim/assets/build_lod.py), drawn with Lambert shading and no HDRI; ?lod=full loads the full one anyway.
// - parking_garage HDRI lights the model's materials (reflections only; the background stays the console's).
// - The Scout and Responder primitives are swapped for the Go1 and Rover models, scaled to the
//   footprint the console already draws, so poses, labels and tests are unchanged.
// - The tower model (blocks b1..b27 by scene/loaded id, basements, stair/lift core) is shown only when
//   the sim says the scene is the tower, or with ?building=1 (?building=0 hides it). It is the scene the
//   simulator runs, not what perception has mapped; casualties are not in it.
// - Above the ground storey the tower is a faint x-ray, so what happens inside stays visible.
// - On world/change, moved blocks fade to a red ghost: where they are now is for the next scan to say.
// - A small credits card lists every asset, its author and licence.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js';
import { on } from './bus';
import type { MapViewer } from './map';

export interface Credit { asset: string; author: string; source: string; licence: string; used_for: string }

export interface DemoAssets {
  loaded: boolean;               // the tower model (loaded the first time the tower is shown)
  robotsLoaded: boolean;
  error?: string;
  buildingVisible: boolean;
  blocks: string[];
  credits: Credit[];
  movedBlocks: string[];
  worldChanges: number;          // world/change messages seen (any scene)
  softwareGl: boolean;           // CPU WebGL: the tower is drawn with Lambert shading and no HDRI
  towerFile: string;             // which tower model loads: aftershock.glb, or aftershock_lite.glb in software GL
  showBuilding(show: boolean): void;
  markMoved(ids: string[]): void;
}

const BASE = `${import.meta.env.BASE_URL}models/`;
const MOVED = new THREE.MeshStandardMaterial({ color: 0xff4d4d, transparent: true, opacity: 0.28, depthWrite: false });

function buildingParam(): boolean | null {
  const v = new URLSearchParams(window.location.search).get('building');
  return v === null ? null : v !== '0';
}

/** Scale `model` uniformly so its footprint fits the meshes `group` draws now, then hide those meshes. */
function swapInto(group: THREE.Object3D | undefined, model: THREE.Object3D | undefined): void {
  if (!group || !model) return;
  const prims = group.children.filter(c => (c as THREE.Mesh).isMesh);
  const box = new THREE.Box3();
  prims.forEach(p => box.expandByObject(p));
  if (box.isEmpty()) return;
  const want = box.getSize(new THREE.Vector3());
  const have = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  const s = Math.min(want.x / have.x, want.y / have.y);
  model.scale.setScalar(s);
  model.position.set(0, 0, 0);
  prims.forEach(p => { p.visible = false; });
  group.add(model);
}

// Everything above the ground storey (the robots' floor) is drawn as a faint x-ray, so routes, robots and
// map cells inside the tower stay visible from the console's camera; the ground storey stays solid.
const XRAY_ABOVE_M = 0.95;
const xrayed = new Map<THREE.Material, THREE.Material>();

function xray(mesh: THREE.Mesh): void {
  if (new THREE.Box3().setFromObject(mesh).min.z < XRAY_ABOVE_M) return;
  const mat = mesh.material as THREE.Material;
  if (!xrayed.has(mat)) {
    const ghost = mat.clone();
    ghost.transparent = true;
    ghost.opacity = 0.22;
    ghost.depthWrite = false;
    xrayed.set(mat, ghost);
  }
  mesh.material = xrayed.get(mat)!;
}

/** True when WebGL runs on the CPU (SwiftShader, llvmpipe): no GPU to spend on PBR shading. */
function softwareGl(renderer: THREE.WebGLRenderer): boolean {
  const gl = renderer.getContext();
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  const name = String(info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
  return /swiftshader|llvmpipe|softpipe|software/i.test(name);
}

const cheap = new Map<THREE.Material, THREE.Material>();

/** The same colour, texture and x-ray opacity with Lambert shading: about twice the frame rate in software GL. */
function cheapen(mesh: THREE.Mesh): void {
  const mat = mesh.material as THREE.MeshStandardMaterial;
  if (!mat.isMeshStandardMaterial) return;
  if (!cheap.has(mat)) {
    cheap.set(mat, new THREE.MeshLambertMaterial({ color: mat.color, map: mat.map, transparent: mat.transparent,
                                                   opacity: mat.opacity, depthWrite: mat.depthWrite }));
  }
  mesh.material = cheap.get(mat)!;
}

function creditsCard(credits: Credit[]): HTMLElement {
  const card = document.createElement('details');
  card.id = 'asset-credits';
  card.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:30;max-width:340px;font:12px/1.4 system-ui,sans-serif;' +
    'background:rgba(15,23,42,.88);color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:6px 10px';
  const summary = document.createElement('summary');
  summary.textContent = '3D asset credits';
  summary.style.cssText = 'cursor:pointer;font-weight:600';
  card.appendChild(summary);
  const list = document.createElement('ul');
  list.style.cssText = 'margin:6px 0 2px;padding-left:16px';
  for (const c of credits) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = c.source;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = c.asset;
    a.style.color = '#7dd3fc';
    li.append(a, ` by ${c.author} (${c.licence}): ${c.used_for}`);
    list.appendChild(li);
  }
  card.appendChild(list);
  return card;
}

export function setupDemoAssets(viewer: MapViewer): DemoAssets {
  const state: DemoAssets = {
    loaded: false,
    robotsLoaded: false,
    buildingVisible: false,
    blocks: [],
    credits: [],
    movedBlocks: [],
    worldChanges: 0,
    softwareGl: false,
    towerFile: 'aftershock.glb',
    showBuilding: () => {},
    markMoved: () => {},
  };
  (window as unknown as { aftershockAssets: DemoAssets }).aftershockAssets = state;

  const forced = buildingParam();
  let towerScene = false;
  let building: THREE.Object3D | undefined;
  let annex: THREE.Object3D | undefined;
  const pendingMoved = new Set<string>();
  const original = new Map<string, THREE.Material | THREE.Material[]>();

  const apply = () => {
    const show = forced ?? towerScene;
    state.buildingVisible = !!building && show;
    if (building) building.visible = show;
    if (annex) annex.visible = show;
  };
  state.showBuilding = (show: boolean) => { towerScene = show; if (forced ?? towerScene) loadTower(); apply(); };
  const clearMoved = () => {
    pendingMoved.clear();
    state.movedBlocks = [];
    original.forEach((mat, id) => {
      const block = building?.getObjectByName(id) as THREE.Mesh | undefined;
      if (block) block.material = mat;
    });
    original.clear();
  };
  state.markMoved = (ids: string[]) => {
    ids.forEach(id => pendingMoved.add(id));
    if (!building) return;
    for (const id of pendingMoved) {
      const block = building.getObjectByName(id) as THREE.Mesh | undefined;
      if (!block?.isMesh) continue;
      if (!original.has(id)) original.set(id, block.material);
      block.material = MOVED;
      if (!state.movedBlocks.includes(id)) state.movedBlocks.push(id);
    }
  };

  // Block ids are per scene (the backup scene's b7 is not the tower's b7): a new scene clears the ghosts,
  // and a world/change only marks tower blocks while the tower is the scene shown.
  on('scene/loaded', data => { clearMoved(); state.showBuilding((data as { scene?: string })?.scene === 'tower'); });
  on('world/change', data => {
    state.worldChanges += 1;
    if (forced ?? towerScene) state.markMoved((data as { moved_blocks?: string[] })?.moved_blocks ?? []);
  });

  const software = softwareGl(viewer.renderer);
  state.softwareGl = software;
  state.towerFile = software && new URLSearchParams(window.location.search).get('lod') !== 'full'
    ? 'aftershock_lite.glb' : 'aftershock.glb';
  const internals = viewer as unknown as { scoutGroup?: THREE.Group; responderGroup?: THREE.Group };

  // The HDRI lights only the model's own materials, not scene.environment: that would put image-based
  // lighting on every console material (thousands of map cells) and halve the frame rate in software GL.
  let envTex: THREE.Texture | undefined;
  const lit: THREE.Object3D[] = [];
  const light = () => {
    if (!envTex) return;
    for (const part of lit.splice(0)) {
      part.traverse(o => {
        const mats = ([] as THREE.Material[]).concat((o as THREE.Mesh).material ?? []);
        for (const m of mats) {
          const std = m as THREE.MeshStandardMaterial;
          if (!std.isMeshStandardMaterial) continue;
          std.envMap = envTex!;
          std.envMapIntensity = 0.6;
          std.envMapRotation.set(Math.PI / 2, 0, 0);   // the HDRI is y-up; the console is z-up
          std.needsUpdate = true;
        }
      });
    }
  };
  let hdrRequested = false;
  const loadHdr = () => {
    if (hdrRequested) return;
    hdrRequested = true;
    new HDRLoader().load(`${BASE}parking_garage_1k.hdr`, tex => {
      tex.mapping = THREE.EquirectangularReflectionMapping;
      envTex = tex;
      light();
    }, undefined, () => { /* lighting falls back to the console's own lights */ });
  };

  fetch(`${BASE}CREDITS.json`)
    .then(r => (r.ok ? r.json() : []))
    .then((credits: Credit[]) => {
      state.credits = credits;
      if (credits.length) document.body.appendChild(creditsCard(credits));
    })
    .catch(() => {});

  const fail = (what: string) => (err: unknown) => {
    state.error = String(err);
    console.error(`[assets] ${what} failed to load; the console keeps its own primitives`, err);
  };

  // The robots load after the page has painted and the first messages are in: they are only decoration.
  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void })
    .requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 500));
  idle(() => new GLTFLoader().load(`${BASE}robots.glb`, gltf => {
    const root = gltf.scene;                 // exported in the scene frame (z up): no rotation needed
    const scout = root.getObjectByName('scout');
    const responder = root.getObjectByName('responder');
    swapInto(internals.scoutGroup, scout);
    swapInto(internals.responderGroup, responder);
    lit.push(...[scout, responder].filter((o): o is THREE.Object3D => !!o));
    light();
    state.robotsLoaded = true;
  }, undefined, fail('robot models')), { timeout: 2000 });

  let towerRequested = false;
  function loadTower(): void {
    if (towerRequested) return;
    towerRequested = true;
    if (!software) loadHdr();
    new GLTFLoader().load(`${BASE}${state.towerFile}`, gltf => {
      const root = gltf.scene;
      building = root.getObjectByName('building');
      annex = root.getObjectByName('annex');
      for (const part of [building, annex]) {
        if (!part) continue;
        viewer.scene.add(part);
        part.updateMatrixWorld(true);
        part.traverse(o => {
          if (!(o as THREE.Mesh).isMesh) return;
          xray(o as THREE.Mesh);
          if (software) cheapen(o as THREE.Mesh);
        });
      }
      state.blocks = building ? building.children.map(c => c.name).filter(n => /^b\d+$/.test(n)) : [];
      lit.push(...[building, annex].filter((o): o is THREE.Object3D => !!o));
      light();
      state.loaded = true;
      apply();
      state.markMoved([]);
    }, undefined, fail('tower model'));
  }
  if (forced) idle(loadTower, { timeout: 2000 });
  return state;
}
