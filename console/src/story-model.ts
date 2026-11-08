// Story mode model (ref DEMO-FLOW): which phases of the rescue the bus events have reached.
// Pure (no DOM, no bus), so the console tests drive it directly; story.ts draws it.

export type Vec3 = [number, number, number];
export type PhaseId = 'quake' | 'search' | 'found' | 'talk' | 'descend' | 'approve' | 'deliver' | 'shift'
  | 'recheck' | 'report';
export type PhaseState = 'pending' | 'active' | 'waiting' | 'held' | 'done';

export const PHASES: { id: PhaseId; label: string }[] = [
  { id: 'quake', label: 'Quake' },
  { id: 'search', label: 'Scout search' },
  { id: 'found', label: 'Casualty found' },
  { id: 'talk', label: 'Talk' },
  { id: 'descend', label: 'Descend B1' },
  { id: 'approve', label: 'Approve' },
  { id: 'deliver', label: 'Deliver' },
  { id: 'shift', label: 'Slab shift' },
  { id: 'recheck', label: 'Stop + recheck' },
  { id: 'report', label: 'Report' },
];

export const BELOW_GROUND_Z = -0.5;
const SIM_TIMED = new Set(['sensors/scout', 'responder/pose', 'world/change']);
const isRun = (topic: string) => topic.startsWith('run/');      // tools/run_b2.py records, all in sim seconds     // a robot below this is in the basement (B1 and down)

export type Phase = { state: PhaseState; t: number | null; note: string };
export type StoryFacts = {
  scene: string | null;
  casualties: Record<string, { pos: Vec3; confidence: number }>;
  replies: number;
  delivered: string[];
  approvals: { asked: number; approved: number; held: number };
  shifts: number;
  stops: number;
  rechecks: number;
  deepestZ: number;
  reportMarkdown: string | null;
};

type Rec = Record<string, unknown>;
const isRec = (v: unknown): v is Rec => typeof v === 'object' && v !== null && !Array.isArray(v);
const vec3 = (v: unknown): Vec3 | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every(n => typeof n === 'number') ? [v[0], v[1], v[2]] as Vec3 : null;
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

export class StoryModel {
  phases = new Map<PhaseId, Phase>(PHASES.map(p => [p.id, { state: 'pending', t: null, note: '' }]));
  current: PhaseId | null = null;
  focus: Vec3 | null = null;
  t = 0;
  facts: StoryFacts = {
    scene: null, casualties: {}, replies: 0, delivered: [], approvals: { asked: 0, approved: 0, held: 0 },
    shifts: 0, stops: 0, rechecks: 0, deepestZ: 0, reportMarkdown: null,
  };
  private scout: Vec3 | null = null;
  private responder: Vec3 | null = null;
  private revoked = new Set<string>();

  phase(id: PhaseId): Phase { return this.phases.get(id)!; }
  lit(): PhaseId[] { return PHASES.filter(p => this.phase(p.id).state !== 'pending').map(p => p.id); }

  private set(id: PhaseId, state: PhaseState, note: string, focus?: Vec3 | null): PhaseId {
    const p = this.phase(id);
    if (p.state === 'done' && state !== 'done' && id !== 'recheck' && id !== 'approve') return id;
    p.state = state;
    if (p.t === null || state === 'done') p.t = this.t;
    p.note = note;
    this.current = id;
    if (focus) this.focus = focus;
    return id;
  }

  private pose(pos: Vec3 | null, who: 'scout' | 'responder'): PhaseId | null {
    if (!pos) return null;
    if (who === 'scout') this.scout = pos; else this.responder = pos;
    this.facts.deepestZ = Math.min(this.facts.deepestZ, pos[2]);
    if (pos[2] < BELOW_GROUND_Z && this.phase('descend').state !== 'done') {
      return this.set('descend', 'done', `${who === 'scout' ? 'Scout' : 'Responder'} below ground, z ${pos[2].toFixed(1)} m`, pos);
    }
    return null;
  }

  /** Feed one bus message. Returns the phase it moved, or null. */
  /** Sim time, from a replay's recorded t (setTime) or, live, from the topics stamped in sim seconds. */
  setTime(t: number): void { if (Number.isFinite(t)) this.t = Math.max(this.t, t); }

