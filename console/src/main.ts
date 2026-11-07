import './style.css';
import * as THREE from 'three';
import { connect, on, send } from './bus';

const canvas = document.querySelector<HTMLCanvasElement>('#map-canvas')!;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101a29);
const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
camera.position.set(3, 3, 5);
camera.lookAt(0, 0, 0);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
scene.add(new THREE.GridHelper(6, 12, 0x46627e, 0x29384c));
scene.add(new THREE.AxesHelper(0.8));
function resize(): void {
  const width = canvas.clientWidth || 1, height = canvas.clientHeight || 1;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas);
function frame(): void { renderer.render(scene, camera); requestAnimationFrame(frame); }
resize(); frame();

const connection = document.querySelector<HTMLElement>('#connection-status')!;
const log = document.querySelector<HTMLOListElement>('#reasoning-log')!;
const mode = new URLSearchParams(location.search).get('fake') === '1';
document.querySelector<HTMLElement>('#mode-label')!.textContent = mode ? 'FAKE MODE · fixture replay' : 'LIVE HUB';
connection.textContent = mode ? 'Fixture replay' : 'Connecting…';
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
const input = document.querySelector<HTMLInputElement>('#operator-command')!;
function submit(): void {
  const text = input.value.trim();
  if (text && send('operator/command', { text, source: 'typed' })) input.value = '';
}
document.querySelector<HTMLButtonElement>('#send-command')!.addEventListener('click', submit);
input.addEventListener('keydown', event => { if (event.key === 'Enter') submit(); });
connect();
