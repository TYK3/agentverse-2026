import { on, send } from './bus';
import { setupSpeak } from './speak';

type Data = Record<string, any>;
const el = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const object = (value: unknown): Data => value && typeof value === 'object' ? value as Data : {};
function text(tag: string, value: unknown, className = ''): HTMLElement {
  const node = document.createElement(tag);
  node.textContent = String(value ?? '');
  node.className = className;
  return node;
}
function badges(node: HTMLElement, data: Data): void {
  // Nested report fields retain their simulation/estimate labels as well.
  const raw = JSON.stringify(data);
  if (/"simulated"\s*:\s*true/.test(raw)) node.append(text('span', 'SIMULATED', 'badge'));
  if (/"estimate"\s*:\s*true/.test(raw)) node.append(text('span', 'ESTIMATE', 'badge'));
}
// CONSOLE-TALK: what the robots said to each casualty, what came back, the facts heard and the gate asks,
// in one running transcript. The panel builds its own DOM and scoped styles, so index.html and style.css
// stay untouched; every message string goes in through textContent, never as HTML.
const TALK_LIMIT = 120;
const TALK_CSS = `
.talk-panel { background: var(--panel-2, #131d2e); border: 1px solid var(--border, #233754); border-radius: 0.5rem;
  padding: 0.75rem; margin-bottom: 1.5rem; font-size: 0.78rem; color: var(--text-2, #cbd5e1); }
.talk-empty { color: var(--muted, #64748b); font-style: italic; margin: 0; }
.talk-contacts { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }
.talk-contact { display: inline-flex; align-items: center; gap: 0.35rem; background: var(--panel, #0e1726);
  border: 1px solid var(--border, #233754); border-radius: 999px; padding: 0.15rem 0.55rem; }
.talk-contact b { color: var(--text, #e2e8f0); }
.talk-status { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }
.talk-status.talking { color: var(--ok, #34d399); } .talk-status.done { color: var(--accent-soft, #93c5fd); }
.talk-status.unresponsive, .talk-status.stopped { color: var(--danger, #f87171); }
.talk-facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 0.6rem; margin: 0 0 0.6rem;
  padding: 0.45rem 0.55rem; background: var(--panel, #0e1726); border-radius: 0.35rem; }
.talk-facts dt { color: var(--muted, #64748b); }
.talk-facts dd { margin: 0; color: var(--text, #e2e8f0); overflow-wrap: anywhere; }
.talk-log { list-style: none; margin: 0; padding: 0; max-height: 22rem; overflow-y: auto; display: flex;
  flex-direction: column; gap: 0.35rem; }
.talk-line { padding: 0.35rem 0.5rem; border-radius: 0.35rem; border-left: 3px solid var(--border-hi, #475569);
  background: var(--panel, #0e1726); overflow-wrap: anywhere; line-height: 1.35; }
.talk-line small { display: block; color: var(--muted, #64748b); font-size: 0.68rem; margin-bottom: 0.1rem; }
.talk-line.robot { border-left-color: var(--accent, #60a5fa); }
.talk-line.casualty { border-left-color: var(--accent-soft, #34d399); }
.talk-line.ask { border-left-color: var(--warn, #f59e0b); }
.talk-line.ask.rejected { border-left-color: var(--danger, #f87171); }
.talk-line.ask.approved { border-left-color: var(--ok, #34d399); }
.talk-tag { font-size: 0.64rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  margin-left: 0.35rem; color: var(--muted, #94a3b8); }
.talk-level { display: inline-block; width: 3rem; height: 0.3rem; margin-left: 0.4rem; vertical-align: middle;
  background: var(--border, #233754); border-radius: 1px; overflow: hidden; }
.talk-level > span { display: block; height: 100%; background: var(--accent-soft, #34d399); }
`;
const FACT_LABELS: Record<string, string> = { responsive: 'Responsive', hurt: 'Hurts', bleeding: 'Bleeding',
  trapped: 'Trapped', breathing: 'Breathing', conscious: 'Conscious' };
function factValue(value: unknown): string {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  if (Array.isArray(value)) return value.length ? value.map(v => String(v)).join(', ') : 'none';
  if (value === null || value === undefined || value === '') return 'unknown';
  return String(value);
}
function factLabel(key: string): string {
  return FACT_LABELS[key] ?? key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
}

