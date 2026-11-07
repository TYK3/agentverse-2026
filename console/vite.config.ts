import { defineConfig, type Plugin } from 'vite';
import { existsSync, mkdirSync, readdirSync, copyFileSync, writeFileSync } from 'node:fs';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const projectDir = dirname(fileURLToPath(import.meta.url));

function fixtures(): Plugin {
  return {
    name: 'aftershock-fixtures',
    buildStart() {
      const source = resolve(projectDir, '../coord/fixtures');
      const target = resolve(projectDir, 'public/fixtures');
      mkdirSync(target, { recursive: true });
      const names = existsSync(source) ? readdirSync(source).filter(name => /^[\w.-]+\.json$/.test(name)) : [];
      for (const name of names) copyFileSync(join(source, name), join(target, name));
      writeFileSync(join(target, 'manifest.json'), JSON.stringify(names, null, 2));
    }
  };
}
export default defineConfig({ plugins: [fixtures()] });
