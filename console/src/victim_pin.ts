// VICTIM-PIN: a pin over each casualty in the 3D map, tall enough to see through the floors above them, saying
// who they are, which floor they are on, and how far the rescue has got with them.
//
// - VictimPins (pure: no DOM, no three.js, no bus import) keeps one pin per casualty id from the bus:
//   map/casualties {id, pos, confidence} places and updates it; a pin stays when a later list drops its id,
//   at its last known place. Its floor is the one its height is on: from 0.05 m below a floor to 0.2 m above
//   it (a casualty lies on a floor; perception's z is mostly the Scout's own, 0.075 m up, and a scene body
//   centre is 0.12 m up). Any other height names no floor ("floor not clear yet"): in a real levels run 276 of
//   1242 estimates (22%) are taken while the Scout is on a ramp and sit between floors, and calling the
//   nearest floor there would be a guess.
//   Its state only moves forward: located -> talking (casualty/contact "talking") -> spoken ("done",
//   "unresponsive" or "stopped" ends the talk) -> reached, once responder/pose says "arrived" within REACH_M
//   of them on their floor (the real delivery to c1 ends 0.44 m beside them). The Scout coming near does not
//   count: perception's first estimate of a casualty is often right beside the Scout itself (in a real levels
//   run the Scout stops within REACH_M of c1's pin 1.1 s after it appears, and of c2's after 0.2 s), so that
//   would mark nearly every pin reached the moment it appears.
// - Ids and places are perception's (perception/casualties.py tracks), shown as they are: in the levels
//   scene a track can move floor as the Scout descends, and its pin moves with it.
// - Floors are the levels scene's (sim/scenes/make_levels.py, H = 0.6 m): L1 +0.6, ground 0, B1 -0.6,
//   B2 -1.2, B3 -1.8. Outside the levels scene a pin names no floor, since other scenes have other heights.
// - setupVictimPins(viewer, on) draws the pins in the map (a stem from the casualty up to a card) and keeps
//   them current; the map's own casualty sphere and label stay as they are. Not wired into main.ts:
//     import { on } from './bus';
//     setupVictimPins(mapViewer, on);

import * as THREE from 'three';
import type { MapViewer } from './map';

export const LEVEL_Z: { id: string; z: number }[] = [
  { id: 'L1', z: 0.6 }, { id: 'ground', z: 0 }, { id: 'B1', z: -0.6 }, { id: 'B2', z: -1.2 }, { id: 'B3', z: -1.8 },
];
export const REACH_M = 0.6;                        // xy metres: a robot stopped this close has reached them
export const RESPONDER_ORIGIN_Z = 0.05;           // the Responder's origin above its floor

export type PinState = 'located' | 'talking' | 'spoken' | 'reached';
export const PIN_ORDER: PinState[] = ['located', 'talking', 'spoken', 'reached'];

export type VictimPin = {
  id: string;
  pos: [number, number, number];
  floor: string | null;           // levels scene only; null there when the height is between floors
  levels: boolean;                // placed in the levels scene
  confidence: number | null;
  state: PinState;
  t: number | null;                   // sim time of the last state change, when the message carried one
};

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const vec3 = (v: unknown): [number, number, number] | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(n => typeof n === 'number' && Number.isFinite(n))
    ? [v[0], v[1], v[2]] as [number, number, number] : null;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export const STOREY_M = 0.6;
export const FLOOR_BELOW_M = 0.05;
export const FLOOR_ABOVE_M = 0.2;

/** The levels-scene floor a casualty at height z is on, or null when z is between floors. */
export function floorOn(z: number): string | null {
  return LEVEL_Z.find(l => z >= l.z - FLOOR_BELOW_M && z <= l.z + FLOOR_ABOVE_M)?.id ?? null;
}

const floorName = (f: string | null) => (f === 'ground' ? 'Ground' : f);

export class VictimPins {
  scene: string | null = null;
  pins = new Map<string, VictimPin>();
  onChange: (() => void) | null = null;

  list(): VictimPin[] { return [...this.pins.values()].sort((a, b) => a.id.localeCompare(b.id)); }

