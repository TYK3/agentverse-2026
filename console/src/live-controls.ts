// LIVE-UI-2: "Trigger Slab Shift" drops the sim's spare rubble block onto the Responder's route,
// through the hub's POST /inject (sim/inject.py, T05). The sim publishes world/change
// kind "block_added" once it has landed; the permit, re-look and re-plan then arrive over the bus.
// Approve and hold are the approval dialog's Approve / Reject buttons, which already send
// gate/answer {id, approved, by: "operator"} over the hub WebSocket (panels.ts).
import { on } from './bus';

export const HUB_INJECT_URL = 'http://localhost:8000/inject';
const AHEAD_M = 0.5;   // same rule as tools/demo60.py shift_cell: first route cell >= 0.5 m ahead
const DROP_Z = 0.3;    // same drop height as sim World.inject(cell)
const GOAL_CELLS = 3;  // never the last 3 cells (the goal)

type Cell = [number, number, number?];
type Route = { id: string; robot?: string; cells: Cell[] };

/** The point to drop the block: the first route cell at least `ahead` m past the cell nearest the
 *  Responder, never one of the last 3 (the goal). Null when the route is too short. */
export function slabShiftPoint(cells: Cell[], responderXY: [number, number] | null, res = 0.05,
  ahead = AHEAD_M): [number, number, number] | null {
  if (!cells.length) return null;
  const centre = cells.map(c => [(c[0] + 0.5) * res, (c[1] + 0.5) * res] as [number, number]);
  const from = responderXY ?? centre[0];
  let near = 0;
  centre.forEach((p, n) => {
    if (Math.hypot(p[0] - from[0], p[1] - from[1]) < Math.hypot(centre[near][0] - from[0], centre[near][1] - from[1])) near = n;
  });
  let run = 0;
  for (let n = near + 1; n < cells.length - GOAL_CELLS; n++) {
    run += Math.hypot(centre[n][0] - centre[n - 1][0], centre[n][1] - centre[n - 1][1]);
    if (run >= ahead) return [round(centre[n][0]), round(centre[n][1]), DROP_Z];
  }
  return null;
}

function round(v: number): number { return Math.round(v * 1000) / 1000; }

export function setupLiveControls(): void {
  const fake = new URLSearchParams(window.location.search).get('fake') === '1';
  const routes = new Map<string, Route>();
  let lastResponderRoute: Route | null = null;
  let pose: { pos: number[]; route: string | null } | null = null;
  let res = 0.05;

  on('map/cells', data => { const r = (data as { res?: unknown })?.res; if (typeof r === 'number' && r > 0) res = r; });
  on('route/proposed', data => {
    const route = data as Route;
    if (!route || typeof route.id !== 'string' || !Array.isArray(route.cells)) return;
    routes.set(route.id, route);
    if (!route.robot || route.robot === 'responder') lastResponderRoute = route;
  });
  on('responder/pose', data => {
    const p = data as { pos?: unknown; route?: unknown };
    if (Array.isArray(p?.pos)) pose = { pos: p.pos as number[], route: typeof p.route === 'string' ? p.route : null };
  });

  const anchor = document.querySelector<HTMLButtonElement>('#btn-demo-replan');
  if (!anchor || document.querySelector('#btn-slab-shift')) return;
  const button = document.createElement('button');
  button.id = 'btn-slab-shift';
  button.type = 'button';
  button.className = 'btn-sm';
  button.title = 'Drop the spare rubble block on the Responder route in the live sim';
  button.textContent = 'Trigger Slab Shift';
  const status = document.createElement('span');
  status.id = 'live-control-status';
  status.setAttribute('role', 'status');
  anchor.after(button, status);

  const say = (text: string): void => { status.textContent = text; };

  button.addEventListener('click', () => {
    if (fake) { say('Fake mode: no live sim to shift'); return; }
    const route = (pose?.route && routes.get(pose.route)) || lastResponderRoute;
    if (!route) { say('No Responder route yet'); return; }
    const xy = pose ? [pose.pos[0], pose.pos[1]] as [number, number] : null;
    const pos = slabShiftPoint(route.cells, xy, res);
    if (!pos) { say(`Route ${route.id} too short to shift`); return; }
    button.disabled = true;
    say(`Shifting on ${route.id}…`);
    fetch(HUB_INJECT_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind: 'block_added', pos })
    }).then(async response => {
      const body = await response.json().catch(() => ({})) as { block?: string; error?: string };
      if (response.ok) say(`Slab shift: ${body.block ?? 'block'} dropping on ${route.id}`);
      else if (response.status === 503) say('No live sim on the hub');
      else say(`Not shifted: ${body.error ?? response.status}`);
    }).catch(() => say('Not shifted: hub unreachable')).finally(() => { button.disabled = false; });
  });
}