  apply(topic: string, data: unknown): PhaseId | null {
    // Some lanes stamp payloads with their own clocks; only these carry sim time.
    if ((SIM_TIMED.has(topic) || isRun(topic)) && isRec(data) && num(data.t) !== null) this.setTime(num(data.t)!);
    if (isRun(topic)) return this.applyRun(topic.slice(4), isRec(data) ? data : {});
    switch (topic) {
      case 'scene/loaded': {
        if (!isRec(data)) return null;
        this.facts.scene = typeof data.scene === 'string' ? data.scene : null;
        const blocks = Array.isArray(data.blocks) ? data.blocks.filter(isRec) : [];
        const c = blocks.reduce<Vec3>((a, b) => { const p = vec3(b.pos) ?? [0, 0, 0]; return [a[0] + p[0], a[1] + p[1], a[2] + p[2]]; }, [0, 0, 0]);
        const n = Math.max(1, blocks.length);
        return this.set('quake', 'done', `${this.facts.scene ?? 'scene'}: ${blocks.length} pieces after the quake`,
                        [c[0] / n, c[1] / n, 0]);
      }
      case 'scout/goto': {
        const target = isRec(data) ? vec3(data.target) : null;
        const s = this.phase('search').state;
        return this.set('search', s === 'done' ? 'done' : 'active',
                        isRec(data) && typeof data.reason === 'string' ? data.reason : 'Scout exploring', target ?? this.scout);
      }
      case 'sensors/scout':
        return this.pose(isRec(data) && isRec(data.pose) ? vec3(data.pose.pos) : null, 'scout');
      case 'sim/truth': {
        if (!isRec(data)) return null;
        const a = this.pose(isRec(data.scout) ? vec3(data.scout.pos) : null, 'scout');
        const b = this.pose(isRec(data.responder) ? vec3(data.responder.pos) : null, 'responder');
        return a ?? b;
      }
      case 'responder/pose':
        return this.pose(isRec(data) ? vec3(data.pos) : null, 'responder');
      case 'map/casualties': {
        if (!Array.isArray(data) || !data.length) return null;
        for (const c of data.filter(isRec)) {
          const pos = vec3(c.pos);
          if (typeof c.id === 'string' && pos) this.facts.casualties[c.id] = { pos, confidence: num(c.confidence) ?? 0 };
        }
        const first = data.filter(isRec)[0];
        if (this.phase('search').state !== 'pending') this.phase('search').state = 'done';
        return this.set('found', 'done', `${data.length} casualt${data.length === 1 ? 'y' : 'ies'} located` +
          (first && num(first.confidence) !== null ? `, ${first.id} at ${Math.round(num(first.confidence)! * 100)}%` : ''),
          first ? vec3(first.pos) : null);
      }
      case 'say':
        if (!isRec(data) || data.to !== 'casualty') return null;
        return this.set('talk', this.phase('talk').state === 'done' ? 'done' : 'active', `"${String(data.text ?? '').slice(0, 80)}"`,
                        this.casualtyFocus());
      case 'casualty/reply':
        if (!isRec(data)) return null;
        this.facts.replies += 1;
        return this.set('talk', 'done', `${data.id}: "${String(data.text ?? '').slice(0, 80)}"`, this.casualtyFocus(data.id));
      case 'casualty/contact':
        if (!isRec(data)) return null;
        return this.set('talk', data.status === 'talking' ? 'active' : 'done', `${data.id}: ${data.status}, ${data.turns} turns`,
                        this.casualtyFocus(data.id));
      case 'gate/request':
        if (!isRec(data)) return null;
        this.facts.approvals.asked += 1;
        return this.set('approve', 'waiting', `waiting for the operator: ${String(data.summary ?? data.kind ?? '')}`,
                        this.responder);
      case 'gate/answer':
        if (!isRec(data)) return null;
        if (data.approved === true) {
          this.facts.approvals.approved += 1;
          return this.set('approve', 'done', 'operator approved', this.responder);
        }
        this.facts.approvals.held += 1;
        return this.set('approve', 'held', 'operator said hold: the Responder waits', this.responder);
      case 'responder/action':
        if (!isRec(data) || data.action !== 'place_supply') return null;
        return this.set('deliver', this.phase('deliver').state === 'done' ? 'done' : 'active', `placing ${data.item}`, this.responder);
      case 'log/decision': {
        if (!isRec(data)) return null;
        const reason = `${data.reason ?? ''} ${data.perception ?? ''}`;
        const placed = /placed (\w+)/i.exec(reason);
        if (data.outcome === 'done' && placed) {
          this.facts.delivered.push(placed[1]);
          return this.set('deliver', 'done', `${placed[1]} delivered`, this.responder);
        }
        if (data.outcome === 'frozen' && this.phase('shift').state === 'done') {
          this.facts.stops += 1;
          return this.set('recheck', 'held', 'Responder stopped: the ground moved', this.responder);
        }
        return null;
      }
      case 'world/change': {
        if (!isRec(data)) return null;
        this.facts.shifts += 1;
        const moved = Array.isArray(data.moved_blocks) ? data.moved_blocks.join(', ') : '';
        return this.set('shift', 'done', `${data.kind}: ${moved || 'the scene changed'}`, this.responder ?? this.scout);
      }
      case 'permit/route': {
        if (!isRec(data) || typeof data.route !== 'string') return null;
        if (data.granted === false) {
          this.revoked.add(data.route);
          this.facts.stops += 1;
          return this.set('recheck', 'held', `stop: ${String(data.reason ?? 'move permit revoked')}`, this.responder);
        }
        if (this.revoked.delete(data.route)) {
          this.facts.rechecks += 1;
          return this.set('recheck', 'done', `rechecked: ${String(data.reason ?? 'route seen free again')}`, this.responder);
        }
        return null;
      }
      case 'report/handover':
        if (!isRec(data)) return null;
        this.facts.reportMarkdown = typeof data.markdown === 'string' ? data.markdown : null;
        return this.set('report', 'done', 'handover report ready', null);
      default:
        return null;
    }
  }

