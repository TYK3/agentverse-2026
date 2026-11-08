import { defineConfig, type Plugin } from 'vite';
import { existsSync, mkdirSync, readdirSync, copyFileSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const projectDir = dirname(fileURLToPath(import.meta.url));

function parseSummary(text: string) {
  const lines = text.split(/\r?\n/);
  const rows: Array<{ property: string; scout: string; responder: string }> = [];
  let inSummary = false;
  let passedHeader = 0;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('## Summary')) {
      inSummary = true;
      passedHeader = 0;
      continue;
    }
    if (inSummary) {
      if (trimmed.startsWith('## ') && !trimmed.startsWith('## Summary')) break;
      if (!trimmed.startsWith('|')) continue;
      const cols = trimmed.split('|').map(c => c.trim()).filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      if (cols.length >= 3) {
        if (passedHeader < 2) {
          passedHeader++;
          continue;
        }
        rows.push({ property: cols[0], scout: cols[1], responder: cols[2] });
      }
    }
  }
  return rows;
}

function fixtures(): Plugin {
  return {
    name: 'aftershock-fixtures',
    configResolved() {
      const source = resolve(projectDir, '../coord/fixtures');
      const target = resolve(projectDir, 'public/fixtures');
      mkdirSync(target, { recursive: true });
      const names = existsSync(source) ? readdirSync(source).filter(name => /^[\w.-]+\.json$/.test(name)).sort() : [];
      for (const name of names) copyFileSync(join(source, name), join(target, name));
      const demo = resolve(projectDir, 'fixtures/panels.json');
      if (existsSync(demo)) { copyFileSync(demo, join(target, 'panels.json')); names.push('panels.json'); }

      // Y7c: Parse docs/hardware.md into hardware.json and copy hardware.md (asset, not a bus envelope)
      const hwDoc = resolve(projectDir, '../docs/hardware.md');
      if (existsSync(hwDoc)) {
        copyFileSync(hwDoc, join(target, 'hardware.md'));
        const text = readFileSync(hwDoc, 'utf8');
        const summaryRows = parseSummary(text);
        writeFileSync(join(target, 'hardware.json'), JSON.stringify(summaryRows, null, 2));
      }

      writeFileSync(join(target, 'manifest.json'), JSON.stringify(names, null, 2));
    }
  };
}
export default defineConfig({ plugins: [fixtures()] });
