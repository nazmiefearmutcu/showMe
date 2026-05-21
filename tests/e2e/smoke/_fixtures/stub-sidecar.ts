/**
 * Strict sidecar route stub for the smoke Playwright project.
 *
 * S06 — replaces the broad `route(/\/api\//, fulfill {})` catch-all from
 * the original `showme-shell.spec.ts`. That pattern hid bugs: any pane
 * that quietly began calling a new endpoint (e.g. `/api/quote/AAPL`,
 * `/api/fn/GP`, `/api/stream/stats`) would still see a 200 / empty
 * body, and the pane would silently render the "no data" branch. The
 * smoke would stay green while shipped UI silently degraded.
 *
 * The new stub:
 *   * Provides explicit, shape-correct fulfillments for the critical
 *     endpoints listed in `CRITICAL_PATHS` — quotes, GP, stream stats,
 *     health, function-index, sidecar info.
 *   * Tracks any request whose pathname matches a critical pattern but
 *     was NOT explicitly handled. The test gets a list back and can
 *     assert it is empty so unhandled critical hits fail the gate.
 *   * Keeps a residual benign-200 for the long tail of non-critical
 *     endpoints (presets, x sentiment, alerts list, ...) so tests
 *     focused on a single pane don't have to enumerate everything.
 *
 * Caller contract:
 *   ```ts
 *   const tracker = await stubSidecar(page, {
 *     quotes: { AAPL: { price: 187.42 } },
 *     functions: { GP: gpFunctionFixture({ symbol: "AAPL" }) },
 *   });
 *   await page.goto("/#/symbol/AAPL/GP");
 *   // ...assertions...
 *   tracker.assertNoCriticalFallthroughs();
 *   ```
 */
import type { Page, Route, Request } from "@playwright/test";
import {
  FUNCTION_INDEX_FIXTURE,
  HEALTH_FIXTURE,
  SIDECAR_INFO_FIXTURE,
  STREAM_STATS_FIXTURE,
  TICKER_FIXTURE,
  gpFunctionFixture,
  quoteSnapshotFixture,
  type QuoteFixtureInput,
} from "./sidecar-fixtures";

/**
 * Critical paths the smoke MUST satisfy with a real fixture. If any of
 * these fall through to the benign catch-all, the test fails — that means
 * a new code path is reaching out for data and we'd be lying about
 * whether the pane works.
 */
const CRITICAL_PATTERNS: RegExp[] = [
  /^\/api\/fn\/GP(?:\/|$|\?)/i,
  /^\/api\/quote\/[^/]+/i,
  /^\/api\/stream\/stats(?:\/|$|\?)/i,
];

export interface StubSidecarOptions {
  /** Map of symbol → quote override. Symbols not listed get a default 100. */
  quotes?: Record<string, Omit<QuoteFixtureInput, "symbol"> | undefined>;
  /** Map of `code` → exact FunctionCallResult body to return for `/api/fn/<code>`. */
  functions?: Record<string, unknown>;
  /** When true (default), the catch-all sets status to 200; flip to false to fail loud. */
  benignCatchAll?: boolean;
}

export interface SidecarStubTracker {
  /** All handled critical requests (path-only). */
  readonly handled: ReadonlyArray<string>;
  /** Critical requests that hit the catch-all instead of a real route. */
  readonly criticalFallthroughs: ReadonlyArray<string>;
  /** Throws with a tidy message if any critical request leaked through. */
  assertNoCriticalFallthroughs(): void;
}

