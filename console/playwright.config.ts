import { defineConfig } from '@playwright/test';
export default defineConfig({
  // each worker runs software WebGL; more workers than this starve the page and the dev server
  workers: 2,
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:5173', launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } },
  webServer: { command: 'npm run dev -- --host 127.0.0.1 --port 5173', url: 'http://127.0.0.1:5173', reuseExistingServer: true },
});
