// Story mode (ref DEMO-FLOW): the whole rescue on one screen.
//
// A phase strip lit by real bus events (live, or a recording replayed with ?run=<url>), the camera
// following the action of each phase, and a report card at the end. Two parts:
// - StoryModel: pure. apply(topic, data) moves the phases on; no DOM, so tests drive it directly.
// - StoryView: the overlay (strip, caption, LIVE/REPLAY badge, follow toggle, report card) and the
//   camera follow (it eases the map's OrbitControls target; it pauses while the user drags).
// setupStory(mapViewer) wires both to the bus and, with ?run=, replays the recording (replay-jsonl.ts)
// instead of the live socket. It only reads the bus; it never sends.

import './story.css';
import { on } from './bus';
import { parseJsonl, ReplayPlayer, STATUS_TOPIC, type ReplayStatus } from './replay-jsonl';
import { BELOW_GROUND_Z, PHASES, StoryModel, type PhaseId, type Vec3 } from './story-model';

export { PHASES, StoryModel } from './story-model';

// ---------------------------------------------------------------------------------------------------
// View

type Viewer = {
  camera: { position: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void } };
  controls: { target: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void };
              update: () => void; addEventListener?: (type: 'start', fn: () => void) => void };
};

const FOLLOW_PAUSE_MS = 8000;
const EASE = 0.06;

export class StoryView {
  readonly root: HTMLElement;
  private chips = new Map<PhaseId, HTMLElement>();
  private caption: HTMLElement;
  private badge: HTMLElement;
  private card: HTMLElement;
  private followBtn: HTMLButtonElement;
  follow = true;
  private pausedUntil = 0;
  private goal: Vec3 | null = null;

  constructor(private model: StoryModel, private viewer: Viewer | null, mode: 'live' | 'replay') {
    this.root = document.createElement('section');
    this.root.id = 'story';
    this.root.setAttribute('aria-label', 'Rescue story');
    const strip = document.createElement('ol');
    strip.className = 'story-strip';
    PHASES.forEach((p, i) => {
      const li = document.createElement('li');
      li.className = 'story-phase';
      li.dataset.phase = p.id;
      li.dataset.state = 'pending';
      li.innerHTML = `<span class="story-num">${i + 1}</span><span class="story-label">${p.label}</span>`;
      strip.appendChild(li);
      this.chips.set(p.id, li);
    });
    this.badge = document.createElement('span');
    this.badge.className = 'story-badge';
    this.badge.dataset.mode = mode;
    this.badge.textContent = mode === 'live' ? 'LIVE' : 'REPLAY';
    this.followBtn = document.createElement('button');
    this.followBtn.type = 'button';
    this.followBtn.className = 'story-follow';
    this.followBtn.addEventListener('click', () => { this.follow = !this.follow; this.pausedUntil = 0; this.render(); });
    this.caption = document.createElement('p');
    this.caption.className = 'story-caption';
    this.caption.setAttribute('aria-live', 'polite');
    const head = document.createElement('div');
    head.className = 'story-head';
    head.append(this.badge, strip, this.followBtn);
    this.card = document.createElement('div');
    this.card.className = 'story-card';
    this.card.hidden = true;
    this.root.append(head, this.caption, this.card);
    (document.getElementById('map-panel') ?? document.body).appendChild(this.root);
    viewer?.controls.addEventListener?.('start', () => { this.pausedUntil = performance.now() + FOLLOW_PAUSE_MS; });
    this.render();
    this.tick();
  }

  replayStatus(s: ReplayStatus): void {
    const name = s.file.split('/').pop();
    this.badge.textContent = `REPLAY ${name} · t ${s.t.toFixed(1)} s${s.state === 'done' ? ' · end' : ''}`;
    if (s.state === 'done') this.showCard();
  }

  render(): void {
    for (const p of PHASES) {
      const chip = this.chips.get(p.id)!;
      const ph = this.model.phase(p.id);
      chip.dataset.state = ph.state;
      chip.classList.toggle('story-current', this.model.current === p.id);
      chip.title = ph.note || p.label;
    }
    const cur = this.model.current;
    this.caption.textContent = cur ? `${PHASES.find(p => p.id === cur)!.label}: ${this.model.phase(cur).note}` : 'Waiting for the scene…';
    this.followBtn.textContent = this.follow ? 'Camera: follow' : 'Camera: free';
    this.followBtn.setAttribute('aria-pressed', String(this.follow));
    if (this.model.focus) this.goal = this.model.focus;
    if (this.model.phase('report').state === 'done') this.showCard();
  }

