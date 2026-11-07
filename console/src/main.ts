import './style.css';
import { connect, on, send } from './bus';
import {
  MapViewer,
  type MapCellsPayload,
  type HazardRecord,
  type CasualtyRecord,
  type ScoutSensorsPayload,
  type ResponderActionPayload,
  type RouteProposedPayload
} from './map';

const canvas = document.querySelector<HTMLCanvasElement>('#map-canvas')!;
const mapViewer = new MapViewer(canvas);

const fpsBadge = document.querySelector<HTMLElement>('#fps-badge');
const cellCountBadge = document.querySelector<HTMLElement>('#cell-count-badge');
mapViewer.setHudElements(fpsBadge, cellCountBadge);

// UI Button actions
document.querySelector<HTMLButtonElement>('#btn-demo-scene')?.addEventListener('click', () => {
  mapViewer.loadBackupSceneDemo();
});

document.querySelector<HTMLButtonElement>('#btn-benchmark-100k')?.addEventListener('click', () => {
  mapViewer.generate100kBenchmark();
});

const connection = document.querySelector<HTMLElement>('#connection-status')!;
const log = document.querySelector<HTMLOListElement>('#reasoning-log')!;

const searchParams = new URLSearchParams(window.location.search);
const isFakeMode = searchParams.get('fake') === '1';
const isBenchmarkMode = searchParams.has('benchmark');

document.querySelector<HTMLElement>('#mode-label')!.textContent = isFakeMode
  ? 'FAKE MODE · fixture replay'
  : 'LIVE HUB';
connection.textContent = isFakeMode ? 'Fixture replay' : 'Connecting…';

// 3D Map Event Subscriptions
on('map/cells', data => {
  mapViewer.updateCells(data as MapCellsPayload);
});

on('map/hazards', data => {
  mapViewer.updateHazards(data as HazardRecord[]);
});

on('map/casualties', data => {
  mapViewer.updateCasualties(data as CasualtyRecord[]);
});

on('sensors/scout', data => {
  mapViewer.updateScoutPose(data as ScoutSensorsPayload);
});

on('responder/action', data => {
  mapViewer.updateResponderAction(data as ResponderActionPayload);
});

on('route/proposed', data => {
  mapViewer.updateRouteProposed(data as RouteProposedPayload);
});

// System Status and Reasoning Log
on('console/connection', data => {
  const online = Boolean((data as { online?: boolean })?.online);
  connection.textContent = online ? 'Online' : 'Offline · reconnecting';
});

on('*', data => {
  const event = data as { topic: string; data: unknown };
  if (event.topic === 'console/connection') return;
  const item = document.createElement('li');
  item.textContent = event.topic + ' · ' + JSON.stringify(event.data).slice(0, 180);
  log.prepend(item);
  while (log.children.length > 30) log.lastElementChild?.remove();
});

on('gate/decision', data => {
  document.querySelector<HTMLElement>('#confidence-panel')!.textContent = JSON.stringify(data);
});

// Operator Command Submission
const input = document.querySelector<HTMLInputElement>('#operator-command')!;
function submit(): void {
  const text = input.value.trim();
  if (text && send('operator/command', { text, source: 'typed' })) {
    input.value = '';
  }
}
document.querySelector<HTMLButtonElement>('#send-command')!.addEventListener('click', submit);
input.addEventListener('keydown', event => {
  if (event.key === 'Enter') submit();
});

// Initial boot
if (isFakeMode) {
  // Populate the backup building demo scene immediately so the coloured map, casualty and hazards are visible
  mapViewer.loadBackupSceneDemo();
}

if (isBenchmarkMode) {
  mapViewer.generate100kBenchmark();
}

connect();
