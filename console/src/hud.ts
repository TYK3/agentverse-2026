// Run HUD (ref CONSOLE-HUD): the run clock and the four rescue stages with their split times,
// on the 3D map's top bar. The clock is sim time, never the wall clock: live it comes from the
// sim-stamped topics (StoryModel.apply), in a replay from the recording's own t (console/replay).
// The stages are stage-ring.ts's four (Find, Reach, Deliver, Report) over StoryModel's phases, and,
// like the ring, the current stage is the furthest one that has started.
import type { Envelope, Handler } from './bus';
import { StoryModel, type PhaseId } from './story-model';

export const HUD_STAGES: { name: string; phases: PhaseId[] }[] = [
  { name: 'Find', phases: ['quake', 'search', 'found'] },
  { name: 'Reach', phases: ['talk', 'descend', 'approve'] },
  { name: 'Deliver', phases: ['deliver', 'shift', 'recheck'] },
  { name: 'Report', phases: ['report'] },
];

export type HudStage = { name: string; state: 'pending' | 'current' | 'done'; start: number | null; took: number | null };

/** "m:ss" under an hour, "h:mm:ss" after; "--:--" before any sim time is known. */
export function formatClock(t: number | null): string {
  if (t === null || !Number.isFinite(t) || t < 0) return '--:--';
  const s = Math.floor(t);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/** Pure (no DOM, no bus), so the console tests drive it directly; setupHud draws it. */
export class HudModel {
  story = new StoryModel();
  private seen = false;   // any sim time or phase yet

  apply(topic: string, data: unknown): void {
    if (topic === 'console/replay') {
      const t = (data as { t?: unknown } | null)?.t;
      if (typeof t === 'number') { this.story.setTime(t); this.seen = true; }
      return;
    }
    if (topic === 'scene/loaded' && this.story.phase('quake').state !== 'pending') this.story = new StoryModel();  // a new run
    if (this.story.apply(topic, data) !== null || this.story.t > 0) this.seen = true;
  }

  clock(): number | null { return this.seen ? this.story.t : null; }

  stages(): HudStage[] {
    const starts = HUD_STAGES.map(s => {
      const ts = s.phases.map(id => this.story.phase(id)).filter(p => p.state !== 'pending').map(p => p.t ?? 0);
      return ts.length ? Math.min(...ts) : null;
    });
    let current = -1;
    starts.forEach((t, i) => { if (t !== null) current = i; });
    const finished = this.story.phase('report').state === 'done';
    return HUD_STAGES.map((s, i) => {
      const start = starts[i];
      if (start === null || i > current) return { name: s.name, state: 'pending', start: null, took: null };
      const next = starts.slice(i + 1).find((t): t is number => t !== null);
      if (i < current) return { name: s.name, state: 'done', start, took: Math.max(0, (next ?? start) - start) };
      if (finished) return { name: s.name, state: 'done', start, took: Math.max(0, this.story.t - start) };
      return { name: s.name, state: 'current', start, took: Math.max(0, this.story.t - start) };
    });
  }
}

const CSS = `
.run-hud { display: flex; align-items: center; gap: 0.35rem; pointer-events: auto; font-size: 1.05rem;
  font-family: var(--retro-font, monospace); border-radius: 2px;
  font-variant-numeric: tabular-nums; background: rgba(15, 23, 42, 0.85); color: #e2e8f0;
  padding: 0.3rem 0.6rem; border: 1px solid rgba(56, 189, 248, 0.3);
  backdrop-filter: blur(4px); white-space: nowrap; }
.run-hud .hud-clock { font-weight: 700; color: #f8fafc; margin-right: 0.25rem; }
.run-hud .hud-stage { padding: 0.1rem 0.4rem; border-radius: 0.3rem; color: #64748b; }
.run-hud .hud-stage[data-state="done"] { color: #86efac; }
.run-hud .hud-stage[data-state="current"] { color: #0f172a; background: #38bdf8; font-weight: 700; }
.run-hud .hud-sep { color: #475569; }
@media (max-width: 720px) { .run-hud .hud-stage[data-state="pending"], .run-hud .hud-sep { display: none; } }
`;

/** Mount the HUD in the map's top bar and keep it current from every bus message (live or replay). */
export function setupHud(on: (topic: string, handler: Handler) => unknown): HudModel | null {
  const bar = document.querySelector<HTMLElement>('.map-hud-top');
  if (!bar) return null;
  if (!document.getElementById('run-hud-style')) {
    const style = document.createElement('style');
    style.id = 'run-hud-style';
    style.textContent = CSS;
    document.head.appendChild(style);
  }
  const view = document.createElement('div');
  view.id = 'run-hud';
  view.className = 'run-hud';
  view.setAttribute('role', 'timer');
  view.setAttribute('aria-label', 'Run clock and rescue stages');
  bar.insertBefore(view, bar.querySelector('.map-stats-badge'));

  const model = new HudModel();
  const render = () => {
    const stages = model.stages();
    const chips = stages.map(s => {
      const time = s.state === 'pending' ? '' : ` ${formatClock(s.took)}`;
      const title = s.start === null ? `${s.name}: not started` : `${s.name}: started at T+${formatClock(s.start)}`;
      return `<span class="hud-stage" data-stage="${s.name}" data-state="${s.state}" title="${title}">${s.name}${time}</span>`;
    }).join('<span class="hud-sep">›</span>');
    view.innerHTML = `<span class="hud-clock" title="sim time">T+${formatClock(model.clock())}</span>${chips}`;
  };
  let queued = false;
  on('*', message => {
    const { topic, data } = message as unknown as Envelope;
    model.apply(topic, data);
    if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; render(); }); }
  });
  render();
  (window as unknown as { aftershockHud: HudModel }).aftershockHud = model;  // read by the browser tests
  return model;
}