  showCard(): void {
    const f = this.model.facts;
    const found = Object.keys(f.casualties);
    const rows: [string, string][] = [
      ['Scene', f.scene ?? '—'],
      ['Time', `${this.model.t.toFixed(1)} s`],
      ['Casualties found', found.length ? found.join(', ') : 'none'],
      ['Replies heard', String(f.replies)],
      ['Deepest level reached', f.deepestZ < BELOW_GROUND_Z ? `z ${f.deepestZ.toFixed(1)} m` : 'ground'],
      ['Supplies delivered', f.delivered.length ? f.delivered.join(', ') : 'none'],
      ['Approvals', `${f.approvals.approved} approved, ${f.approvals.held} held, of ${f.approvals.asked} asked`],
      ['Ground moved', String(f.shifts)],
      ['Stops / rechecks', `${f.stops} / ${f.rechecks}`],
      ['Phases reached', `${this.model.lit().length} of ${PHASES.length}`],
    ];
    const missed = PHASES.filter(p => this.model.phase(p.id).state === 'pending').map(p => p.label);
    this.card.innerHTML = '';
    const h = document.createElement('h2');
    h.textContent = 'Rescue report';
    const dl = document.createElement('dl');
    for (const [k, v] of rows) {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      dl.append(dt, dd);
    }
    this.card.append(h, dl);
    if (missed.length) {
      const p = document.createElement('p');
      p.className = 'story-missed';
      p.textContent = `Not seen in this run: ${missed.join(', ')}`;
      this.card.append(p);
    }
    if (f.reportMarkdown) {
      const pre = document.createElement('pre');
      pre.textContent = f.reportMarkdown.split('\n').slice(0, 12).join('\n');
      this.card.append(pre);
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = 'Close';
    close.addEventListener('click', () => { this.card.hidden = true; });
    this.card.append(close);
    this.card.hidden = false;
  }

  /** Ease the orbit target (and the camera with it) toward the current phase's focus. */
  private tick = (): void => {
    const v = this.viewer;
    if (v && this.goal && this.follow && performance.now() > this.pausedUntil) {
      const t = v.controls.target, c = v.camera.position;
      const dx = (this.goal[0] - t.x) * EASE, dy = (this.goal[1] - t.y) * EASE, dz = (this.goal[2] - t.z) * EASE;
      if (Math.abs(dx) + Math.abs(dy) + Math.abs(dz) > 1e-4) {
        t.set(t.x + dx, t.y + dy, t.z + dz);
        c.set(c.x + dx, c.y + dy, c.z + dz);
        v.controls.update();
      }
    }
    requestAnimationFrame(this.tick);
  };
}

/** Wire story mode to the bus. With ?run=<url>, replay that recording instead of the live socket;
 *  `replaying` tells main.ts not to connect. */
export function setupStory(viewer: Viewer | null): { model: StoryModel; view: StoryView; replaying: boolean } {
  const params = new URLSearchParams(window.location.search);
  const run = params.get('run');
  const model = new StoryModel();
  const view = new StoryView(model, viewer, run ? 'replay' : 'live');
  on('*', msg => {
    const { topic, data } = msg as { topic: string; data: unknown };
    if (topic === STATUS_TOPIC) {
      model.setTime((data as ReplayStatus).t);           // the recording's own sim time
      return view.replayStatus(data as ReplayStatus);
    }
    if (model.apply(topic, data)) view.render();
  });
  if (run) {
    const speed = Number(params.get('speed')) || 1;
    const dispatch = (window as unknown as { dispatchBusMessage: (t: string, d: unknown) => void }).dispatchBusMessage;
    void fetch(run).then(r => {
      if (!r.ok) throw new Error(`${run}: HTTP ${r.status}`);
      return r.text();
    }).then(text => {
      new ReplayPlayer(parseJsonl(text), dispatch, { source: run, speed }).start();
    }).catch(err => {
      view.replayStatus({ source: 'replay', file: run, state: 'stopped', t: 0, index: 0, total: 0, speed,
                          scene: null, skipped_lines: 0 });
      console.error('[story] replay failed', err);
    });
  }
  return { model, view, replaying: Boolean(run) };
}
