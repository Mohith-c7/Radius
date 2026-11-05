import { defineConfig } from "@playwright/test";

// The stack is started outside Playwright (stack.yml / `make dev`). The base URL must use
// `localhost`, not 127.0.0.1: the API session cookie is host-scoped and the dashboard talks to
// http://localhost:8000, so a different host name would make the cookie cross-site.
export default defineConfig({
  testDir: "./tests",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: {
    browserName: "chromium",
    // Local convenience only (CI uses the Playwright-managed Chromium): E2E_CHROME_PATH=/path/to/chrome
    launchOptions: process.env.E2E_CHROME_PATH ? { executablePath: process.env.E2E_CHROME_PATH } : {},
  } }],
});
