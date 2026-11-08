// BLENDER-LOOK: the console's look, built on the Blender models from tools/blender/build_scene.py.
//
// - Scout and Responder models (public/models/blender_{scout,responder}.glb) at their full envelopes
//   (0.33 x 0.23 x 0.29 m and 0.52 x 0.44 x 0.75 m), following the live poses: the Scout follows whatever the
//   map last set for it (sensors/scout, fixtures, replay), the Responder follows responder/pose (the sim's
//   real pose, 10 Hz) and otherwise the map's Responder marker. Motion is eased between samples; a jump
//   over SNAP_M is drawn as a jump, never smoothed into a fake drive. Labels stay on the map's own markers.
// - The collapsed tower (public/models/blender_tower.glb: ground, L1, L2 from sim/scenes/tower.xml plus the
//   illustrative B1..B3 basements) loads only when the tower is the scene, or with ?look=tower.
//   Storeys above ground are drawn faint so what happens inside stays visible; basement south walls are cut
//   away. It is the scene the simulator runs (and, below ground, a proposal), not what perception mapped.
// - PBR lighting (hemisphere + warm key + two amber emergency lamps; headlight beams are additive cones), exponential fog and a
//   slow drift of dust (static under prefers-reduced-motion).
// - ?look=0 turns all of it off. A model that fails to load leaves the console's own primitives in place.
//
// glTF is +Y up; the console is the MuJoCo frame (Z up), so each loaded scene is rotated once, +90 deg about X.

import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { on } from './bus';
import type { MapViewer } from './map';

export interface LookState {
  enabled: boolean;
  robotsLoaded: boolean;
  towerLoaded: boolean;
  towerVisible: boolean;
  error?: string;
  dust: number;
  responderPoses: number;
  showTower(show: boolean): void;
}

const BASE = `${import.meta.env.BASE_URL}models/`;
const SCOUT_ORIGIN_Z = 0.075;     // sim: the Scout's body origin is its sensor origin, 0.075 m above the floor
const RESPONDER_ORIGIN_Z = 0.05;  // sim: the Responder's body origin is its chassis centre, 0.05 m up
const SNAP_M = 0.75;              // a pose jump longer than this is shown as a jump
const EASE_S = 0.12;              // time constant for easing between pose samples
const DUST_COUNT = 700;

interface Follower {
  model: THREE.Object3D;
  target: THREE.Vector3;
  yaw: number;
  has: boolean;
}

function lookParam(): string | null {
  return new URLSearchParams(window.location.search).get('look');
}

/** Pose z is the body origin; the models stand on z = 0. Fixtures that already give floor height (z = 0) stay. */
function floorZ(z: number, origin: number): number {
  return Math.abs(z) < 0.01 ? z : z - origin;
}

function upright(root: THREE.Object3D): THREE.Group {
  const g = new THREE.Group();
  root.rotation.x = Math.PI / 2;      // glTF +Y up -> console +Z up, once
  g.add(root);
  return g;
}