  /** Feed one bus message. Returns true if any pin changed. */
  apply(topic: string, data: unknown): boolean {
    const before = this.key();
    if (topic === 'scene/loaded' && isRec(data) && typeof data.scene === 'string') {
      if (data.scene !== this.scene) this.pins.clear();
      this.scene = data.scene;
      for (const p of this.pins.values()) { p.floor = this.floorOf(p.pos); p.levels = this.scene === 'levels'; }
    } else if (topic === 'console/replay' && isRec(data) && typeof data.scene === 'string') {
      this.scene = data.scene;
      for (const p of this.pins.values()) { p.floor = this.floorOf(p.pos); p.levels = this.scene === 'levels'; }
    } else if (topic === 'map/casualties' && Array.isArray(data)) {
      for (const c of data.filter(isRec)) {
        const pos = vec3(c.pos);
        if (typeof c.id !== 'string' || !c.id || !pos) continue;
        const p = this.pins.get(c.id);
        if (p) {
          p.pos = pos;
          p.floor = this.floorOf(pos);
          p.levels = this.scene === 'levels';
          p.confidence = num(c.confidence) ?? p.confidence;
        } else {
          this.pins.set(c.id, { id: c.id, pos, floor: this.floorOf(pos), levels: this.scene === 'levels',
                                confidence: num(c.confidence),
                                state: 'located', t: null });
        }
      }
    } else if (topic === 'casualty/contact' && isRec(data) && typeof data.id === 'string') {
      const p = this.pins.get(data.id);
      if (p) this.advance(p, data.status === 'talking' ? 'talking' : 'spoken', num(data.t));
    } else if (topic === 'responder/pose' && isRec(data)) {
      const pos = vec3(data.pos);
      if (!pos || data.state !== 'arrived') return false;
      this.arrived(pos, num(data.t));
    } else {
      return false;
    }
    const changed = before !== this.key();
    if (changed) this.onChange?.();
    return changed;
  }

  private floorOf(pos: [number, number, number]): string | null {
    return this.scene === 'levels' ? floorOn(pos[2]) : null;
  }

  private advance(p: VictimPin, s: PinState, t: number | null): void {
    if (PIN_ORDER.indexOf(s) <= PIN_ORDER.indexOf(p.state)) return;
    p.state = s;
    p.t = t;
  }

  private arrived(pos: [number, number, number], t: number | null): void {
    const floorZ = pos[2] - RESPONDER_ORIGIN_Z;
    for (const p of this.pins.values()) {
      if (p.state === 'reached') continue;
      // same floor: in the levels scene, the robot's floor (within 3 cm: not on a ramp) is the pin's floor
      const robotFloor = LEVEL_Z.find(l => Math.abs(floorZ - l.z) <= 0.03)?.id ?? null;
      const sameFloor = this.scene === 'levels' ? robotFloor !== null && robotFloor === p.floor
                                                : Math.abs(pos[2] - p.pos[2]) < STOREY_M / 2;
      if (sameFloor && Math.hypot(pos[0] - p.pos[0], pos[1] - p.pos[1]) <= REACH_M) {
        p.state = 'reached';
        p.t = t;
      }
    }
  }

  private key(): string {
    return this.list().map(p => `${p.id}:${p.pos.map(v => v.toFixed(2))}:${p.floor}:${p.state}:${p.confidence?.toFixed(2)}`).join('|');
  }
}

/** One plain line for a pin: "c2 on B2: reached by the Responder", "c1: located, 82% sure". */
export function describePin(p: VictimPin): string {
  const where = p.floor ? ` on ${floorName(p.floor)}` : p.levels ? ', floor not clear yet' : '';
  switch (p.state) {
    case 'located': return `${p.id}${where}: located` + (p.confidence !== null ? `, ${Math.round(p.confidence * 100)}% sure` : '');
    case 'talking': return `${p.id}${where}: talking to them`;
    case 'spoken': return `${p.id}${where}: spoken to`;
    case 'reached': return `${p.id}${where}: reached by the Responder`;
  }
}

// ---- drawing -------------------------------------------------------------------------------------------

