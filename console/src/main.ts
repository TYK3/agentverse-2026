import './style.css';
import { connect, on } from './bus';
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

const searchParams = new URLSearchParams(window.location.search);
const isFakeMode = searchParams.get('fake') === '1';
const isBenchmarkMode = searchParams.has('benchmark');
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

import { setupPanels } from './panels';
setupPanels();

// Initial boot
if (isFakeMode) {
  // Populate the backup building demo scene immediately so the coloured map, casualty and hazards are visible
  mapViewer.loadBackupSceneDemo();
}

if (isBenchmarkMode) {
  mapViewer.generate100kBenchmark();
}

connect();
