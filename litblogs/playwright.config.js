import { defineConfig, devices } from '@playwright/test';

const frontendPort = Number.parseInt(process.env.E2E_FRONTEND_PORT || '4173', 10);

export default defineConfig({
  testDir: './e2e/specs',
  globalSetup: './e2e/global-setup.mjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [
    ['./e2e/support/sanitized-reporter.mjs', {
      outputDirectory: 'test-results/e2e/sanitized-failures',
    }],
  ],
  outputDir: 'test-results/e2e',
  preserveOutput: 'failures-only',
  use: {
    baseURL: `http://127.0.0.1:${frontendPort}`,
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    screenshot: 'off',
    trace: 'off',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        browserName: 'chromium',
      },
    },
  ],
});