export const PIN_COLOUR: Record<PinState, string> = {
  located: '#f472b6',             // the map's own casualty pink
  talking: '#fbbf24',
  spoken: '#fbbf24',
  reached: '#34d399',
};
const STATE_WORD: Record<PinState, string> = { located: 'Located', talking: 'Talking', spoken: 'Spoken to', reached: 'Reached' };
export const PIN_HEIGHT_M = 0.62;  // card above the casualty: clear of the map's own label (0.42 above the floor)

/** A pin card: id and floor in bold, the state underneath, edged in the state's colour. */
export function pinSprite(p: VictimPin): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  const colour = PIN_COLOUR[p.state];
  ctx.fillStyle = 'rgba(15, 23, 42, 0.92)';
  ctx.beginPath();
  ctx.roundRect(6, 6, 244, 100, 18);
  ctx.fill();
  ctx.strokeStyle = colour;
  ctx.lineWidth = 5;
  ctx.stroke();
  ctx.fillStyle = colour;                     // the pin's point, under the card
  ctx.beginPath();
  ctx.moveTo(112, 106);
  ctx.lineTo(128, 124);
  ctx.lineTo(144, 106);
  ctx.closePath();
  ctx.fill();
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#e8f0fa';
  ctx.font = 'bold 40px Inter, system-ui, sans-serif';
  ctx.fillText(p.floor ? `${p.id} · ${floorName(p.floor)}` : p.levels ? `${p.id} · ?` : p.id, 128, 40);
  ctx.fillStyle = colour;
  ctx.font = '600 28px Inter, system-ui, sans-serif';
  const sure = p.state === 'located' && p.confidence !== null ? ` ${Math.round(p.confidence * 100)}%` : '';
  ctx.fillText(STATE_WORD[p.state] + sure, 128, 80);
  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(0.36, 0.18, 1);
  sprite.center.set(0.5, 0.03);               // anchored at the point, so the card sits on top of the stem
  sprite.renderOrder = 11;
  sprite.userData.label = describePin(p);    // read by browser tests, like the map's own labels
  return sprite;
}

/** Add the pins to the map and keep them current. Returns the model. */
export function setupVictimPins(viewer: MapViewer, on: (topic: string, handler: (data: unknown) => void) => unknown,
                                pins = new VictimPins()): VictimPins {
  const group = new THREE.Group();
  group.name = 'victim-pins';
  viewer.scene.add(group);
  const drawn = new Map<string, { obj: THREE.Group; label: string; at: string }>();
  const dispose = (g: THREE.Group) => g.traverse(o => {
    const m = o as THREE.Mesh | THREE.Sprite;
    if (m.geometry && !(o as THREE.Sprite).isSprite) m.geometry.dispose();
    const mat = m.material as THREE.Material & { map?: THREE.Texture | null };
    mat?.map?.dispose();
    mat?.dispose?.();
  });
  const draw = () => {
    for (const p of pins.list()) {
      const label = describePin(p);
      const at = p.pos.map(v => v.toFixed(3)).join(',');
      const cur = drawn.get(p.id);
      if (cur && cur.label === label && cur.at === at) continue;
      if (cur) { group.remove(cur.obj); dispose(cur.obj); }
      const g = new THREE.Group();
      g.name = `victim-pin-${p.id}`;
      g.position.set(p.pos[0], p.pos[1], p.pos[2]);
      const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, PIN_HEIGHT_M, 8),
        new THREE.MeshBasicMaterial({ color: PIN_COLOUR[p.state], depthTest: false, transparent: true, opacity: 0.85 }));
      stem.rotation.x = Math.PI / 2;            // cylinders stand on y; the map is z-up
      stem.position.z = PIN_HEIGHT_M / 2;
      stem.renderOrder = 11;
      g.add(stem);
      const card = pinSprite(p);
      card.position.z = PIN_HEIGHT_M;
      g.add(card);
      group.add(g);
      drawn.set(p.id, { obj: g, label, at });
    }
    for (const [id, d] of drawn) {
      if (!pins.pins.has(id)) { group.remove(d.obj); dispose(d.obj); drawn.delete(id); }
    }
  };
  const prev = pins.onChange;
  pins.onChange = () => { prev?.(); draw(); };
  for (const topic of ['scene/loaded', 'console/replay', 'map/casualties', 'casualty/contact', 'responder/pose']) {
    on(topic, data => { pins.apply(topic, data); });
  }
  draw();
  return pins;
}
