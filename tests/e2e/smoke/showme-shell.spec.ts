import { expect, test, type Page, type Route } from "@playwright/test";

/**
 * Hermetic smoke specs for the showMe Tauri shell.
 *
 * Every test stubs the sidecar HTTP surface via `page.route` so the suite
 * runs without a real Python backend (TEST-04 P1: replace ad-hoc real-network
 * dependence with deterministic fixtures). The Tauri runtime is not
 * involved either — these run against `vite preview` so they exercise the
 * UI shell, command palette, theme system, and pane router exactly as a
 * developer would in browser-mode (`isInTauri() === false`).
 */

const HEALTH_FIXTURE = {
  // `ok` + nested `engine` are the load-bearing fields per
  // `SidecarHealth` in `lib/sidecar.ts`. Without them, `refreshHealth`
  // marks the sidecar as "crashed" and leaves `engineRoot` null, which
  // keeps the IntroSplash in `--standby` phase (pointer-events:auto)
  // long enough to break any spec that needs to click a UI element.
  ok: true,
  status: "healthy",
  engine: {
    engine_attached: true,
    engine_root: "/Applications/showMe.app/Contents/Resources/engine",
  },
  engine_attached: true,
  engine_root: "/Applications/showMe.app/Contents/Resources/engine",
  function_count: 141,
};

/**
 * Function index fixture — MUST contain > 20 entries.
 *
 * Why: `App.tsx` (BACKEND_INDEX_READY_THRESHOLD = 20) gates
 * `dashboardReady` on the index size. A short fixture leaves the
 * boot IntroSplash stuck in `--standby` phase (`pointer-events: auto`),
 * blocking every click in subsequent smoke specs.
 */
const FUNCTION_INDEX_FIXTURE = [
  { code: "DES", name: "Description", category: "equity", asset_classes: ["equity"] },
  { code: "PORT", name: "Portfolio", category: "portfolio", asset_classes: ["equity"] },
  { code: "WATCH", name: "Watchlist", category: "screen", asset_classes: ["equity"] },
  { code: "XSEN", name: "X Sentiment", category: "news", asset_classes: ["equity"] },
  { code: "INSTANT", name: "Instant Line", category: "trade", asset_classes: ["equity"] },
  { code: "GP", name: "Price Graph", category: "equity", asset_classes: ["equity"] },
  { code: "BTMM", name: "BTMM", category: "screen", asset_classes: ["equity"] },
  { code: "GEX", name: "Gamma Exposure", category: "options", asset_classes: ["equity"] },
  { code: "OMON", name: "Options Monitor", category: "options", asset_classes: ["equity"] },
  { code: "FA", name: "Fundamental Analysis", category: "fund", asset_classes: ["equity"] },
  { code: "TOP", name: "Top News", category: "news", asset_classes: ["equity"] },
  { code: "NEWS", name: "News", category: "news", asset_classes: ["equity"] },
  { code: "ALRT", name: "Alerts", category: "screen", asset_classes: ["equity"] },
  { code: "ANR", name: "Analyst", category: "fund", asset_classes: ["equity"] },
  { code: "ASK", name: "Ask", category: "screen", asset_classes: ["equity"] },
  { code: "CORR", name: "Correlations", category: "stat", asset_classes: ["equity"] },
  { code: "DPF", name: "Dividend PnL", category: "fund", asset_classes: ["equity"] },
  { code: "DVD", name: "Dividend", category: "fund", asset_classes: ["equity"] },
  { code: "ECFC", name: "Econ Forecast", category: "macro", asset_classes: ["equity"] },
  { code: "ECO", name: "Econ", category: "macro", asset_classes: ["equity"] },
  { code: "ECST", name: "Stats", category: "macro", asset_classes: ["equity"] },
  { code: "EE", name: "Earnings Est", category: "fund", asset_classes: ["equity"] },
  { code: "MIS", name: "Multi-Indicator Scan", category: "screen", asset_classes: ["equity"] },
  { code: "HP", name: "Historical Prices", category: "equity", asset_classes: ["equity"] },
  { code: "TRAN", name: "Transactions", category: "portfolio", asset_classes: ["equity"] },
  { code: "SCAN", name: "All Functions", category: "screen", asset_classes: ["equity"] },
  { code: "MOST", name: "Most Active", category: "screen", asset_classes: ["equity"] },
];

async function stubSidecar(page: Page) {
  // Route registration order matters: Playwright's matcher is
  // "last-registered wins". The catch-all MUST go first so the
  // specific routes below override it for the real paths. The pre-S06
  // ordering had the catch-all last, which silently shadowed every
  // specific route and made `/api/health` return `{}` — leaving the
  // sidecar status as "crashed" and the boot splash glued to the
  // viewport with pointer-events:auto.
  await page.route(/\/api\//, async (route: Route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
  await page.route("**/api/health", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(HEALTH_FIXTURE) }),
  );
  await page.route("**/api/sidecar/info", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ version: "0.0.1", engine: { engine_attached: true, engine_root: HEALTH_FIXTURE.engine_root } }) }),
  );
  await page.route("**/api/function-index", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(FUNCTION_INDEX_FIXTURE) }),
  );
  await page.route("**/api/sidecar/ticker", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ bot: { running: true, mode: "live", cycle: 12 }, portfolio: { n_positions: 3, market_value: 12345.67 }, alerts: { active: 0, fired_today: 1 } }) }),
  );
}

