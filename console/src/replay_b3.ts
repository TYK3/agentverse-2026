// B3-CONSOLE-REPLAY: replay a real B3 rescue run in the console.
//
// The run is `python tools/run_b2.py --floor B3 --seed <n>` (#185) -> runs/b3-<seed>.jsonl: the e2e runner
// aimed at the deepest basement. It logs its own records, one {"t": sim seconds, "kind": ...} per line:
//   level {level}                     each level the Scout reaches (L1, ground, B1, B2, B3)
//   pose {pos, state, level, cell}    the Scout's real pose, 1 Hz (no yaw)
//   plan {status, why, target, cells} each (re-)plan; cells are [i, j, k] at 0.05 m (B3 floor is k = -36)
//   shift {xy, level, footprint}      the unscripted change: slab x1 lands on the route in B3
//   mapped {cells, sources}           the slab cells the Scout mapped from its own measurements
//   summary {floor, reached, final_pos, final_level, max_jump, route, route_k} and verdict {steps, ...}
// adaptB3Run() turns them into the bus messages the console already draws, in file order at the recorded
// sim time, and ReplayPlayer (replay-jsonl.ts) plays them:
//   pose  -> sensors/scout {t, pose: {pos, yaw}}   yaw from the direction of travel (the log has none)
//   plan  -> route/proposed (robot "scout", model "local-astar") when the route's goal or status changes,
//            plus log/decision when the status changes
//   level, mapped -> log/decision (reaching B3 is marked as the target floor)
//   shift -> world/change {kind: "aftershock", moved_blocks: ["x1"]} + log/decision (stop and recheck)
//   summary + verdict -> console/replay_b3 {floor, steps, passed, total, reached, on_target, route, ...}
//                        (console-only, last event)
// Honesty: ReplayPlayer announces console/replay {source: "replay"} with every step, never live; nothing is
// sent to the hub; data is the runner's own (pos keeps its z, so B3 stays 1.8 m below ground). A log that
// is not a B3 run (summary floor other than B3) still replays but is reported as an issue, and on_target
// is only true when the run ended on B3 and said it reached the casualty. Bad lines are issues, never thrown.
//
// Self-contained on purpose: the B2 adapter (#191) is not on main yet. Pure module, nothing runs on import.
// Wiring (not done here, main.ts belongs to the console owner):
//   const { player } = await loadB3Run('/replays/b3-0.jsonl', dispatchBusMessage, { speed: 4 });
//   player.start();

import { ReplayPlayer, type Dispatch, type ParsedRecording, type ParseIssue, type RecordedEvent, type Scheduler }
  from './replay-jsonl';

export const B3_STATUS_TOPIC = 'console/replay_b3';
export const B3_SCENE = 'levels';
export const B3_FLOOR = 'B3';
export const B3_LEVELS = ['L1', 'ground', 'B1', 'B2', 'B3'];
export const SLAB_ID = 'x1';                      // run_b2.py drops the levels scene's spare body x1 as the slab
const MODEL = 'local-astar';
const MIN_MOVE_M = 0.01;                          // below this, keep the previous heading

export type B3Step = { name: string; ok: boolean; t: number | null; detail: string };
export type B3Result = {
  floor: string | null;
  steps: B3Step[];
  passed: number;
  total: number;
  reached: boolean | null;
  on_target: boolean;
  final_level: string | null;
  final_pos: number[] | null;
  max_jump: number | null;
  route: string | null;
  route_k: number[] | null;
  levels: string[];
  descended_in_order: boolean;
  shift_t: number | null;
  shift_level: string | null;
};
export type B3Run = ParsedRecording & { result: B3Result; records: number };

type Rec = Record<string, unknown> & { t: number; kind: string };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

const isVec = (v: unknown, n: number): v is number[] =>
  Array.isArray(v) && v.length >= n && v.slice(0, n).every(x => typeof x === 'number' && Number.isFinite(x));

const isCells = (v: unknown): v is [number, number, number][] =>
  Array.isArray(v) && v.every(c => isVec(c, 3) && (c as number[]).every(Number.isInteger));

