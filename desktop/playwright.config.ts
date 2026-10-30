import { defineConfig } from "@playwright/test";
export default defineConfig({
  workers: 1,
  testDir: "tests/ui",
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1440, height: 940 },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:1420",
    reuseExistingServer: true,
  },
  reporter: [["list"], ["json", { outputFile: `${process.env.LP_UI_EVIDENCE_DIR || "docs/evidence/runs/" + Date.now()}/browser-tests.json` }]],
});
