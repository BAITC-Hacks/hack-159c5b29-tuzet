import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:8765", browserName: "chromium", headless: true },
  webServer: {
    command: "PYTHONPATH=../src ../.venv/bin/python -m money_graph.cli serve --artifacts ../artifacts/latest --port 8765",
    url: "http://127.0.0.1:8765/api/health",
    timeout: 30_000,
    reuseExistingServer: !process.env.CI,
  },
});
