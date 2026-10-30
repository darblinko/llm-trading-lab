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
  // Servers start in order, so the backend below serves the dist/ built by the first command.
  webServer: [
    {
      command: 'npm run build && npm exec -- vite preview --host 127.0.0.1 --port 4174 --strictPort',
      // Wait for Vite to bind; probing an unused port can hang on filtered loopback networks.
      wait: { stdout: /Local:\s+http:\/\/127\.0\.0\.1:4174\// },
      reuseExistingServer: false,
      timeout: 60000,
    },
    {
      // The real backend on the committed synthetic sample session (tests/backend.spec.ts).
      command: 'uv run --project .. python ../run.py --offline --as-of 2026-01-07 --host 127.0.0.1 --port 4175',
      wait: { stderr: /Uvicorn running on http:\/\/127\.0\.0\.1:4175/ },
      reuseExistingServer: false,
      timeout: 120000,
    },
    {
      // The static review app in apps/claude-review-app on the same sample (tests/staticApp.spec.ts).
      command: 'uv run --project ../../claude-review-app python ../../claude-review-app/run_review_app.py --port 4176',
      wait: { stderr: /Serving .* on http:\/\/127\.0\.0\.1:4176/ },
      reuseExistingServer: false,
      timeout: 120000,
    },
  ],
});