const fmt = (v: number[]) => `[${v.map(x => Math.round(x * 100) / 100).join(', ')}]`;
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);

/** Read the runner's records. Blank lines are ignored; anything else that is not a record is an issue. */
function readRecords(text: string, issues: ParseIssue[]): { rec: Rec; line: number }[] {
  const out: { rec: Rec; line: number }[] = [];
  let lastT = -Infinity;
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = i + 1;
    if (!raw.trim()) return;
    let v: unknown;
    try { v = JSON.parse(raw); } catch { return void issues.push({ line, reason: 'not JSON' }); }
    if (!isRecord(v)) return void issues.push({ line, reason: 'not an object' });
    if (typeof v.kind !== 'string' || !v.kind) return void issues.push({ line, reason: 'missing kind' });
    if (typeof v.t !== 'number' || !Number.isFinite(v.t) || v.t < 0) {
      return void issues.push({ line, reason: 'missing or invalid t' });
    }
    if (v.t < lastT) issues.push({ line, reason: `time goes back (${v.t} after ${lastT}); kept in file order` });
    lastT = Math.max(lastT, v.t);
    out.push({ rec: v as Rec, line });
  });
  return out;
}

/** Headings from the direction of travel: each pose looks ahead to the next pose that moved. */
function headings(records: { rec: Rec; line: number }[]): Map<number, number> {
  const poses = records.filter(r => r.rec.kind === 'pose' && isVec(r.rec.pos, 3));
  const yawAt = new Map<number, number>();
  let yaw = 0;
  poses.forEach((p, i) => {
    const here = p.rec.pos as number[];
    for (let j = i + 1; j < poses.length; j++) {
      const there = poses[j].rec.pos as number[];
      if (Math.hypot(there[0] - here[0], there[1] - here[1]) >= MIN_MOVE_M) {
        yaw = Math.atan2(there[1] - here[1], there[0] - here[0]);
        break;
      }
    }
    yawAt.set(p.line, Math.round(yaw * 1000) / 1000);
  });
  return yawAt;
}

