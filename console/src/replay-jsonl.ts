// Replay a real sim recording in the console (ref S1): the runs/*.jsonl written by SIM_RECORD
// (sim/recorder.py) or the integration runner (tools/run_rescue.py), one {"t","topic","data"} per line.
//
// No DOM or WebSocket runs on import. The console wires it in (c1):
//   const parsed = parseJsonl(await (await fetch(url)).text());
//   const player = new ReplayPlayer(parsed, (topic, data) => dispatchBusMessage(topic, data), { source: url });
//   player.start();
//
// What it guarantees:
// - order: events are dispatched in file order, which is the order they happened on the bus;
// - time: pacing follows the recorded sim time `t` (scaled by `speed`), never wall clock;
// - data: each message's data is passed through untouched, so poses keep their z, maps their layers;
// - honesty: it never claims to be live. Alongside the messages it dispatches `console/replay`
//   {source:"replay", file, t, index, total, state} so the screen can say "REPLAY of <file> at t=..";
//   `record/meta` lines become that status, not bus messages.
// - malformed lines are skipped and reported (line number and reason), never thrown.

export type RecordedEvent = { t: number; topic: string; data: unknown; wall?: number; line: number };
export type ParseIssue = { line: number; reason: string };
export type ParsedRecording = {
  events: RecordedEvent[];
  issues: ParseIssue[];
  meta: Record<string, unknown> | null;   // the record/meta line, if the recording has one
  scene: string | null;                   // from record/meta or the first scene/loaded
};
export type ReplayStatus = {
  source: 'replay';
  file: string;
  state: 'ready' | 'playing' | 'paused' | 'done' | 'stopped';
  t: number;
  index: number;
  total: number;
  speed: number;
  duration?: number;
  scene: string | null;
  skipped_lines: number;
};
export type Dispatch = (topic: string, data: unknown) => void;
export type Scheduler = {
  set: (fn: () => void, ms: number) => unknown;
  clear: (handle: unknown) => void;
};

export const STATUS_TOPIC = 'console/replay';
const META_TOPIC = 'record/meta';

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Parse a recording. Blank lines are ignored; anything else that is not a valid event is an issue. */
export function parseJsonl(text: string): ParsedRecording {
  const events: RecordedEvent[] = [];
  const issues: ParseIssue[] = [];
  let meta: Record<string, unknown> | null = null;
  let scene: string | null = null;
  let lastT = -Infinity;
  const lines = text.split(/\r?\n/);
  lines.forEach((raw, i) => {
    const line = i + 1;
    if (!raw.trim()) return;
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      issues.push({ line, reason: 'not JSON' });
      return;
    }
    if (!isRecord(value)) return void issues.push({ line, reason: 'not an object' });
    const { t, topic, data, wall } = value;
    if (typeof topic !== 'string' || !topic) return void issues.push({ line, reason: 'missing topic' });
    if (typeof t !== 'number' || !Number.isFinite(t) || t < 0) {
      return void issues.push({ line, reason: 'missing or invalid t' });
    }
    if (!('data' in value)) return void issues.push({ line, reason: 'missing data' });
    if (t < lastT) issues.push({ line, reason: `time goes back (${t} after ${lastT}); kept in file order` });
    lastT = Math.max(lastT, t);
    if (topic === META_TOPIC) {
      if (isRecord(data)) {
        meta = data;
        if (typeof data.scene === 'string') scene = data.scene;
      }
      return;
    }
    if (topic === 'scene/loaded' && scene === null && isRecord(data) && typeof data.scene === 'string') {
      scene = data.scene;
    }
    events.push({ t, topic, data, line, ...(typeof wall === 'number' ? { wall } : {}) });
  });
  return { events, issues, meta, scene };
}

