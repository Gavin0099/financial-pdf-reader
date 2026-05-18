import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.UI_BASE_URL || 'http://127.0.0.1:8080';
const webServerCommand =
  process.env.UI_SERVER_COMMAND ||
  (process.platform === 'win32' ? 'py -m http.server 8080' : 'python3 -m http.server 8080');

export default defineConfig({
  testDir: './tests/ui',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: webServerCommand,
    url: baseURL,
    // CI workflow may start a static server in a separate step.
    // Reuse if one already exists to avoid EADDRINUSE on 8080.
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
