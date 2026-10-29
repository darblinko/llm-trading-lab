import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:4174',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run build && npm exec -- vite preview --host 127.0.0.1 --port 4174 --strictPort',
    // Wait for Vite to bind; probing an unused port can hang on filtered loopback networks.
    wait: { stdout: /Local:\s+http:\/\/127\.0\.0\.1:4174\// },
    reuseExistingServer: false,
    timeout: 60000,
  },
});
