import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.APP_URL || "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [["list"], ["html", { open: "never" }]],
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1050 },
      },
    },
    {
      name: "firefox",
      use: {
        ...devices["Desktop Firefox"],
        viewport: { width: 1440, height: 1050 },
      },
    },
    ...(existsSync(
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    )
      ? [
          {
            name: "edge",
            use: {
              ...devices["Desktop Edge"],
              channel: "msedge",
              viewport: { width: 1440, height: 1050 },
            },
          },
        ]
      : []),
  ],
});