export function setupTalkPanel(): void {
  const host = el('right-panel');
  if (!host || el('talk-panel')) return;
  if (!document.getElementById('talk-panel-style')) {
    const style = document.createElement('style');
    style.id = 'talk-panel-style';
    style.textContent = TALK_CSS;
    document.head.append(style);
  }
  const title = text('h2', 'Casualty talk');
  title.id = 'talk-title';
  const panel = document.createElement('section');
  panel.id = 'talk-panel';
  panel.className = 'talk-panel';
  panel.setAttribute('aria-labelledby', 'talk-title');
  const contacts = document.createElement('div');
  contacts.className = 'talk-contacts';
  contacts.setAttribute('aria-label', 'Contact status');
  const facts = document.createElement('dl');
  facts.className = 'talk-facts';
  facts.setAttribute('aria-label', 'Facts heard');
  facts.hidden = true;
  const log = document.createElement('ol');
  log.className = 'talk-log';
  log.setAttribute('aria-label', 'Transcript');
  log.setAttribute('aria-live', 'polite');
  const empty = text('p', 'No casualty contact yet', 'talk-empty');
  panel.append(contacts, facts, empty, log);
  setupSpeak(panel);
  // Above the reasoning log: talk is what the operator reads first when a casualty is found.
  const before = Array.from(host.querySelectorAll('h2')).find(h => h.textContent === 'Reasoning log') ?? null;
  host.insertBefore(title, before);
  host.insertBefore(panel, before);

  let current = '';                                   // the casualty a `say` to the casualty is aimed at
  const status = new Map<string, Data>();             // casualty id -> latest casualty/contact
  const asks = new Map<string, HTMLElement>();        // gate id -> its transcript line

  function add(kind: string, meta: string, body: string, extra?: (node: HTMLElement) => void): HTMLElement {
    const line = document.createElement('li');
    line.className = `talk-line ${kind}`;
    line.append(text('small', meta), text('span', body, 'talk-text'));
    extra?.(line);
    empty.hidden = true;
    const stick = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
    log.append(line);
    while (log.children.length > TALK_LIMIT) log.firstElementChild?.remove();
    if (stick) log.scrollTop = log.scrollHeight;
    return line;
  }
  function stamp(t: unknown): string {
    const n = Number(t);
    return Number.isFinite(n) ? `${n.toFixed(1)}s · ` : '';
  }
  function renderContacts(): void {
    contacts.replaceChildren();
    for (const [id, data] of status) {
      const chip = document.createElement('span');
      chip.className = 'talk-contact';
      chip.dataset.casualty = id;
      const state = String(data.status ?? 'talking');
      chip.append(text('b', id), text('span', state, `talk-status ${state}`));
      if (data.turns !== undefined) chip.append(text('small', `turn ${data.turns}/${data.max_turns ?? '?'}`));
      contacts.append(chip);
    }
    const latest = status.get(current) ?? Array.from(status.values()).pop();
    facts.replaceChildren();
    const entries = Object.entries(object(latest?.facts));
    const injuries = Array.isArray(latest?.injuries) ? latest!.injuries as unknown[] : [];
    for (const [key, value] of entries) facts.append(text('dt', factLabel(key)), text('dd', factValue(value)));
    if (injuries.length) facts.append(text('dt', 'Injuries'), text('dd', factValue(injuries)));
    facts.hidden = !facts.children.length;
    if (!facts.hidden) facts.setAttribute('aria-label', `Facts heard from ${latest?.id ?? 'casualty'}`);
  }

  on('say', value => {
    const data = object(value);
    const to = String(data.to ?? 'casualty');
    const who = to === 'casualty' ? (current || 'casualty') : to;
    add('robot', `Robot → ${who}`, String(data.text ?? ''), line => {
      if (data.intent) line.querySelector('small')?.append(text('span', String(data.intent).replace(/_/g, ' '), 'talk-tag'));
    });
  });
  on('casualty/reply', value => {
    const data = object(value);
    if (data.id) current = String(data.id);
    add('casualty', `${stamp(data.t)}${data.id ?? 'casualty'} → robot`, String(data.text ?? ''), line => {
      const meta = line.querySelector('small')!;
      if (data.source) meta.append(text('span', String(data.source), 'talk-tag'));
      const level = Number(data.level);
      if (Number.isFinite(level)) {
        const bar = text('span', '', 'talk-level');
        bar.setAttribute('role', 'meter');
        bar.setAttribute('aria-label', 'Voice level');
        bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '1');
        bar.setAttribute('aria-valuenow', String(level));
        const fill = document.createElement('span');
        fill.style.width = `${Math.round(Math.max(0, Math.min(1, level)) * 100)}%`;
        bar.append(fill);
        meta.append(bar);
      }
    });
  });
  on('casualty/contact', value => {
    const data = object(value);
    if (!data.id) return;
    current = String(data.id);
    status.set(current, data);
    empty.hidden = true;
    renderContacts();
  });
  on('gate/request', value => {
    const data = object(value);
    if (typeof data.id !== 'string' || asks.has(data.id)) return;
    const route = data.route && data.route !== 'none' ? ` · route ${data.route}` : '';
    const line = add('ask', `Ask operator · ${data.id} · ${String(data.kind ?? 'gate').replace(/_/g, ' ')}${route}`,
      String(data.summary ?? ''), node => node.append(text('span', 'pending', 'talk-tag talk-answer')));
    badges(line, data);
    asks.set(data.id, line);
  });
  on('gate/answer', value => {
    const data = object(value);
    const line = asks.get(String(data.id));
    if (!line) return;
    const approved = data.approved === true;
    line.classList.add(approved ? 'approved' : 'rejected');
    const tag = line.querySelector('.talk-answer');
    if (tag) tag.textContent = `${approved ? 'approved' : 'rejected'}${data.by ? ' by ' + data.by : ''}`;
  });
}

