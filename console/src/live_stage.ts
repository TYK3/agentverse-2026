// CONSOLE-LIVE-STAGE: the rescue stage right now, from the live bus (or a run replayed onto it), in the same
// stages and labels as CONSOLE-STAGE (#275, rescue_stage.ts, which reads a finished run log). Standalone on
// main: the stage type and labels below match rescue_stage.ts's, so its renderRescueStage() draws these too.
//
// Live there is no run log, so each stage comes from a message the console already gets (coord/CONTRACT.md):
//   scene/loaded                   starts over (start)
//   sensors/scout {pose.pos}       the Scout's floor, from its height in the levels scene (L1 +0.6, ground 0,
//                                  B1 -0.6, B2 -1.2, B3 -1.8; within 0.03 m of a floor, else a ramp; the body
//                                  origin is 0.075 m up): descend while above the target floor, else search
//   map/casualties [{id, pos}]     the target: the first casualty not yet reached, on the floor at or below its pos
//   world/change (aftershock, block_added)   shift, on the Scout's floor
//   log/decision stop_and_recheck, or the first Scout route/proposed after the shift   recheck
//   the next Scout pose that moved (>= 0.01 m) after that   back to search (or descend)
//   casualty/contact {id, status: talking | done}   reached that casualty (the Scout is with them)
//   console/replay_b2 | console/replay_b3 {reached, passed, total}   reached (if reached) then done, n of m
//   report/handover               done
// Nothing is guessed: with no casualty known yet the target is the floor the Scout is on, a casualty is reached
// only when the bus says so (never from distance), and sim time is the message's t (else the last one seen).
//
// LiveStage is pure (no DOM, no bus import): apply(topic, data) and read `current` / `history` (each with a
// plain `label`). attachLiveStage(on) subscribes it with bus.ts's on(). Not wired into main.ts:
//   import { on } from './bus';
//   const live = attachLiveStage(on);
//   live.onChange = s => { stageEl.textContent = s.label; };   // or renderRescueStage(el, s) from #275

export type StageId = 'start' | 'descend' | 'search' | 'shift' | 'recheck' | 'reached' | 'done';
export type RescueStage = {
  t: number;
  stage: StageId;
  floor: string | null;           // the floor (or 'ramp') the Scout is on
  target: string | null;          // the floor of the casualty being sought
  casualty: string | null;        // its id, when known
  label: string;
  ok?: boolean;                   // done: every check passed
};

const fmtFloor = (f: string | null) => (f === 'ground' ? 'the ground floor' : f === 'ramp' ? 'a ramp' : f ?? 'an unknown floor');

/** The stage as one plain line (the same wording as rescue_stage.ts). */
export function stageLabel(s: Omit<RescueStage, 'label'>, passed?: number, total?: number): string {
  const who = s.casualty ?? 'the casualty';
  switch (s.stage) {
    case 'start': return 'Waiting for the run to start';
    case 'descend': return `Descending: on ${fmtFloor(s.floor)}, heading for ${fmtFloor(s.target)}`;
    case 'search': return `Searching ${fmtFloor(s.target)} for ${who}`;
    case 'shift': return `Slab shifted on ${fmtFloor(s.floor)}: Scout stopping`;
    case 'recheck': return `Re-planning around the slab on ${fmtFloor(s.floor)}`;
    case 'reached': return `Reached ${who} on ${fmtFloor(s.target)}`;
    case 'done': return total ? `Run over: ${passed} of ${total} checks passed` : 'Run over: no checks in the log';
  }
}

export const LEVEL_Z: { id: string; z: number }[] = [
  { id: 'L1', z: 0.6 }, { id: 'ground', z: 0 }, { id: 'B1', z: -0.6 }, { id: 'B2', z: -1.2 }, { id: 'B3', z: -1.8 },
];
const TOL_M = 0.03;
const SCOUT_ORIGIN_Z = 0.075;
const MIN_MOVE_M = 0.01;

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const vec = (v: unknown): number[] | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(x => num(x) !== null) ? (v as number[]).slice(0, 3) : null;

/** The floor at a floor-level height, or 'ramp' between floors. */
export function floorAt(z: number): string {
  const f = LEVEL_Z.find(l => Math.abs(z - l.z) <= TOL_M);
  if (f) return f.id;
  if (z > LEVEL_Z[0].z) return LEVEL_Z[0].id;
  if (z < LEVEL_Z[LEVEL_Z.length - 1].z) return LEVEL_Z[LEVEL_Z.length - 1].id;
  return 'ramp';
}
/** The floor something stands on: the highest floor at or below its height (a casualty's pos is its centre). */
export function floorBelow(z: number): string {
  return (LEVEL_Z.find(l => l.z <= z + TOL_M) ?? LEVEL_Z[LEVEL_Z.length - 1]).id;
}
const rank = (f: string | null) => LEVEL_Z.findIndex(l => l.id === f);

export class LiveStage {
  current: RescueStage;
  history: RescueStage[] = [];
  onChange: ((s: RescueStage) => void) | null = null;
  private t = 0;
  private floor: string | null = null;
  private lastPos: number[] | null = null;
  private casualties: { id: string; floor: string }[] = [];
  private reached = new Set<string>();
  private shiftAt: number | null = null;

  constructor() { this.current = this.make('start'); this.history.push(this.current); }

  private target(): { floor: string | null; id: string | null } {
    const c = this.casualties.find(x => !this.reached.has(x.id));
    return c ? { floor: c.floor, id: c.id } : { floor: this.floor === 'ramp' ? null : this.floor, id: null };
  }