/** Turn a B3 run log into console bus events (see the header for the mapping). */
export function adaptB3Run(text: string): B3Run {
  const issues: ParseIssue[] = [];
  const records = readRecords(text, issues);
  const events: RecordedEvent[] = [];
  const result: B3Result = { floor: null, steps: [], passed: 0, total: 0, reached: null, on_target: false,
                             final_level: null, final_pos: null, max_jump: null, route: null, route_k: null,
                             levels: [], descended_in_order: false, shift_t: null, shift_level: null };
  const push = (t: number, topic: string, data: unknown, line: number) => events.push({ t, topic, data, line });
  const decide = (t: number, line: number, perception: string, outcome: string, reason: string) =>
    push(t, 'log/decision', { t, perception, model: MODEL, physics: '', outcome, reason }, line);
  const yawAt = headings(records);

  let routes = 0;
  let lastKey = '';
  let lastStatus = '';
  let summary: { rec: Rec; line: number } | null = null;
  let verdict: Rec | null = null;
  let endT = 0;
  for (const { rec, line } of records) {
    const t = rec.t;
    endT = Math.max(endT, t);
    switch (rec.kind) {
      case 'pose':
        if (!isVec(rec.pos, 3)) { issues.push({ line, reason: 'pose without pos [x, y, z]' }); break; }
        push(t, 'sensors/scout', { t, pose: { pos: rec.pos.slice(0, 3), yaw: yawAt.get(line) ?? 0 } }, line);
        break;
      case 'plan': {
        const status = str(rec.status) ?? 'unknown';
        const why = str(rec.why) ?? status;
        if (status !== lastStatus) {
          decide(t, line, `Scout plan: ${status}`, status, why);
          lastStatus = status;
        }
        if (!isCells(rec.cells)) { issues.push({ line, reason: 'plan cells are not [i, j, k] integers' }); break; }
        if (rec.cells.length === 0) break;
        const target = isVec(rec.target, 3) ? fmt(rec.target as number[]) : 'unknown';
        const key = `${status}|${target}`;
        if (key === lastKey) break;
        lastKey = key;
        routes += 1;
        push(t, 'route/proposed', { id: `b3-r${routes}`, robot: 'scout', cells: rec.cells, goal: `${status} to ${target}`,
                                     reason: why, model: MODEL }, line);
        break;
      }
      case 'level': {
        const level = str(rec.level);
        if (!level) { issues.push({ line, reason: 'level without a name' }); break; }
        result.levels.push(level);
        const target = level === B3_FLOOR;
        decide(t, line, target ? `Scout on ${level}, the target floor` : `Scout on ${level}`, 'level',
               `reached ${level} by driving (no teleport)`);
        break;
      }
      case 'shift': {
        const where = isVec(rec.xy, 2) ? fmt(rec.xy as number[]) : 'unknown';
        const level = str(rec.level) ?? 'unknown';
        result.shift_t = t;
        result.shift_level = str(rec.level);
        push(t, 'world/change', { kind: 'aftershock', t, moved_blocks: [SLAB_ID] }, line);
        decide(t, line, `slab landed on the route at ${where} on ${level}`, 'stop_and_recheck',
               'stop short, map the slab from the Scout\'s own measurements, re-plan around it');
        break;
      }
      case 'mapped': {
        const n = typeof rec.cells === 'number' ? rec.cells : 0;
        const src = Array.isArray(rec.sources) ? rec.sources.join(', ') : 'unknown';
        decide(t, line, `${n} slab cell(s) mapped from ${src}`, 'mapped', 'measured by the Scout, not sim truth');
        break;
      }
      case 'summary':
        summary = { rec, line };
        break;
      case 'verdict':
        verdict = rec;
        break;
      default:
        issues.push({ line, reason: `unknown kind ${rec.kind}` });
    }
  }

  if (verdict && isRecord(verdict.steps)) {
    for (const [name, s] of Object.entries(verdict.steps)) {
      if (!isRecord(s)) continue;
      result.steps.push({ name, ok: s.ok === true, t: typeof s.t === 'number' ? s.t : null,
                          detail: str(s.detail) ?? '' });
    }
  }
  result.total = result.steps.length;
  result.passed = result.steps.filter(s => s.ok).length;
  result.descended_in_order = B3_LEVELS.every((l, i) => result.levels[i] === l);
  if (summary) {
    const s = summary.rec;
    result.floor = str(s.floor);
    if (result.floor !== B3_FLOOR) {
      issues.push({ line: summary.line, reason: `not a B3 run: summary floor is ${result.floor ?? 'missing'}` });
    }
    result.reached = typeof s.reached === 'boolean' ? s.reached : null;
    result.final_level = str(s.final_level);
    result.final_pos = isVec(s.final_pos, 3) ? (s.final_pos as number[]) : null;
    result.max_jump = typeof s.max_jump === 'number' ? s.max_jump : null;
    result.route = str(s.route);
    result.route_k = isVec(s.route_k, 2) ? (s.route_k as number[]) : null;
    result.on_target = result.floor === B3_FLOOR && result.final_level === B3_FLOOR && result.reached === true;
  }
  if (summary || verdict) push(endT, B3_STATUS_TOPIC, { source: 'replay', ...result }, Infinity);
  return { events, issues, meta: null, scene: B3_SCENE, result, records: records.length };
}

/** Adapt a B3 log and make its player (not started). */
export function playB3Run(text: string, dispatch: Dispatch,
                          opts: { source?: string; speed?: number; scheduler?: Scheduler } = {}) {
  const run = adaptB3Run(text);
  const player = new ReplayPlayer(run, dispatch, { ...opts, source: opts.source ?? 'b3 run' });
  return { run, player };
}

/** Fetch a B3 log and make its player (not started). Throws if the file cannot be fetched. */
export async function loadB3Run(url: string, dispatch: Dispatch,
                                opts: { speed?: number; scheduler?: Scheduler } = {}) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`B3 run ${url}: HTTP ${response.status}`);
  return playB3Run(await response.text(), dispatch, { source: url, ...opts });
}