  private shiftAt: number | null = null;   // run logs: when the slab landed
  private stopped = false;                  // ... and the Scout has stopped for it

  /** tools/run_b2.py records (B1-B3 descents with a slab shift): the same phases, from that log's kinds. */
  private applyRun(kind: string, r: Rec): PhaseId | null {
    switch (kind) {
      case 'level': {
        const level = String(r.level ?? '');
        if (this.phase('quake').state === 'pending') {
          this.facts.scene = 'levels';
          return this.set('quake', 'done', `levels scene: the Scout starts on ${level}`, null);
        }
        if (/^B\d$/.test(level)) return this.set('descend', 'done', `reached ${level}`, this.scout);
        return this.set('search', 'active', `Scout on ${level}`, this.scout);
      }
      case 'pose': {
        const pos = vec3(r.pos);
        const moved = this.pose(pos, 'scout');
        if (this.shiftAt !== null && !this.stopped && r.state === 'blocked') {
          this.stopped = true;
          this.facts.stops += 1;
          return this.set('recheck', 'held', 'Scout stopped short of the slab', pos);
        }
        return moved;
      }
      case 'plan': {
        const target = vec3(r.target);
        if (this.shiftAt !== null && this.stopped && r.status === 'ok' && this.phase('recheck').state !== 'done') {
          this.facts.rechecks += 1;
          return this.set('recheck', 'done', 're-planned around the slab from a fresh scan', target);
        }
        if (this.phase('search').state === 'pending') return this.set('search', 'active', `Scout ${r.why ?? 'exploring'}`, target);
        return null;
      }
      case 'shift': {
        this.shiftAt = num(r.t);
        this.facts.shifts += 1;
        const xy = Array.isArray(r.xy) ? r.xy : [0, 0];
        const z = vec3(r.scout)?.[2] ?? 0;
        return this.set('shift', 'done', `slab dropped on ${r.level} at [${xy.join(', ')}]`,
                        [Number(xy[0]) || 0, Number(xy[1]) || 0, z]);
      }
      case 'mapped':
        if (this.shiftAt === null) return null;
        if (!this.stopped) { this.stopped = true; this.facts.stops += 1; }
        return this.set('recheck', 'held', `slab mapped from the Scout's own ${Array.isArray(r.sources) ? r.sources.join(' + ') : 'scan'}`,
                        this.scout);
      case 'summary': {
        if (r.reached !== true) return null;
        const pos = vec3(r.final_pos);
        const id = `c${String(r.floor ?? '').replace('B', '')}`;
        if (pos) this.facts.casualties[id] = { pos, confidence: 1 };
        if (this.phase('search').state !== 'pending') this.phase('search').state = 'done';
        return this.set('found', 'done', `Scout reached ${id} on ${r.final_level}`, pos);
      }
      case 'verdict': {
        const steps = isRec(r.steps) ? Object.entries(r.steps).filter(([, v]) => isRec(v)) as [string, Rec][] : [];
        const ok = steps.filter(([, v]) => v.ok === true).length;
        this.facts.reportMarkdown = [`# Run checks: ${ok}/${steps.length} passed`,
          ...steps.map(([k, v]) => `- ${v.ok === true ? 'ok' : 'FAIL'} ${k}${v.detail ? `: ${v.detail}` : ''}`)].join('\n');
        return this.set('report', 'done', `${ok}/${steps.length} run checks passed`, null);
      }
      default:
        return null;
    }
  }

  private casualtyFocus(id?: unknown): Vec3 | null {
    const c = typeof id === 'string' ? this.facts.casualties[id] : Object.values(this.facts.casualties)[0];
    return c ? c.pos : null;
  }
}