export function setupPanels(): void {
  setupTalkPanel();
  const fake = new URLSearchParams(location.search).get('fake') === '1';
  el('mode-label').textContent = fake ? 'FAKE MODE · fixture replay' : 'LIVE HUB';
  el('connection-status').textContent = fake ? 'Fixture replay' : 'Connecting…';
  let online: boolean | undefined;
  on('console/connection', value => {
    el('connection-status').textContent = object(value).online ? 'Hub connected' : 'Hub disconnected · reconnecting';
  });
  on('status/link', value => {
    online = Boolean(object(value).online);
    el('link-status').textContent = online ? 'Online' : 'Offline';
    el('link-status').className = online ? 'online pill' : 'offline pill';
  });
  window.addEventListener('keydown', event => {
    const target = event.target as HTMLElement;
    if (event.key.toLowerCase() !== 'o' || event.repeat || event.ctrlKey || event.metaKey || event.altKey ||
        target.closest('input,textarea,select,[contenteditable="true"]') || online === undefined) return;
    event.preventDefault();
    if (!send('status/link', { online: !online })) el('send-status').textContent = 'Link toggle failed: hub disconnected';
  });
  on('status/gemini', value => {
    const data = object(value);
    el('gemini-status').textContent = `GEMINI: ${String(data.mode ?? 'unknown').toUpperCase()}`;
    el('gemini-status').title = `Stand-ins: ${(data.stand_ins ?? []).join(', ') || 'none'} · Calls/hour: ${data.calls_last_hour ?? 0}`;
  });
  on('status/budget', value => {
    const data = object(value), limits = object(data.limit), panel = el('budget-panel');
    panel.replaceChildren(text('small', `${data.device} · ${data.model}`));
    for (const [key, label, unit] of [['mem_mb', 'Memory', 'MB'], ['ms_per_step', 'Step', 'ms']]) {
      const used = Number(data[key]), limit = Number(limits[key]);
      const row = text('div', `${label}: ${used} ${unit} / ${limit > 0 ? limit + ' ' + unit : 'limit unset'}`);
      if (limit > 0) {
        const meter = document.createElement('progress');
        meter.max = limit; meter.value = Math.min(used, limit);
        meter.setAttribute('aria-label', label);
        row.append(meter);
        if (used > limit) { row.className = 'over-budget'; row.append(text('strong', ' OVER LIMIT')); }
      }
      panel.append(row);
    }
    badges(panel, data);
  });
  on('log/decision', value => {
    const data = object(value), item = document.createElement('li');
    item.className = ['act', 'relook', 'refer'].includes(data.outcome) ? data.outcome : '';
    item.append(text('small', `${Number(data.t).toFixed(1)}s · ${data.model} · ${data.outcome}`), text('div', data.reason));
    item.title = `Perception: ${data.perception}\nPhysics: ${data.physics}`;
    badges(item, data);
    el('reasoning-log').prepend(item);
    while (el('reasoning-log').children.length > 200) el('reasoning-log').lastElementChild?.remove();
  });
  on('gate/decision', value => {
    const data = object(value), panel = el('confidence-panel');
    const confidence = Math.max(0, Math.min(1, Number(data.confidence) || 0));
    const meter = document.createElement('progress'); meter.max = 1; meter.value = confidence;
    meter.setAttribute('aria-label', 'Decision confidence');
    panel.replaceChildren(text('div', `${data.outcome} · ${Math.round(confidence * 100)}%`), meter, text('p', data.reason));
    badges(panel, data);
  });
  // L1: Proof-carrying move permit & evidence panel
  on('permit/route', value => {
    const data = object(value);
    const panel = el('permit-panel');
    if (!panel) return;
    panel.replaceChildren();

    const header = document.createElement('div');
    header.className = 'permit-header';
    const granted = Boolean(data.granted);
    header.append(
      text('strong', `Route ${data.route ?? 'unknown'}`, 'permit-route-label'),
      text('span', granted ? 'GRANTED' : 'REVOKED', `permit-status ${granted ? 'granted' : 'revoked'}`),
      text('small', `t = ${Number(data.t || 0).toFixed(1)}s`, 'permit-time')
    );
    panel.append(header);

    if (data.reason) {
      panel.append(text('p', String(data.reason), 'permit-reason'));
    }

    const evidence = Array.isArray(data.evidence) ? data.evidence : [];
    if (evidence.length > 0) {
      panel.append(text('div', `Proof Evidence (${evidence.length})`, 'evidence-title'));
      const ul = document.createElement('ul');
      ul.className = 'evidence-list';
      for (const item of evidence) {
        const ev = object(item);
        const li = document.createElement('li');
        li.className = `evidence-item kind-${ev.kind}`;
        li.append(
          text('span', String(ev.kind ?? '').replace('_', ' '), `evidence-kind ${ev.kind}`),
          text('span', String(ev.detail ?? ''), 'evidence-detail'),
          text('small', `${Number(ev.t || 0).toFixed(1)}s`, 'evidence-time')
        );
        ul.append(li);
      }
      panel.append(ul);
    }
    badges(panel, data);
  });
  function submit(): void {
    const input = el<HTMLInputElement>('operator-command'), command = input.value.trim();
    if (!command) return;
    const ok = send('operator/command', { text: command, source: 'typed' });
    el('send-status').textContent = ok ? 'Command sent' : 'Not sent: hub disconnected';
    if (ok) input.value = '';
  }
  el('send-command').addEventListener('click', submit);
  el('operator-command').addEventListener('keydown', event => { if (event.key === 'Enter') submit(); });
  const approval = el<HTMLDialogElement>('approval-dialog');
  const pending = new Map<string, Data>();
  const answered = new Set<string>();
  function showRequest(): void {
    const data = pending.values().next().value as Data | undefined;
    if (!data) { approval.close(); return; }
    el('approval-summary').replaceChildren(text('span', data.summary)); badges(el('approval-summary'), data);
    el('approval-meta').textContent = `${data.id} · ${data.kind} · route ${data.route ?? 'none'} · ${pending.size} pending`;
    el('approval-error').textContent = '';
    if (!approval.open) approval.showModal();
  }
  on('gate/request', value => {
    const data = object(value);
    if (typeof data.id !== 'string' || answered.has(data.id)) return;
    pending.set(data.id, data); showRequest();
  });
  function answer(approved: boolean): void {
    const id = pending.keys().next().value;
    if (!id) return;
    if (!send('gate/answer', { id, approved, by: 'operator' })) {
      el('approval-error').textContent = 'Not sent: hub disconnected. Request remains pending.'; return;
    }
    answered.add(id); pending.delete(id); showRequest();
  }
  el('approve').addEventListener('click', () => answer(true));
  el('reject').addEventListener('click', () => answer(false));
  approval.addEventListener('cancel', event => { event.preventDefault(); answer(false); });
  on('gate/answer', value => {
    const id = object(value).id; answered.add(id); pending.delete(id); showRequest();
  });
  const report = el<HTMLDialogElement>('report-dialog');
  let reportData: Data = {};
  function renderReport(): void {
    const panel = el('report-content');
    // Render Markdown as safe text: model-generated HTML is never inserted into the DOM.
    panel.replaceChildren();
    for (const line of String(reportData.markdown ?? 'Awaiting handover report.').split('\n')) {
      const heading = /^(#{1,6})\s+(.+)$/.exec(line);
      panel.append(text(heading ? `h${heading[1].length}` : 'p', heading ? heading[2] : line));
    }
    badges(panel, reportData);
  }
  on('report/handover', value => { reportData = object(value); renderReport(); });
  el('show-report').addEventListener('click', () => { renderReport(); report.showModal(); });
  el('close-report').addEventListener('click', () => report.close());
}
