import './style.css';
import { connect, on } from './bus';
import {
  MapViewer,
  type MapCellsPayload,
  type HazardRecord,
  type CasualtyRecord,
  type ScoutSensorsPayload,
  type ResponderActionPayload,
  type RouteProposedPayload,
  type RouteVerifiedPayload,
  type WorldChangePayload
} from './map';
import { setupInterior } from './interior';
import { setupPanels } from './panels';
import { setupHardwarePanel } from './hardware';

const canvas = document.querySelector<HTMLCanvasElement>('#map-canvas')!;
const mapViewer = new MapViewer(canvas);
(window as unknown as { aftershockMap: MapViewer }).aftershockMap = mapViewer;  // read by the browser tests

// Connect HUD and Banner elements
const fpsBadge = document.querySelector<HTMLElement>('#fps-badge');
const cellCountBadge = document.querySelector<HTMLElement>('#cell-count-badge');
mapViewer.setHudElements(fpsBadge, cellCountBadge);

const banner = document.querySelector<HTMLElement>('#world-change-banner');
const bannerText = document.querySelector<HTMLElement>('#banner-text');
const bannerIcon = document.querySelector<HTMLElement>('#banner-icon');
mapViewer.setBannerElements(banner, bannerText, bannerIcon);

// UI Button actions
document.querySelector<HTMLButtonElement>('#btn-demo-scene')?.addEventListener('click', () => {
  mapViewer.loadBackupSceneDemo();
});

document.querySelector<HTMLButtonElement>('#btn-demo-replan')?.addEventListener('click', () => {
  mapViewer.simulateAftershockAndReplan();
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

// Task T19: Route Proposed, Route Verified, and World Change
on('route/proposed', data => {
  mapViewer.updateRouteProposed(data as RouteProposedPayload);
});

on('route/verified', data => {
  mapViewer.onRouteVerified(data as RouteVerifiedPayload);
});

// Task L1: Move permission & proof evidence
on('permit/route', data => {
  mapViewer.onPermitRoute(data as any);
});

on('world/change', data => {
  const change = data as WorldChangePayload;
  mapViewer.onWorldChange(change);

  // In fake mode: when world/change arrives, simulate re-plan route arriving after re-scanning
  if (isFakeMode) {
    window.setTimeout(() => {
      mapViewer.updateRouteProposed({
        id: 'r4',
        robot: 'responder',
        cells: [
          [-16, -24, 0],
          [-13, -17, 0],
          [-4, -8, 0],
          [8, -4, 0],
          [20, 2, 0],
          [39, 20, 0]
        ],
        goal: 'deliver water to c1',
        reason: 'avoiding collapsed block b7 toward casualty c1',
        model: 'local-astar'
      });
    }, 1500);
  }
});

// Setup operator reasoning, approval and status panels (T20)
setupPanels();

// Setup robot hardware specification panel (Y7c)
setupHardwarePanel();

setupInterior(mapViewer);

// Initial boot
if (isFakeMode) {
  // Populate the backup building demo scene immediately so the coloured map, casualty, hazards and route are visible
  mapViewer.loadBackupSceneDemo();
}

if (isBenchmarkMode) {
  mapViewer.generate100kBenchmark();
}

connect();
