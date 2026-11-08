// FLOOR-BADGE: a small floor badge ("B2", "Ground", "Ramp") over each robot in the 3D map, so it is plain which
// floor the Scout and the Responder are on as they go down through the basements.
//
// - FloorBadges (pure: no DOM, no three.js, no bus import) works out each robot's floor from its real pose:
//   sensors/scout {pose.pos} (body origin 0.075 m above the floor) and responder/pose {pos} (0.05 m). Floor
//   heights are the levels scene's (sim/scenes/make_levels.py, H = 0.6 m): L1 +0.6, ground 0, B1 -0.6,
//   B2 -1.2, B3 -1.8; within 0.03 m of a floor the robot is on it, otherwise on a ramp.
// - Badges show only in the levels scene (scene/loaded, or a replay's console/replay status with scene
//   "levels"): other scenes have other floor heights, so a badge there would be a guess. No pose, no badge.
// - setupFloorBadges(viewer, on) adds the badges to the map's robot groups (beside their name labels) and
//   keeps them current. Not wired into main.ts (console owner's call):
//     import { on } from './bus';
//     setupFloorBadges(mapViewer, on);

import * as THREE from 'three';
import type { MapViewer } from './map';

export const LEVEL_Z: { id: string; z: number }[] = [
  { id: 'L1', z: 0.6 }, { id: 'ground', z: 0 }, { id: 'B1', z: -0.6 }, { id: 'B2', z: -1.2 }, { id: 'B3', z: -1.8 },
];
export const TOL_M = 0.03;
export const ORIGIN_Z = { scout: 0.075, responder: 0.05 } as const;
export type Robot = 'scout' | 'responder';

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const posZ = (v: unknown): number | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(n => typeof n === 'number' && Number.isFinite(n)) ? v[2] as number : null;

/** Badge text for a floor-level height: "L1", "Ground", "B1".."B3", or "Ramp" between floors. */
export function floorBadge(z: number): string {
  const f = LEVEL_Z.find(l => Math.abs(z - l.z) <= TOL_M);
  if (f) return f.id === 'ground' ? 'Ground' : f.id;
  if (z > LEVEL_Z[0].z) return 'L1';
  if (z < LEVEL_Z[LEVEL_Z.length - 1].z) return 'B3';
  return 'Ramp';
}

export class FloorBadges {
  scene: string | null = null;
  floor: Record<Robot, string | null> = { scout: null, responder: null };
  onChange: (() => void) | null = null;

  get visible(): boolean { return this.scene === 'levels'; }

  /** The badge to draw for a robot, or null (not the levels scene, or no pose yet). */
  badge(robot: Robot): string | null { return this.visible ? this.floor[robot] : null; }

  /** Feed one bus message. Returns true if a badge changed. */
  apply(topic: string, data: unknown): boolean {
    if (!isRec(data)) return false;
    const before = `${this.badge('scout')}|${this.badge('responder')}`;
    if (topic === 'scene/loaded' && typeof data.scene === 'string') {
      this.scene = data.scene;
      this.floor = { scout: null, responder: null };
    } else if (topic === 'console/replay' && typeof data.scene === 'string') {
      this.scene = data.scene;
    } else if (topic === 'sensors/scout') {
      const z = isRec(data.pose) ? posZ(data.pose.pos) : null;
      if (z === null) return false;
      this.floor.scout = floorBadge(z - ORIGIN_Z.scout);
    } else if (topic === 'responder/pose') {
      const z = posZ(data.pos);
      if (z === null) return false;
      this.floor.responder = floorBadge(z - ORIGIN_Z.responder);
    } else {
      return false;
    }
    const changed = before !== `${this.badge('scout')}|${this.badge('responder')}`;
    if (changed) this.onChange?.();
    return changed;
  }
}

// ---- drawing -------------------------------------------------------------------------------------------

const COLOUR: Record<Robot, string> = { scout: '#38bdf8', responder: '#fbbf24' };   // the map's own label colours
const ABOVE_LABEL: Record<Robot, number> = { scout: 0.36, responder: 0.42 };        // labels sit at 0.22 / 0.28

/** A compact badge sprite: the floor in bold, on the console's dark pill, edged in the robot's colour. */
export function badgeSprite(text: string, colour: string): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 192;
  canvas.height = 96;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = 'rgba(15, 23, 42, 0.92)';
  ctx.beginPath();
  ctx.roundRect(6, 6, 180, 84, 42);
  ctx.fill();
  ctx.strokeStyle = colour;
  ctx.lineWidth = 5;
  ctx.stroke();
  ctx.fillStyle = '#e8f0fa';
  ctx.font = `bold ${text.length > 3 ? 36 : 44}px Inter, system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 96, 50);
  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(0.26, 0.13, 1);
  sprite.renderOrder = 10;
  sprite.userData.label = text;            // read by browser tests, like the map's own labels
  return sprite;
}

/** Add floor badges to the map's robot groups and keep them current. Returns the model. */
export function setupFloorBadges(viewer: MapViewer, on: (topic: string, handler: (data: unknown) => void) => unknown,
                                 badges = new FloorBadges()): FloorBadges {
  const groups = viewer as unknown as { scoutGroup: THREE.Group; responderGroup: THREE.Group };
  const shown: Record<Robot, THREE.Sprite | null> = { scout: null, responder: null };
  const draw = () => {
    for (const robot of ['scout', 'responder'] as Robot[]) {
      const text = badges.badge(robot);
      const cur = shown[robot];
      if (cur && cur.userData.label === text) continue;
      const group = robot === 'scout' ? groups.scoutGroup : groups.responderGroup;
      if (cur) {
        group.remove(cur);
        (cur.material as THREE.SpriteMaterial).map?.dispose();
        cur.material.dispose();
        shown[robot] = null;
      }
      if (!text) continue;
      const sprite = badgeSprite(text, COLOUR[robot]);
      sprite.name = `floor-badge-${robot}`;
      sprite.position.set(0, 0, ABOVE_LABEL[robot]);
      group.add(sprite);
      shown[robot] = sprite;
    }
  };
  const prev = badges.onChange;
  badges.onChange = () => { prev?.(); draw(); };
  for (const topic of ['scene/loaded', 'console/replay', 'sensors/scout', 'responder/pose']) {
    on(topic, data => { badges.apply(topic, data); });
  }
  draw();
  return badges;
}
