/**
 * S06 gate 2 — GP pane release contract.
 *
 * Why this gate exists: prior smoke runs only checked that
 * `/#/symbol/AAPL/GP` "rendered" by matching the literal text "Price". A
 * pane stuck on the loading skeleton with zero candles would pass that
 * gate. Worse, the WS transport pill / SNAPSHOT-ONLY / OFFLINE branches
 * were never exercised because `useLiveQuote` never received a tick.
 *
 * Required by the goal:
 *   * fixture candles render the chart host (real branch, not skeleton)
 *   * a quote snapshot is consumed
 *   * a fake WebSocket tick lifts `transportState` → live, so the
 *     `gp-transport-pill[data-state="live"]` chip appears
 *   * Compare and Export remain visibly disabled (we explicitly chose
 *     the "honest" route over a fake hookup — the gate locks that in)
 *   * the GP-specific news rail shows the empty state, not invented
 *     headlines (S03-R regression guard)
 *   * no critical request (`/api/fn/GP`, `/api/quote/*`,
 *     `/api/stream/stats`) silently falls through to the catch-all
 */
import { expect, test } from "@playwright/test";
import { installFakeQuoteSocket } from "./_fixtures/fake-quote-socket";
import {
  gpFunctionFixture,
  STREAM_STATS_FIXTURE,
} from "./_fixtures/sidecar-fixtures";
import {
  seedBrowserShellLocalStorage,
  stubSidecar,
} from "./_fixtures/stub-sidecar";

test.describe("GP pane — fixture-backed release gate", () => {
  test.beforeEach(async ({ page }) => {
    await seedBrowserShellLocalStorage(page);
  });

  test("renders fixture candles, picks up live tick, honors disabled controls", async ({
    page,
  }) => {
    const candleFixture = gpFunctionFixture({
      symbol: "AAPL",
      count: 60,
      startPrice: 187.42,
    });
    const tracker = await stubSidecar(page, {
      quotes: { AAPL: { price: 187.42, previousClose: 185.0, source: "fixture" } },
      functions: { GP: candleFixture },
    });

    // Fake WS so the transport pill can advance to `live`.
    const socket = await installFakeQuoteSocket(page, {
      ticks: {
        AAPL: [
          { price: 188.21, changePct: 1.74, source: "fake-ws" },
          { price: 188.55, changePct: 1.92, source: "fake-ws" },
        ],
      },
      intervalMs: 250,
    });

    await page.goto("/#/symbol/AAPL/GP");

    // ── Chart host (real, not skeleton). The host is rendered only
    //    when `ohlc.length > 0`, so visibility here proves `/api/fn/GP`
    //    was consumed end-to-end.
    const chartHost = page.locator('[data-testid="gp-chart-host"]');
    await expect(chartHost).toBeVisible({ timeout: 10_000 });

    // ── Candle count banner ("60 candles · drag/scroll to inspect history")
    //    lives in the fit-toolbar inside the chart. Match the count.
    const candleCount = candleFixture.data.ohlcv.length;
    await expect(page.locator("body")).toContainText(
      new RegExp(`${candleCount}\\s+candles`, "i"),
      { timeout: 4_000 },
    );

    // ── Header strip shows the last candle's close. The fixture is
    //    deterministic, so we derive the integer-part of the last close
    //    from the fixture itself instead of hard-coding a magic number —
    //    if the fixture algorithm shifts, this assertion still tracks.
    const lastCandle =
      candleFixture.data.ohlcv[candleFixture.data.ohlcv.length - 1];
    const lastClose = lastCandle.close;
    const lastCloseInt = Math.trunc(lastClose);
    await expect(page.locator("body")).toContainText(
      new RegExp(`${lastCloseInt}\\.\\d`),
    );

    // ── Provider tag in PaneFooter proves /api/fn/GP went through our
    //    fixture and wasn't swallowed by the catch-all.
    await expect(page.locator("body")).toContainText("fixture-deterministic");

    // ── WS tick → live pill. The transport pill DOM only appears when
    //    transport is `live` (or one of the warn states). Asserting
    //    [data-state="live"] specifically catches the case where the WS
    //    handshake succeeded but no tick arrived — which used to leave
    //    the pill on `connecting` until the stale watchdog fired.
    const liveTransport = page.locator(
      '[data-testid="gp-transport-pill"][data-state="live"]',
    );
    await expect(liveTransport).toBeVisible({ timeout: 8_000 });
    await expect(liveTransport).toContainText(/RT LIVE/i);

    // ── Compare / Export are explicitly honest-disabled (S03 decision —
    //    we ship the chip greyed instead of pretending the action works).
    //    aria-disabled is the contract; `:disabled` alone wouldn't catch
    //    a regression that swapped `<button disabled>` for a span/div.
    const compareBtn = page.locator('[data-testid="gp-compare-button"]');
    await expect(compareBtn).toBeVisible();
    await expect(compareBtn).toHaveAttribute("aria-disabled", "true");
    await expect(compareBtn).toBeDisabled();

    const exportBtn = page.locator('[data-testid="gp-export-button"]');
    await expect(exportBtn).toBeVisible();
    await expect(exportBtn).toHaveAttribute("aria-disabled", "true");
    await expect(exportBtn).toBeDisabled();

    // ── News rail empty state — protects S03-R "no mock news". If a
    //    future change re-introduces fabricated headlines, this gate
    //    fails because `[data-testid="gp-news-empty"]` disappears.
    const newsEmpty = page.locator('[data-testid="gp-news-empty"]');
    await expect(newsEmpty).toBeVisible();
    await expect(newsEmpty).toContainText(/News not wired/i);

    // ── At least one WS connection happened.
    expect(socket.connections()).toBeGreaterThanOrEqual(1);

    // ── No critical endpoint slipped past the strict route stub.
    //    Strictness check covers `/api/quote/AAPL` + `/api/fn/GP` and would
    //    catch a regression that started calling `/api/stream/stats` from
    //    inside the GP pane without us realizing.
    tracker.assertNoCriticalFallthroughs();

    // The GP pane drives /api/fn/GP and /api/quote/<sym>. Both should
    // show up in the handled list — that proves snapshot + function
    // payload both reached the route handlers rather than slipping past
    // into the catch-all fallback. The presence of the stream-stats
    // fixture is documented (consumed elsewhere) without forcing it
    // here, since GP itself doesn't poll the statusbar.
    expect(
      tracker.handled.some((p) => p.startsWith("/api/quote/")),
      "the snapshot route must be hit",
    ).toBeTruthy();
    expect(
      tracker.handled.some((p) => p.startsWith("/api/fn/GP")),
      "the GP function route must be hit",
    ).toBeTruthy();
    // STREAM_STATS_FIXTURE is loaded by the stub for other panes; keep
    // the import to lock the fixture surface even though GP itself
    // doesn't fetch it.
    void STREAM_STATS_FIXTURE;
  });
});
