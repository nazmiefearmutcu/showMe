/**
 * S06 gate 3 — WATCH pane release contract.
 *
 * Why this gate exists: the original smoke navigated to `/#/symbol/AAPL/WATCH`
 * and only checked that the body contained "WATCH" or "Watchlist". That
 * passed even with zero rows, no quotes, no ticks — i.e. it asserted the
 * route resolved but not that the pane actually worked.
 *
 * The real WATCH contract:
 *   * `useLiveQuotes(symbols)` snapshots every symbol via `/api/quote/<S>`
 *     and subscribes to `ws://.../ws/quote/<S>`.
 *   * The header pill shows `LIVE · <n>` when ≥1 socket is in transport
 *     state `live`; otherwise it shows `OFFLINE`. The footer mirrors with
 *     `ws · n/m live`.
 *   * Snapshot-only (no ticks) would leave the LIVE count at 0 forever
 *     — a known failure mode we want to catch.
 *
 * This spec seeds the watchlist in localStorage, stubs the snapshot route
 * with deterministic prices, feeds two scripted ticks per symbol via the
 * fake WS, and asserts the LIVE count surface AND the strict-route
 * contract.
 */
import { expect, test } from "@playwright/test";
import { installFakeQuoteSocket } from "./_fixtures/fake-quote-socket";
import {
  seedBrowserShellLocalStorage,
  stubSidecar,
} from "./_fixtures/stub-sidecar";

const SEEDED_SYMBOLS = ["AAPL", "MSFT"] as const;

test.describe("WATCH pane — snapshot + live tick gate", () => {
  test.beforeEach(async ({ page }) => {
    await seedBrowserShellLocalStorage(page, {
      watchlist: SEEDED_SYMBOLS,
    });
  });

  test("snapshots + WS ticks lift LIVE count above 0", async ({ page }) => {
    const tracker = await stubSidecar(page, {
      quotes: {
        AAPL: { price: 187.42, previousClose: 185.0, source: "fixture" },
        MSFT: { price: 412.55, previousClose: 410.1, source: "fixture" },
      },
    });

    const socket = await installFakeQuoteSocket(page, {
      ticks: {
        AAPL: [
          { price: 187.6, changePct: 1.4, source: "fake-ws" },
          { price: 188.1, changePct: 1.7, source: "fake-ws" },
        ],
        MSFT: [
          { price: 413.2, changePct: 0.75, source: "fake-ws" },
          { price: 413.4, changePct: 0.8, source: "fake-ws" },
        ],
      },
      intervalMs: 250,
    });

    await page.goto("/#/symbol/AAPL/WATCH");

    // ── Both rows mount (symbol cells are <button class="u-symbol-link">).
    //    Playwright's `getByRole({ name: 'AAPL' })` misses these because the
    //    button has no aria-label and the accessible name is computed
    //    against the trimmed text; we go straight to the canonical class
    //    name + visible text for stability.
    for (const sym of SEEDED_SYMBOLS) {
      await expect(
        page.locator(`button.u-symbol-link:has-text("${sym}")`),
      ).toBeVisible({ timeout: 10_000 });
    }

    // ── Quote values reach the cells. WATCH's `view.price` merges
    //    snapshot + lastTick with the tick winning when present, so the
    //    rendered number is the most recent fake-WS tick price. We
    //    assert on the integer part of the FINAL tick we scripted —
    //    proves both the snapshot path resolved AND the WS tick
    //    overlaid on top.
    await expect(page.locator("body")).toContainText(/188\./);
    await expect(page.locator("body")).toContainText(/413\./);

    // ── LIVE pill in the header. It only renders this branch once ≥1
    //    quote view has `transportState === "live"`. The regex pins
    //    "LIVE · <n>" with n >= 1.
    const liveHeaderPill = page
      .locator("body")
      .getByText(/LIVE\s*·\s*[1-9]\d*/i)
      .first();
    await expect(liveHeaderPill).toBeVisible({ timeout: 8_000 });

    // ── Footer mirrors with `ws · n/m live` where n ≥ 1.
    const liveFooter = page
      .locator("body")
      .getByText(/ws\s*·\s*[1-9]\d*\s*\/\s*2\s*live/i)
      .first();
    await expect(liveFooter).toBeVisible({ timeout: 8_000 });

    // ── Per-row stream pill must reach `live` for at least one symbol.
    //    `.showme-watch__stream--live` is the canonical row-level marker.
    const liveRowMarkers = page.locator(".showme-watch__stream--live");
    await expect(liveRowMarkers.first()).toBeVisible({ timeout: 8_000 });

    // ── Source column should advertise the live tick overlay on at least
    //    one row (text includes "· live" suffix per WATCH.tsx).
    await expect(page.locator("body")).toContainText(/· live/i, {
      timeout: 4_000,
    });

    // ── WS connections: at least one per symbol.
    expect(socket.connections()).toBeGreaterThanOrEqual(SEEDED_SYMBOLS.length);

    // ── Strict-route contract.
    tracker.assertNoCriticalFallthroughs();
    expect(
      tracker.handled.filter((p) => p.startsWith("/api/quote/")).length,
      "every seeded symbol should hit the snapshot endpoint",
    ).toBeGreaterThanOrEqual(SEEDED_SYMBOLS.length);
  });
});
