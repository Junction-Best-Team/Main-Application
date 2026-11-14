import { defineConfig } from "@playwright/test";

const integration = process.env.AIMO_INTEGRATION === "1";
const baseURL =
  process.env.BASE_URL ||
  (integration ? "http://localhost:8000" : "http://127.0.0.1:5173");

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: { baseURL, viewport: { width: 1440, height: 1000 } },
  webServer:
    !integration && !process.env.BASE_URL
      ? {
          command: "npm run dev -- --port 5173 --strictPort",
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 30_000,
        }
      : undefined,
  reporter: "list",
  outputDir: "test-results",
});