function dustSprite(): THREE.Texture {
  const c = document.createElement('canvas');
  c.width = c.height = 32;
  const ctx = c.getContext('2d')!;
  const grad = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
  grad.addColorStop(0, 'rgba(255,240,215,0.9)');
  grad.addColorStop(0.4, 'rgba(230,210,180,0.35)');
  grad.addColorStop(1, 'rgba(200,190,170,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 32, 32);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function kelvin(k: number): THREE.Color {
  // Tanner Helland's blackbody fit, good enough for lamp tints.
  const t = k / 100;
  const r = t <= 66 ? 255 : 329.7 * Math.pow(t - 60, -0.1332);
  const g = t <= 66 ? 99.47 * Math.log(t) - 161.1 : 288.1 * Math.pow(t - 60, -0.0755);
  const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5 * Math.log(t - 10) - 305.0;
  const c = (v: number) => Math.min(255, Math.max(0, v)) / 255;
  return new THREE.Color().setRGB(c(r), c(g), c(b), THREE.SRGBColorSpace);
}

export function setupLook(viewer: MapViewer): LookState {
  const param = lookParam();
  const state: LookState = {
    enabled: param !== '0',
    robotsLoaded: false,
    towerLoaded: false,
    towerVisible: false,
    dust: 0,
    responderPoses: 0,
    showTower: () => {},
  };
  (window as unknown as { aftershockLook: LookState }).aftershockLook = state;
  if (!state.enabled) return state;

  const scene = viewer.scene;
  const internals = viewer as unknown as { scoutGroup: THREE.Group; responderGroup: THREE.Group };
  const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

  // ---- light and air ---------------------------------------------------------------------------------
  scene.traverse(o => {
    if ((o as THREE.AmbientLight).isAmbientLight) (o as THREE.AmbientLight).intensity = 0.6;
  });
  scene.background = new THREE.Color(0x0b1119);
  scene.fog = new THREE.FogExp2(0x0b1119, 0.04);
  const hemi = new THREE.HemisphereLight(0xdbe8ff, 0x4a3c2c, 1.1);
  hemi.position.set(0, 0, 1);
  const key = new THREE.DirectionalLight(kelvin(5200), 1.6);
  key.position.set(4, -5, 7);
  const look = new THREE.Group();
  look.name = 'blender-look';
  look.add(hemi, key);
  // Two emergency lamps (dynamic lights are the costly part in software GL): ground portal warm 4200 K,
  // B1 portal amber 3000 K. B2/B3 stay dark on purpose (spec: darker with depth, red only for blocked).
  // They light the tower, so they live in its group and cost nothing until the tower is shown.
  const lamps = new THREE.Group();
  lamps.name = 'emergency-lamps';
  for (const [x, y, z, k, i] of [[-0.3, -1.35, 0.85, 4200, 1.6], [1.8, 0.5, -0.2, 3000, 0.9]] as const) {
    const lamp = new THREE.PointLight(kelvin(k), i, 3.2, 1.6);
    lamp.position.set(x, y, z);
    lamps.add(lamp);
  }
  scene.add(look);

  // Dust: sparse motes in and around the tower, drifting slowly and settling.
  const dustPos = new Float32Array(DUST_COUNT * 3);
  const dustVel = new Float32Array(DUST_COUNT * 3);
  let seed = 8112026;
  const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 4294967296);
  const respawn = (i: number, anyHeight: boolean) => {
    dustPos[i * 3] = -2.4 + rand() * 4.8;
    dustPos[i * 3 + 1] = -1.9 + rand() * 3.8;
    dustPos[i * 3 + 2] = anyHeight ? rand() * 2.4 : 2.4;
    dustVel[i * 3] = (rand() - 0.5) * 0.02;
    dustVel[i * 3 + 1] = (rand() - 0.5) * 0.02;
    dustVel[i * 3 + 2] = -0.005 - rand() * 0.02;
  };
  for (let i = 0; i < DUST_COUNT; i++) respawn(i, true);
  const dustGeom = new THREE.BufferGeometry();
  dustGeom.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  const dust = new THREE.Points(dustGeom, new THREE.PointsMaterial({
    size: 0.03, map: dustSprite(), transparent: true, opacity: 0.55, depthWrite: false,
    blending: THREE.AdditiveBlending, color: 0xd9c9ad, sizeAttenuation: true,
  }));
  dust.name = 'dust';
  dust.frustumCulled = false;
  scene.add(dust);
  state.dust = DUST_COUNT;

  // ---- robots ----------------------------------------------------------------------------------------
  const followers: { scout?: Follower; responder?: Follower } = {};
  const responderPose = { pos: new THREE.Vector3(), yaw: 0, fresh: false };
  on('responder/pose', data => {
    const p = data as { pos?: number[]; yaw?: number };
    if (!Array.isArray(p?.pos) || p.pos.length < 2) return;
    responderPose.pos.set(p.pos[0], p.pos[1], floorZ(p.pos[2] ?? 0, RESPONDER_ORIGIN_Z));
    responderPose.yaw = typeof p.yaw === 'number' ? p.yaw : responderPose.yaw;
    responderPose.fresh = true;
    state.responderPoses += 1;
  });

  const hidePrimitives = (group: THREE.Group) => {
    for (const c of group.children) if (!(c as THREE.Sprite).isSprite) c.visible = false;
  };

  // Headlight beams as additive cones, not lights: legible, 4500 K, and free in software GL.
  const beamMat = new THREE.MeshBasicMaterial({ color: kelvin(4500), transparent: true, opacity: 0.09,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide });
  const headlight = (parent: THREE.Object3D, x: number, z: number, len: number) => {
    const beam = new THREE.Mesh(new THREE.ConeGeometry(len * 0.32, len, 20, 1, true), beamMat);
    beam.rotation.z = Math.PI / 2;                     // cone tip at the lamp, opening along +X
    beam.position.set(x + len / 2, 0, z);
    beam.name = 'headlight-beam';
    parent.add(beam);
  };

  const loader = new GLTFLoader();
  const loadModel = (file: string) => new Promise<THREE.Object3D>((resolve, reject) =>
    loader.load(`${BASE}${file}`, gltf => resolve(gltf.scene), undefined, reject));

  const fail = (what: string) => (err: unknown) => {
    state.error = `${what}: ${String((err as Error)?.message ?? err)}`;
    console.error(`[look] ${what} failed to load; the console keeps its own primitives`, err);
  };

  const idle = (window as unknown as { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => void })
    .requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 300));
  idle(() => {
    Promise.all([loadModel('blender_scout.glb'), loadModel('blender_responder.glb')]).then(([s, r]) => {
      const scout = upright(s);
      scout.name = 'look-scout';
      headlight(scout, 0.17, 0.085, 0.7);
      const responder = upright(r);
      responder.name = 'look-responder';
      headlight(responder, 0.27, 0.15, 0.9);
      scene.add(scout, responder);
      followers.scout = { model: scout, target: new THREE.Vector3(), yaw: 0, has: false };
      followers.responder = { model: responder, target: new THREE.Vector3(), yaw: 0, has: false };
      state.robotsLoaded = true;
    }).catch(fail('robot models'));
  }, { timeout: 1500 });

  // ---- tower -----------------------------------------------------------------------------------------
  let tower: THREE.Group | undefined;
  let towerWanted = param === 'tower';
  let towerRequested = false;
  const applyTower = () => {
    state.towerVisible = !!tower && towerWanted;
    if (tower) tower.visible = towerWanted;
    lamps.visible = state.towerVisible;
  };
  const loadTower = () => {
    if (towerRequested) return;
    towerRequested = true;
    loadModel('blender_tower.glb').then(root => {
      root.traverse(o => {
        const mesh = o as THREE.Mesh;
        if (/_wall_s$/.test(o.name)) o.visible = false;              // cutaway: basement south walls
        if (!mesh.isMesh) return;
        if (/^level_l[12]_static$/.test(o.name)) {                   // storeys above ground: faint
          const m = (mesh.material as THREE.MeshStandardMaterial).clone();
          m.transparent = true;
          m.opacity = 0.28;
          m.depthWrite = false;
          mesh.material = m;
        }
      });
      tower = upright(root);
      tower.name = 'look-tower';
      for (const [label, z] of [['B1 · illustrative', -0.35], ['B2 · illustrative', -1.35], ['B3 · illustrative', -2.35]] as const) {
        const tag = viewer.createLabelSprite(label, '#e8a43b');
        tag.position.set(-2.45, -1.6, z);
        tag.scale.set(0.6, 0.2, 1);
        tower.add(tag);
      }
      scene.add(tower);
      scene.add(lamps);
      state.towerLoaded = true;
      applyTower();
    }).catch(fail('tower model'));
  };
  state.showTower = (show: boolean) => {
    towerWanted = show;
    if (show) loadTower();
    applyTower();
  };
  on('scene/loaded', data => {
    if (param === 'tower') return;
    // The A1 asset pass (#128) draws its own tower; never draw two.
    const a1 = (window as unknown as { aftershockAssets?: unknown }).aftershockAssets;
    state.showTower((data as { scene?: string })?.scene === 'tower' && !a1);
  });
  if (towerWanted) idle(loadTower, { timeout: 1500 });

  // ---- per frame -------------------------------------------------------------------------------------
  const tmp = new THREE.Vector3();
  const step = (f: Follower | undefined, group: THREE.Group, pos: THREE.Vector3, yaw: number, dt: number) => {
    if (!f) return;
    hidePrimitives(group);
    f.target.copy(pos);
    if (!f.has || f.model.position.distanceTo(f.target) > SNAP_M) {
      f.model.position.copy(f.target);
      f.yaw = yaw;
      f.has = true;
    } else {
      const k = 1 - Math.exp(-dt / EASE_S);
      f.model.position.lerp(f.target, k);
      const d = Math.atan2(Math.sin(yaw - f.yaw), Math.cos(yaw - f.yaw));
      f.yaw += d * k;
    }
    f.model.rotation.z = f.yaw;
  };

  let last = performance.now();
  const frame = (now: number) => {
    const dt = Math.max(0, Math.min(0.5, (now - last) / 1000));
    last = now;
    const sg = internals.scoutGroup;
    tmp.copy(sg.position);
    tmp.z = floorZ(tmp.z, SCOUT_ORIGIN_Z);
    step(followers.scout, sg, tmp, sg.rotation.z, dt);
    const rg = internals.responderGroup;
    if (responderPose.fresh) {
      step(followers.responder, rg, responderPose.pos, responderPose.yaw, dt);
      rg.position.set(responderPose.pos.x, responderPose.pos.y, responderPose.pos.z);   // label rides the real pose
    } else {
      step(followers.responder, rg, rg.position, rg.rotation.z, dt);
    }
    if (!reducedMotion) {
      for (let i = 0; i < DUST_COUNT; i++) {
        dustPos[i * 3] += dustVel[i * 3] * dt;
        dustPos[i * 3 + 1] += dustVel[i * 3 + 1] * dt;
        dustPos[i * 3 + 2] += dustVel[i * 3 + 2] * dt;
        if (dustPos[i * 3 + 2] < -0.05) respawn(i, false);
      }
      dustGeom.attributes.position.needsUpdate = true;
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
  return state;
}
