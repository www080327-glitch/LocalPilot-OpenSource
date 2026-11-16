import config from "../../../../playwright.config";
export default {
  ...config,
  testDir: "../../../../tests/ui",
  use: { ...config.use, baseURL: "http://127.0.0.1:1437" },
  webServer: {
    command: "npm run dev -- --port 1437 --strictPort",
    cwd: "/workspace/scratch/2a488f6eabf5/LocalPilot-polish-final-20261116/desktop",
    url: "http://127.0.0.1:1437",
    reuseExistingServer: false,
  },
};
