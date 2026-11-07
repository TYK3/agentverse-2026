import { defineConfig, type Plugin } from 'vite';
import { existsSync, mkdirSync, readdirSync, copyFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

function fixtures(): Plugin {
  return {
    name: 'aftershock-fixtures',
    buildStart() {
      const source = resolve(__dirname, '../coord/fixtures');
      const target = resolve(__dirname, 'public/fixtures');
      mkdirSync(target, { recursive: true });
      const names = existsSync(source) ? readdirSync(source).filter(name => /^[\w.-]+\.json$/.test(name)) : [];
      for (const name of names) copyFileSync(join(source, name), join(target, name));
      writeFileSync(join(target, 'manifest.json'), JSON.stringify(names, null, 2));
    }
  };
}
export default defineConfig({ plugins: [fixtures()] });