export async function stubSidecar(
  page: Page,
  opts: StubSidecarOptions = {},
): Promise<SidecarStubTracker> {
  const handled: string[] = [];
  const criticalFallthroughs: string[] = [];
  const benign = opts.benignCatchAll !== false;

  const markHandled = (req: Request) => {
    const path = new URL(req.url()).pathname;
    handled.push(path);
  };

  // ── 1. Catch-all registered FIRST so later, more-specific routes win.
  //
  // Playwright's matching rule is "last registered route wins" — so the
  // catch-all here is the LOW-priority fallback, and the specific routes
  // we add afterwards override it for the real paths.
  await page.route(/\/api\//, async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (CRITICAL_PATTERNS.some((re) => re.test(path))) {
      criticalFallthroughs.push(path);
      // Return a deliberately broken envelope so the pane doesn't render
      // pretend-data and the test can fail fast on top of the assertion.
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: "smoke: unstubbed critical endpoint",
          path,
        }),
      });
      return;
    }
    if (!benign) {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ error: "smoke: unstubbed non-critical endpoint", path }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });

  // ── 2. Sidecar bootstrap: health + info + function index + ticker.
  await page.route("**/api/health", (route) => {
    markHandled(route.request());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(HEALTH_FIXTURE),
    });
  });

  await page.route("**/api/sidecar/info", (route) => {
    markHandled(route.request());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SIDECAR_INFO_FIXTURE),
    });
  });

  await page.route("**/api/function-index", (route) => {
    markHandled(route.request());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(FUNCTION_INDEX_FIXTURE),
    });
  });

  await page.route("**/api/sidecar/ticker", (route) => {
    markHandled(route.request());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(TICKER_FIXTURE),
    });
  });

  // ── 3. Critical: /api/stream/stats
  await page.route("**/api/stream/stats", (route) => {
    markHandled(route.request());
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(STREAM_STATS_FIXTURE),
    });
  });

  // ── 4. Critical: /api/quote/<symbol>
  await page.route(/\/api\/quote\/[^/?]+/, (route) => {
    const req = route.request();
    markHandled(req);
    const url = new URL(req.url());
    const segments = url.pathname.split("/").filter(Boolean);
    const symbol = decodeURIComponent(segments[segments.length - 1] ?? "").toUpperCase();
    const override = opts.quotes?.[symbol];
    const price = override?.price ?? 100;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        quoteSnapshotFixture({
          symbol,
          price,
          previousClose: override?.previousClose,
          source: override?.source,
        }),
      ),
    });
  });

  // ── 5. Critical: /api/fn/<code> — GP gets a real candle fixture by
  // default; other functions can be overridden via `opts.functions`.
  await page.route(/\/api\/fn\/[^/?]+/, (route) => {
    const req = route.request();
    markHandled(req);
    const url = new URL(req.url());
    const segments = url.pathname.split("/").filter(Boolean);
    const code = decodeURIComponent(segments[segments.length - 1] ?? "").toUpperCase();
    const override = opts.functions?.[code];
    if (override !== undefined) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(override),
      });
    }
    // Default GP fixture so the watchlist sparkline call (which fans into
    // /api/fn/GP for every row) doesn't bring back zero candles and trip
    // an unrelated branch.
    if (code === "GP") {
      const symbolParam = url.searchParams.get("symbol") ?? "AAPL";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(gpFunctionFixture({ symbol: symbolParam })),
      });
    }
    // Generic empty-OK envelope for other functions — keeps panes from
    // rendering an error toast but does NOT count as a critical handler.
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        code,
        instrument: null,
        data: {},
        metadata: {},
        fetched_at: new Date().toISOString(),
        sources: [],
        warnings: [],
        elapsed_ms: 1,
        status: "ok",
      }),
    });
  });

  const tracker: SidecarStubTracker = {
    get handled() {
      return handled.slice();
    },
    get criticalFallthroughs() {
      return criticalFallthroughs.slice();
    },
    assertNoCriticalFallthroughs() {
      if (criticalFallthroughs.length === 0) return;
      throw new Error(
        `Critical endpoints fell through to catch-all (unstubbed):\n  - ${criticalFallthroughs.join(
          "\n  - ",
        )}`,
      );
    },
  };
  return tracker;
}

/**
 * Seed `localStorage` so the browser-mode UI behaves as if the Tauri
 * shell already published a sidecar port and (optionally) a dev auth
 * token. Without this, every fetch waits for `/api/health` first and the
 * boot sequence stays in "booting…" for ~250ms longer.
 */
export async function seedBrowserShellLocalStorage(
  page: Page,
  init?: { port?: number; devAuthToken?: string; watchlist?: ReadonlyArray<string> },
): Promise<void> {
  const port = init?.port ?? 8765;
  const watchlist = init?.watchlist
    ? JSON.stringify({
        rows: init.watchlist.map((symbol) => ({ symbol })),
      })
    : null;
  const devAuthToken = init?.devAuthToken ?? null;
  await page.addInitScript(
    ([p, devToken, list]) => {
      try {
        window.localStorage.setItem("showme.sidecarPort", String(p));
        if (devToken) {
          window.localStorage.setItem("showme.devAuthToken", devToken as string);
        }
        if (list) {
          window.localStorage.setItem("showme.watchlist", list as string);
        }
      } catch {
        /* private mode → no-op */
      }
    },
    [port, devAuthToken, watchlist],
  );
}