  private make(stage: StageId, extra: { casualty?: string | null; target?: string | null; ok?: boolean; passed?: number; total?: number } = {}): RescueStage {
    const tg = this.target();
    const s = { t: this.t, stage, floor: this.floor, target: extra.target !== undefined ? extra.target : tg.floor,
                casualty: extra.casualty !== undefined ? extra.casualty : tg.id };
    return { ...s, label: stageLabel(s, extra.passed, extra.total), ...(extra.ok !== undefined ? { ok: extra.ok } : {}) };
  }

  private go(stage: StageId, extra: Parameters<LiveStage['make']>[1] = {}): RescueStage | null {
    const s = this.make(stage, extra);
    const c = this.current;
    if (c.stage === s.stage && c.floor === s.floor && c.target === s.target && c.casualty === s.casualty && c.label === s.label) return null;
    this.current = s;
    this.history.push(s);
    this.onChange?.(s);
    return s;
  }

  /** Descend while above the target floor (or on a ramp with no target yet), else search. */
  private travel(): RescueStage | null {
    const tg = this.target().floor;
    const above = tg ? rank(this.floor) < rank(tg) || this.floor === 'ramp' : this.floor === 'ramp';
    if (above && !tg) {
      const below = LEVEL_Z.find((l, i) => i > 0 && this.lastPos && l.z < this.lastPos[2] - SCOUT_ORIGIN_Z)?.id ?? null;
      return this.go('descend', { target: below });
    }
    return this.go(above ? 'descend' : 'search');
  }

  /** Feed one bus message. Returns the new stage if it changed. */
  apply(topic: string, data: unknown): RescueStage | null {
    if (topic === 'map/casualties' && Array.isArray(data)) {
      for (const c of data) {
        const p = isRec(c) ? vec(c.pos) : null;
        if (!p || typeof c.id !== 'string' || this.casualties.some(x => x.id === c.id)) continue;
        this.casualties.push({ id: c.id, floor: floorBelow(p[2]) });
      }
      return ['descend', 'search'].includes(this.current.stage) ? this.travel() : null;
    }
    if (!isRec(data)) return null;
    const t = num(data.t);
    if (t !== null) this.t = t;
    switch (topic) {
      case 'scene/loaded': {
        const fresh = new LiveStage();
        Object.assign(this, { ...fresh, onChange: this.onChange, history: this.history });
        this.t = 0;
        return this.go('start');
      }
      case 'sensors/scout': {
        const p = isRec(data.pose) ? vec(data.pose.pos) : null;
        if (!p) return null;
        const moved = this.lastPos ? Math.hypot(p[0] - this.lastPos[0], p[1] - this.lastPos[1], p[2] - this.lastPos[2]) : 0;
        this.lastPos = p;
        this.floor = floorAt(p[2] - SCOUT_ORIGIN_Z);
        const st = this.current.stage;
        if (st === 'shift') return this.go('shift');                          // stopped: only the floor may update
        if (st === 'recheck') return moved >= MIN_MOVE_M ? this.travel() : null;
        if (st === 'reached' && moved < MIN_MOVE_M) return null;
        if (st === 'done') return null;
        return this.travel();
      }
      case 'world/change':
        if (data.kind !== 'aftershock' && data.kind !== 'block_added') return null;
        this.shiftAt = this.t;
        return this.go('shift');
      case 'log/decision':
        if (data.outcome === 'stop_and_recheck' && this.current.stage === 'shift') return this.go('recheck');
        return null;
      case 'route/proposed':
        if (data.robot === 'scout' && this.current.stage === 'shift' && this.shiftAt !== null) return this.go('recheck');
        return null;
      case 'casualty/contact': {
        if (typeof data.id !== 'string' || (data.status !== 'talking' && data.status !== 'done') || this.reached.has(data.id)) return null;
        const c = this.casualties.find(x => x.id === data.id);
        const s = this.go('reached', { casualty: data.id, target: c?.floor ?? this.floor });
        this.reached.add(data.id);
        return s;
      }
      case 'console/replay_b2':
      case 'console/replay_b3': {
        // the result carries no t: its checks' own latest time is when the run ended
        const stepT = Array.isArray(data.steps) ? data.steps.map(x => (isRec(x) ? num(x.t) : null)).filter((x): x is number => x !== null) : [];
        if (stepT.length) this.t = Math.max(this.t, ...stepT);
        if (data.reached === true && this.current.stage !== 'reached') this.go('reached', { casualty: null, target: this.floor });
        const total = num(data.total) ?? 0, passed = num(data.passed) ?? 0;
        return this.go('done', { ok: total > 0 && passed === total, passed, total, casualty: null, target: this.floor });
      }
      case 'report/handover':
        return this.go('done', { casualty: null, target: this.floor });
      default:
        return null;
    }
  }
}

/** Subscribe a LiveStage to the console bus, given its on() (bus.ts). */
export function attachLiveStage(on: (topic: string, handler: (data: unknown) => void) => unknown,
                                live = new LiveStage()): LiveStage {
  for (const topic of ['scene/loaded', 'sensors/scout', 'map/casualties', 'world/change', 'log/decision', 'route/proposed',
                       'casualty/contact', 'console/replay_b2', 'console/replay_b3', 'report/handover']) {
    on(topic, data => { live.apply(topic, data); });
  }
  return live;
}
