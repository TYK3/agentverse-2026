// Stage ring: next to the LIVE badge, show only the current stage (Find, Reach,
// Deliver, Report) with a thin loading ring. It reads the story strip that
// story.ts keeps up to date (the strip stays in the DOM but is hidden), so the
// story model and its tests are unchanged.
// The ring fills as the stage's phases finish; amber and still while waiting on
// the operator. When a stage ends the ring closes, a tick draws, and the next
// stage slides in. The last stage ends on a tick.
const STAGES: { name: string; phases: string[] }[] = [
  { name: 'Find', phases: ['quake', 'search', 'found'] },
  { name: 'Reach', phases: ['talk', 'descend', 'approve'] },
  { name: 'Deliver', phases: ['deliver', 'shift', 'recheck'] },
  { name: 'Report', phases: ['report'] },
];

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function setupStageRing(): void {
  const strip = document.querySelector<HTMLElement>('#story .story-strip');
  const head = strip?.parentElement;
  if (!strip || !head) return;

  const view = document.createElement('div');
  view.className = 'stage-ring';
  view.setAttribute('role', 'status');
  view.setAttribute('aria-live', 'polite');
  view.innerHTML =
    '<span class="ring-wrap"><span class="ring"></span>' +
    '<svg class="tick" viewBox="0 0 26 26" aria-hidden="true"><path d="M8 13.5l3.5 3.5L18.5 9.5"/></svg></span>' +
    '<span class="ring-stage"></span>';
  strip.insertAdjacentElement('beforebegin', view);
  const wrap = view.querySelector<HTMLElement>('.ring-wrap')!;
  const ring = view.querySelector<HTMLElement>('.ring')!;
  const label = view.querySelector<HTMLElement>('.ring-stage')!;
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;

  let shown: number | null = null;
  let token = 0;

  const read = () => {
    const chips = [...strip.querySelectorAll<HTMLElement>('.story-phase')];
    const cur = chips.find((c) => c.classList.contains('story-current'));
    const lastStarted = [...chips].reverse().find((c) => c.dataset.state !== 'pending');
    const phase = (cur ?? lastStarted)?.dataset.phase ?? null;
    const stage = Math.max(0, STAGES.findIndex((s) => phase !== null && s.phases.includes(phase)));
    const state = (id: string) => chips.find((c) => c.dataset.phase === id)?.dataset.state ?? 'pending';
    const s = STAGES[stage];
    const done = s.phases.filter((id) => state(id) === 'done').length;
    const waiting = !!cur && (cur.dataset.state === 'waiting' || cur.dataset.state === 'held');
    const allDone = state('report') === 'done';
    const started = phase !== null;
    return { stage, fill: done / s.phases.length, waiting, allDone, started, title: cur?.title ?? '' };
  };

  const paint = (r: ReturnType<typeof read>) => {
    label.textContent = r.started ? STAGES[r.stage].name : 'Standby';
    ring.style.setProperty('--p', `${Math.round((r.allDone ? 1 : r.fill) * 100)}%`);
    view.classList.toggle('is-waiting', r.waiting);
    view.classList.toggle('is-idle', !r.started);
    wrap.classList.toggle('is-ticked', r.allDone);
    view.title = r.title;
  };

  const update = async () => {
    const r = read();
    const forward = shown !== null && r.stage > shown && !reduce;
    shown = r.stage;
    const my = ++token;
    if (!forward) {
      view.classList.remove('is-leaving', 'is-entering');
      wrap.classList.remove('is-filling');
      paint(r);
      return;
    }
    // close the old stage's ring, tick, hold, slide out, slide the new stage in
    wrap.classList.add('is-filling');
    ring.style.setProperty('--p', '100%');
    await wait(420); if (my !== token) return;
    wrap.classList.add('is-ticked');
    await wait(800); if (my !== token) return;
    view.classList.add('is-leaving');
    await wait(300); if (my !== token) return;
    wrap.classList.remove('is-ticked', 'is-filling');
    view.classList.remove('is-leaving');
    view.classList.add('is-entering');
    paint(read());
    requestAnimationFrame(() => requestAnimationFrame(() => { if (my === token) view.classList.remove('is-entering'); }));
  };

  new MutationObserver(() => { void update(); })
    .observe(strip, { attributes: true, subtree: true, attributeFilter: ['class', 'data-state'] });
  void update();
}
