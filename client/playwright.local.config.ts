import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e-live",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 10 * 60 * 1000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    actionTimeout: 30_000,
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
});
