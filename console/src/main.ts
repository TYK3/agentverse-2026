import './style.css';
import * as THREE from 'three';
import { connect } from './bus';

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

import { setupPanels } from './panels';
setupPanels();
connect();
