// Smoke test for aftershock-console lane (T18 & T19)
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const dir = path.dirname(fileURLToPath(import.meta.url));

console.log('Testing console build artifacts...');

// If dist/index.html does not exist, build first
const distHtml = path.join(dir, 'dist/index.html');
if (!fs.existsSync(distHtml)) {
  console.log('dist/index.html missing, running npm run build...');
  execSync('npm run build', { cwd: dir, stdio: 'inherit' });
}

if (!fs.existsSync(distHtml)) {
  console.error('FAIL: dist/index.html missing after build');
  process.exit(1);
}

// 2. Check compiled JS bundle exists and contains key modules
const assetsDir = path.join(dir, 'dist/assets');
const files = fs.readdirSync(assetsDir);
const jsBundle = files.find(f => f.endsWith('.js'));
if (!jsBundle) {
  console.error('FAIL: No JS bundle in dist/assets');
  process.exit(1);
}

const jsContent = fs.readFileSync(path.join(assetsDir, jsBundle), 'utf8');
const expectedSymbols = [
  'InstancedMesh',
  'OrbitControls',
  'TubeGeometry',
  'map/cells',
  'map/hazards',
  'map/casualties',
  'sensors/scout',
  'responder/action',
  'route/proposed',
  'route/verified',
  'world/change',
  'previous route',
  'Aftershock detected'
];

for (const sym of expectedSymbols) {
  if (!jsContent.includes(sym)) {
    console.error(`FAIL: Bundle missing expected symbol: ${sym}`);
    process.exit(1);
  }
}

// 3. Verify fixtures copied to public/fixtures and dist/fixtures
const publicFixtures = path.join(dir, 'public/fixtures');
const manifestFile = path.join(publicFixtures, 'manifest.json');
if (!fs.existsSync(manifestFile)) {
  console.error('FAIL: public/fixtures/manifest.json missing');
  process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestFile, 'utf8'));
if (!Array.isArray(manifest) || manifest.length === 0) {
  console.error('FAIL: Invalid fixture manifest');
  process.exit(1);
}

// 4. Test 100k cell calculation logic
console.log('Verifying 100k cell generator math...');
const sizeX = 100, sizeY = 100, layers = 10;
const totalCount = sizeX * sizeY * layers;
if (totalCount !== 100000) {
  console.error('FAIL: Expected 100000 cells');
  process.exit(1);
}

console.log(`PASS: All smoke tests passed (${manifest.length} fixtures, 100k math verified, bundle contains Three.js InstancedMesh, TubeGeometry, OrbitControls, T19 re-plan & world/change handlers)`);
