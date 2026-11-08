// A1 + CONSOLE-3D: free 3D assets for the demo (built by sim/assets/build_glb.py, credits in public/models/CREDITS.json)
// and live/replay bus wiring for the 3D building, robots, depth cloud, debris and supply drops.
//
// - robots.glb (small) loads at idle time in every scene. aftershock.glb (the tower) and the HDRI load only
//   the first time the tower is shown: parsing them costs seconds in software GL, and other scenes never
//   need them. In software WebGL (no GPU, e.g. CI) the tower uses Lambert shading and skips the HDRI.
// - parking_garage HDRI lights the model's materials (reflections only; the background stays the console's).
// - The Scout and Responder primitives are swapped for the Go1 and Rover models, scaled to the
//   footprint the console already draws, so poses, labels and tests are unchanged.
// - The tower model (blocks b1..b27 by scene/loaded id, basements, stair/lift core) is shown only when
//   the sim says the scene is the tower, or with ?building=1 (?building=0 hides it), or via the 3D toggle.
//   For backup, building and levels scenes, MapViewer renders the 3D building directly from scene/loaded.blocks.
// - Above the ground storey the tower is a faint x-ray, so what happens inside stays visible.
// - On world/change, moved blocks fade to a red ghost: where they are now is for the next scan to say.
// - A small credits card lists every asset, its author and licence.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js';
import { on } from './bus';
import type {
  MapViewer,
  SceneLoadedPayload,
  ResponderPosePayload,
  MapPointsPayload,
  ScoutGotoPayload,
  WorldDebrisPayload,
  SimTruthPayload,
  RunnerStagePayload,
  DecisionLogPayload
} from './map';

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
  if (prims.length === 0) return;

  // Measure primitive footprint in unrotated local coordinates so an already-turned robot never skews scale
  const savedPos = group.position.clone();
  const savedRot = group.rotation.clone();
  group.position.set(0, 0, 0);
  group.rotation.set(0, 0, 0);
  group.updateMatrixWorld(true);

  const box = new THREE.Box3();
  prims.forEach(p => box.expandByObject(p));

  group.position.copy(savedPos);
  group.rotation.copy(savedRot);
  group.updateMatrixWorld(true);

  if (box.isEmpty()) return;
  const want = box.getSize(new THREE.Vector3());
  model.updateMatrixWorld(true);
  const have = new THREE.Box3().setFromObject(model).getSize(new THREE.Vector3());
  if (have.x <= 0 || have.y <= 0) return;
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

function creditsCard(credits: Credit[], onToggleTower: () => void, isTowerVisible: () => boolean): HTMLElement {
  const card = document.createElement('details');
  card.id = 'asset-credits';
  card.style.cssText = 'position:fixed;left:12px;bottom:12px;z-index:30;max-width:340px;font:12px/1.4 system-ui,sans-serif;' +
    'background:rgba(15,23,42,.88);color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:6px 10px';
  const summary = document.createElement('summary');
  summary.textContent = '3D asset credits';
  summary.style.cssText = 'cursor:pointer;font-weight:600';
  card.appendChild(summary);

  const toggleBtn = document.createElement('button');
  toggleBtn.type = 'button';
  toggleBtn.id = 'btn-toggle-tower-glb';
  toggleBtn.textContent = isTowerVisible() ? 'Tower GLB mesh: ON' : 'Tower GLB mesh: auto / toggle';
  toggleBtn.style.cssText = 'margin:6px 0 4px;padding:3px 8px;font:11px/1.3 system-ui,sans-serif;cursor:pointer;' +
    'background:#1e293b;color:#7dd3fc;border:1px solid #38bdf8;border-radius:5px;display:block;width:100%';
  toggleBtn.addEventListener('click', e => {
    e.stopPropagation();
    onToggleTower();
    toggleBtn.textContent = isTowerVisible() ? 'Tower GLB mesh: ON' : 'Tower GLB mesh: OFF (scene blocks)';
  });
  card.appendChild(toggleBtn);

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
    showBuilding: () => {},
    markMoved: () => {},
  };
  (window as unknown as { aftershockAssets: DemoAssets }).aftershockAssets = state;

  let forced = buildingParam();
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
    viewer.setGlbBuildingVisible?.(state.buildingVisible);
  };
  state.showBuilding = (show: boolean) => {
    towerScene = show;
    if (forced !== null && forced !== show) forced = show;
    if (forced ?? towerScene) loadTower();
    apply();
  };
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
  on('scene/loaded', data => {
    clearMoved();
    const payload = data as SceneLoadedPayload;
    viewer.updateSceneLoaded?.(payload);
    state.showBuilding(payload?.scene === 'tower');
  });
  on('world/change', data => {
    state.worldChanges += 1;
    if (forced ?? towerScene) state.markMoved((data as { moved_blocks?: string[] })?.moved_blocks ?? []);
  });

  // Wire continuous 3D robot poses, live point clouds, debris and multi-level stage traces to MapViewer
  on('responder/pose', data => {
    viewer.updateResponderPose?.(data as ResponderPosePayload);
  });
  on('map/points', data => {
    viewer.updateMapPoints?.(data as MapPointsPayload);
  });
  on('scout/goto', data => {
    viewer.updateScoutGoto?.(data as ScoutGotoPayload);
  });
  on('world/debris', data => {
    viewer.updateWorldDebris?.(data as WorldDebrisPayload);
  });
  on('sim/truth', data => {
    viewer.updateSimTruth?.(data as SimTruthPayload);
  });
  on('_runner/stage', data => {
    viewer.updateRunnerStage?.(data as RunnerStagePayload);
  });
  on('log/decision', data => {
    viewer.onDecisionLog?.(data as DecisionLogPayload);
  });

  const software = softwareGl(viewer.renderer);
  state.softwareGl = software;
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
      if (credits.length) {
        const existing = document.getElementById('asset-credits');
        if (existing) existing.remove();
        document.body.appendChild(
          creditsCard(
            credits,
            () => state.showBuilding(!state.buildingVisible),
            () => state.buildingVisible
          )
        );
      }
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
    const kit = root.getObjectByName('first_aid_kit');
    swapInto(internals.scoutGroup, scout);
    swapInto(internals.responderGroup, responder);
    if (kit) {
      viewer.setSupplyTemplate?.(kit);
    }
    lit.push(...[scout, responder, kit].filter((o): o is THREE.Object3D => !!o));
    light();
    state.robotsLoaded = true;
  }, undefined, fail('robot models')), { timeout: 2000 });

  let towerRequested = false;
  function loadTower(): void {
    if (towerRequested) return;
    towerRequested = true;
    if (!software) loadHdr();
    new GLTFLoader().load(`${BASE}aftershock.glb`, gltf => {
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
