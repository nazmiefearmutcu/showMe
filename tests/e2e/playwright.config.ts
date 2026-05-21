import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for the showMe Tauri shell.
 *
 * Two projects:
 *   - smoke: hermetic specs against `npm --workspace ui run preview` with
 *            sidecar HTTP stubbed via `page.route`. Suitable for CI on PRs.
 *            Wall-clock: < 60s.
 *   - audit: legacy data-driven 144-function spec; needs a real sidecar
 *            and is gated behind `workflow_dispatch`. Suitable for nightly
 *            runs against the live engine.
 *
 * TEST-03 P1: this config replaces Playwright's stock defaults so
 * developers get reporters, retries, screenshots-on-failure, and a
 * predictable `baseURL` instead of every spec rolling its own
 * fallbacks.
 */
const isCi = !!process.env.CI;
const previewPort = Number(process.env.SHOWME_E2E_PREVIEW_PORT ?? 4173);

export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  forbidOnly: isCi,
  retries: isCi ? 2 : 0,
  workers: 1,
  timeout: 60_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      // High threshold for now — the visual regression baseline is
      // intentionally not committed yet (TEST-03 P3 follow-up).
      maxDiffPixelRatio: 0.05,
    },
  },
  reporter: isCi
    ? [
        ["list"],
        ["html", { open: "never", outputFolder: "../../artifacts/playwright-report" }],
        ["junit", { outputFile: "../../artifacts/playwright-junit.xml" }],
      ]
    : [["list"]],
  use: {
    baseURL: process.env.SHOWME_APP_URL ?? `http://127.0.0.1:${previewPort}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "smoke",
      testMatch: ["smoke/**/*.spec.ts"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "audit",
      testMatch: ["showme-functions.spec.ts"],
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: process.env.PLAYWRIGHT_E2E_MODE === "smoke"
    ? {
        // S06 — chain `build:ui` into the smoke webServer so the suite always
        // exercises a fresh dist, not whatever stale artifacts happened to be
        // sitting in `ui/dist` from a previous run. CI also runs build:ui
        // explicitly (belt-and-suspenders), but this guarantees the local
        // `npm run test:e2e:smoke` flow is hermetic too. Opt out with
        // `SHOWME_E2E_SKIP_BUILD=1` if you're iterating on a spec and the
        // dist is already fresh.
        // `--host 127.0.0.1` is load-bearing: vite preview's default
        // listens on `localhost`, which resolves to ::1 on modern macOS;
        // Playwright probes the literal IPv4 URL below, so without the
        // explicit host the webServer health check times out at 180s
        // even though the server is live on the IPv6 socket.
        command:
          process.env.SHOWME_E2E_SKIP_BUILD === "1"
            ? `npm --workspace ui run preview -- --strictPort --host 127.0.0.1 --port ${previewPort}`
            : `npm run build:ui && npm --workspace ui run preview -- --strictPort --host 127.0.0.1 --port ${previewPort}`,
        url: `http://127.0.0.1:${previewPort}`,
        // Larger timeout: a cold UI build can take 30-45s on macOS runners
        // before the preview server starts listening.
        timeout: 180_000,
        reuseExistingServer: !isCi,
        cwd: "../..",
      }
    : undefined,
});