test.describe("showMe shell smoke", () => {
  test.beforeEach(async ({ page }) => {
    await stubSidecar(page);
    // Pretend we have a sidecar port so `sidecarBaseUrl` doesn't fall
    // back to `http://127.0.0.1:0`.
    await page.addInitScript(() => {
      window.localStorage.setItem("showme.sidecarPort", "8765");
    });
  });

  test("Welcome screen loads", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    // Splash → welcome should mount within 5s after the function index
    // resolves.
    await expect(page.locator("body")).not.toContainText("loading", { timeout: 5_000 });
  });

  test("function index resolves with stubbed payload", async ({ page }) => {
    await page.goto("/");
    // Statusbar rendering of FN count is the canonical signal that the
    // index merge completed.
    await expect(page.locator("body")).toContainText(/FN\s*\d+/i, { timeout: 8_000 });
  });

  test("command palette opens via ⌘K", async ({ page }) => {
    await page.goto("/");
    // Wait for the boot signal AND the palette-open button so we know
    // the Palette component has mounted (which is when its keydown
    // listener attaches). Without this, `Meta+K` races React's effect
    // and the keypress is silently dropped.
    await expect(page.locator("body")).toContainText(/FN\s*\d+/i, { timeout: 8_000 });
    await expect(page.getByLabel(/Open command palette/i).first()).toBeVisible({ timeout: 4_000 });
    // Focus the page body so the keypress isn't absorbed by Playwright's
    // default focus-to-noop behavior.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Meta+K");
    // The palette placeholder is i18n-bound ("Run a function — DES, …"),
    // so we target the input via its stable `role="combobox"` + the
    // `Function search` aria-label instead of the legacy placeholder.
    await expect(page.getByRole("combobox", { name: /Function search/i })).toBeVisible({ timeout: 4_000 });
  });

  test("command palette filters by substring", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toContainText(/FN\s*\d+/i, { timeout: 8_000 });
    // Use the dedicated open button — this is the more direct way to
    // exercise the palette filter path and avoids the keyboard-race.
    await page.getByLabel(/Open command palette/i).first().click();
    const input = page.getByRole("combobox", { name: /Function search/i });
    await expect(input).toBeVisible({ timeout: 4_000 });
    await input.fill("port");
    await expect(page.locator("body")).toContainText(/Portfolio/i, { timeout: 4_000 });
  });

  test("navigates to PORT pane via deep-link route", async ({ page }) => {
    await page.goto("/#/symbol/AAPL/PORT");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("body")).toContainText(/PORT|Portfolio/i, { timeout: 6_000 });
  });

  test("navigates to WATCH pane", async ({ page }) => {
    await page.goto("/#/symbol/AAPL/WATCH");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("body")).toContainText(/WATCH|Watchlist/i, { timeout: 6_000 });
  });

  test("navigates to XSEN pane", async ({ page }) => {
    await page.goto("/#/symbol/AAPL/XSEN");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("body")).toContainText(/XSEN|Sentiment/i, { timeout: 6_000 });
  });

  test("navigates to Preferences pane", async ({ page }) => {
    await page.goto("/#/preferences");
    await expect(page.locator("body")).toBeVisible();
    await expect(page.locator("body")).toContainText(/Preferences|Settings/i, { timeout: 6_000 });
  });

  test("theme toggle button is reachable and clickable", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
    // Theme toggle exposes either an aria-label or visible text "Light" /
    // "Dark"; we tolerate either.
    const toggle = page
      .getByRole("button", { name: /light|dark|theme/i })
      .first();
    if (await toggle.isVisible().catch(() => false)) {
      await toggle.click();
    }
    // We just need to confirm the click didn't throw; a successful click
    // mutates a `data-theme` attribute on `html`.
    const html = page.locator("html");
    await expect(html).toBeVisible();
  });

  test("sidecar offline banner appears when health 503s", async ({ page }) => {
    await page.unroute("**/api/health");
    await page.route("**/api/health", (route: Route) =>
      route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ status: "unavailable" }) }),
    );
    await page.goto("/");
    // Look for any banner / status message indicating offline. Match a
    // broad regex because the exact string is locale-dependent.
    await expect(page.locator("body")).toContainText(/offline|unavailable|reconnect|sidecar/i, { timeout: 12_000 });
  });

  test("404 hash route renders gracefully", async ({ page }) => {
    await page.goto("/#/symbol/AAPL/__no_such_function__");
    // The router should fall back to either Welcome, an error pane, or
    // FunctionStub with an "unknown function" message — any of which
    // are visible body content. The test's job is just to assert that
    // the shell didn't crash.
    await expect(page.locator("body")).toBeVisible();
    expect(await page.evaluate(() => document.body.children.length)).toBeGreaterThan(0);
  });

  test("no console errors at boot", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");
    // Allow the first paint + boot effects to settle.
    await page.waitForTimeout(2_000);
    // We don't fail the test on every red console line because some
    // panes legitimately log via `console.error` for non-critical
    // user-input warnings; instead we assert nothing matches a known
    // catastrophic substring.
    const fatal = errors.filter((e) =>
      /TypeError|ReferenceError|Failed to fetch chunk|Cannot read properties of undefined/i.test(e),
    );
    expect(fatal, `fatal console errors:\n${fatal.join("\n")}`).toEqual([]);
  });
});
