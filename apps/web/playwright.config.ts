import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import path from "node:path";

const root = path.resolve(__dirname, "../..");
const venvPython = [".venv/Scripts/python.exe", ".venv/bin/python"].map((p) => path.join(root, p)).find(existsSync);
const python = process.env.FORGEFLOW_PYTHON ?? venvPython ?? "python";
const apiPort = Number(process.env.FORGEFLOW_API_PORT ?? 8000);

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3000", trace: "retain-on-failure", screenshot: "only-on-failure",
    // PW_CHANNEL=msedge|chrome runs against an installed browser instead of the downloaded Chromium
    ...(process.env.PW_CHANNEL ? { channel: process.env.PW_CHANNEL } : {}),
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn forgeflow_api.main:create_app --factory --port ${apiPort}`,
      cwd: root,
      env: { FORGEFLOW_DATA_DIR: path.join(root, ".forgeflow-e2e") },
      url: `http://localhost:${apiPort}/health`,
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "npx next start -p 3000",
      cwd: __dirname,
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