const timers: Scheduler = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: handle => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Dispatches a parsed recording at its recorded pace. One player per recording. */
export class ReplayPlayer {
  readonly events: RecordedEvent[];
  private readonly dispatch: Dispatch;
  private readonly scheduler: Scheduler;
  private readonly file: string;
  private readonly scene: string | null;
  private readonly skipped: number;
  private readonly seekAt: number;
  private readonly duration: number;
  private index = 0;
  private handle: unknown = null;
  private dueAt: number | null = null;
  private remainingMs = 0;
  private state: ReplayStatus['state'] = 'ready';
  speed: number;

  constructor(parsed: ParsedRecording, dispatch: Dispatch,
              opts: { source?: string; speed?: number; scheduler?: Scheduler; seekAt?: number } = {}) {
    this.events = parsed.events;
    this.dispatch = dispatch;
    this.scheduler = opts.scheduler ?? timers;
    this.file = opts.source ?? 'recording';
    this.scene = parsed.scene;
    this.skipped = parsed.issues.filter(i => !i.reason.startsWith('time goes back')).length;
    this.duration = parsed.events.reduce((latest, event) => Math.max(latest, event.t), 0);
    this.speed = opts.speed && opts.speed > 0 ? opts.speed : 1;
    const querySeek = typeof window === 'undefined' ? 0 : Number(new URLSearchParams(window.location.search).get('seek'));
    const requested = opts.seekAt ?? querySeek;
    this.seekAt = Number.isFinite(requested) && requested > 0 ? requested : 0;
    if (typeof window !== 'undefined') {
      (window as unknown as { activeReplayPlayer: ReplayPlayer }).activeReplayPlayer = this;
    }
  }

  status(): ReplayStatus {
    const at = this.events[Math.min(this.index, this.events.length) - 1];
    return { source: 'replay', file: this.file, state: this.state, t: at ? at.t : 0, index: this.index,
             total: this.events.length, speed: this.speed, scene: this.scene, skipped_lines: this.skipped,
             duration: this.duration };
  }

  private announce(): void {
    this.dispatch(STATUS_TOPIC, this.status());
  }

  private schedule(wait: number): void {
    this.remainingMs = wait;
    this.dueAt = performance.now() + wait;
    this.handle = this.scheduler.set(() => this.step(), wait);
  }

  start(): void {
    if (this.state === 'playing' || this.state === 'done') return;
    const resuming = this.state === 'paused';
    this.state = 'playing';
    if (this.index === 0 && this.seekAt > 0) {
      // A scrub reload starts with clean views. Rebuild them from the recording in
      // file order, then wait the remaining recorded time before the next event.
      while (this.index < this.events.length && this.events[this.index].t <= this.seekAt) {
        const ev = this.events[this.index++];
        this.dispatch(ev.topic, ev.data);
      }
      if (this.index >= this.events.length) {
        this.state = 'done';
        this.announce();
        return;
      }
      this.announce();
      const wait = Math.max(0, (this.events[this.index].t - this.seekAt) * 1000 / this.speed);
      this.schedule(wait);
      return;
    }
    this.announce();
    if (resuming) this.schedule(this.remainingMs);
    else this.step();
  }

  pause(): void {
    if (this.state !== 'playing') return;
    if (this.dueAt !== null) this.remainingMs = Math.max(0, this.dueAt - performance.now());
    this.cancel();
    this.state = 'paused';
    this.announce();
  }

  stop(): void {
    this.cancel();
    this.state = 'stopped';
    this.announce();
  }

  private cancel(): void {
    if (this.handle !== null) this.scheduler.clear(this.handle);
    this.handle = null;
    this.dueAt = null;
  }

  /** Dispatch every event due now, then wait (scaled sim time) for the next one. */
  private step(): void {
    this.handle = null;
    this.dueAt = null;
    if (this.state !== 'playing') return;
    const due = this.events[this.index]?.t;
    while (this.index < this.events.length && this.events[this.index].t <= due) {
      const ev = this.events[this.index++];
      this.dispatch(ev.topic, ev.data);
    }
    this.announce();
    if (this.index >= this.events.length) {
      this.state = 'done';
      this.announce();
      return;
    }
    const wait = Math.max(0, (this.events[this.index].t - due) * 1000 / this.speed);
    this.schedule(wait);
  }
}
