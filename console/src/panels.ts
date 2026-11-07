import { on, send } from './bus';

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
export function setupPanels(): void {
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
