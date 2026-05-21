/**
 * Deterministic fixture payloads for the showMe sidecar HTTP surface.
 *
 * S06 — the legacy `stubSidecar` helper relied on a single catch-all that
 * replied `{}` to every `/api/**` request. That hid real wiring bugs:
 *   * a pane could quietly fall back to "no data" because `/api/quote/AAPL`
 *     returned `{}` and the snapshot parser silently coerced it to nothing;
 *   * GP could render an empty chart skeleton because `/api/fn/GP` came back
 *     as `{}` and `normalizeOHLC` short-circuited to an empty array.
 *
 * The new fixtures here are intentionally minimal but SHAPED — they match
 * what the sidecar would actually return, so panes hit their real branches.
 */
/**
 * Match the `SidecarHealth` interface in `lib/sidecar.ts`:
 *   * `ok: boolean` — drives `setSidecarStatus("healthy" | "crashed")`
 *   * `engine: { engine_root, engine_attached }` — used by `refreshHealth`
 *     to feed `setEngineRoot`. Without a truthy `engine_root`, the
 *     `dashboardReady` gate in App.tsx never trips and the IntroSplash
 *     stays in `--standby` forever with `pointer-events: auto`,
 *     blocking every smoke-spec click.
 *
 * The flat `status` / `function_count` fields are kept for any pane
 * that still reads them, but the load-bearing ones are `ok` + `engine`.
 */
export const HEALTH_FIXTURE = {
  ok: true,
  status: "healthy",
  engine: {
    engine_attached: true,
    engine_root: "/Applications/showMe.app/Contents/Resources/engine",
  },
  engine_attached: true,
  engine_root: "/Applications/showMe.app/Contents/Resources/engine",
  function_count: 141,
} as const;

export const SIDECAR_INFO_FIXTURE = {
  version: "0.0.1-s06-smoke",
  engine: {
    engine_attached: true,
    engine_root: HEALTH_FIXTURE.engine_root,
  },
} as const;

/**
 * Function-index payload returned by the sidecar.
 *
 * IMPORTANT: must contain MORE THAN 20 entries — the boot splash in
 * `App.tsx` (`BACKEND_INDEX_READY_THRESHOLD = 20`) waits for the
 * function index to clear that floor before flipping `dashboardReady`
 * true. With a shorter index, `IntroSplash` stays in the `standby`
 * phase forever, its `pointer-events: auto` overlay covers the
 * workspace, and every interaction in a smoke spec gets intercepted.
 *
 * The canonical panes (DES, GP, PORT, WATCH, XSEN, INSTANT) come first
 * so panes that query them by code still work. The remainder are
 * realistic-looking filler so the count clears the threshold without
 * inventing random strings.
 */
const REAL_CODES = [
  "DES", "GP", "PORT", "WATCH", "XSEN", "INSTANT",
] as const;
const FILLER_CODES = [
  "BTMM", "GEX", "OMON", "FA", "TOP", "NEWS",
  "ALRT", "ANR", "ASK", "BIO", "CORR", "DPF",
  "DVD", "ECFC", "ECO", "ECST", "EE", "MIS",
  "HP", "TRAN", "SCAN", "MOST",
] as const;
export const FUNCTION_INDEX_FIXTURE = [
  ...REAL_CODES.map((code) => ({
    code,
    name: `${code} fixture`,
    category: "equity",
    asset_classes: ["equity"],
  })),
  ...FILLER_CODES.map((code) => ({
    code,
    name: `${code} fixture`,
    category: "screen",
    asset_classes: ["equity"],
  })),
];

export const TICKER_FIXTURE = {
  bot: { running: true, mode: "live", cycle: 12 },
  portfolio: { n_positions: 3, market_value: 12345.67 },
  alerts: { active: 0, fired_today: 1 },
} as const;

/**
 * /api/stream/stats — exact shape the SidecarStatus polling in the
 * statusbar consumes. Real shape: `{ active_clients, total_messages,
 * uptime_s, ... }`. Keep the keys present so the statusbar doesn't
 * fall back to "—" placeholders that we'd then assert on by accident.
 */
export const STREAM_STATS_FIXTURE = {
  active_clients: 1,
  total_messages: 42,
  uptime_s: 120,
  symbols_streamed: ["AAPL"],
} as const;

export interface QuoteFixtureInput {
  symbol: string;
  price: number;
  previousClose?: number;
  source?: string;
}

/** Build a quote snapshot that matches `QuoteSnapshot` in `lib/quotes.ts`. */
export function quoteSnapshotFixture(input: QuoteFixtureInput) {
  const previous = input.previousClose ?? input.price - 1;
  const changePct = previous ? ((input.price - previous) / previous) * 100 : 0;
  const fetchedAt = new Date("2026-05-20T15:00:00Z").toISOString();
  return {
    ok: true,
    data: {
      symbol: input.symbol,
      asset_class: "EQUITY",
      last: input.price,
      price: input.price,
      previous_close: previous,
      previousClose: previous,
      change_pct: changePct,
      regularMarketChangePercent: changePct,
      volume: 1_500_000,
      bid: input.price - 0.05,
      ask: input.price + 0.05,
      source: input.source ?? "fixture",
      provider_symbol: input.symbol,
      currency: "USD",
      fetched_at: fetchedAt,
    },
  };
}

/**
 * Build a `FunctionCallResult` envelope for `/api/fn/GP`. Generates `count`
 * candles backwards from `endIso`, walking down at a steady rate so the
 * computed indicators in the right rail are deterministic. The series is
 * intentionally long enough (>=15 bars) to trip the RSI / MACD branches in
 * `computeIndicators` so the rail isn't all em-dashes.
 */
export function gpFunctionFixture(opts: {
  symbol: string;
  count?: number;
  startPrice?: number;
}) {
  const count = opts.count ?? 60;
  const startPrice = opts.startPrice ?? 180;
  const ohlcv: Array<{
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
  }> = [];
  // Anchor on a fixed date so the spec is deterministic across days.
  const anchor = new Date("2026-05-20T00:00:00Z");
  for (let i = 0; i < count; i += 1) {
    const d = new Date(anchor.getTime() - (count - 1 - i) * 86_400_000);
    const open = startPrice + Math.sin(i / 3) * 4 + i * 0.1;
    const close = open + Math.cos(i / 5) * 1.5 + 0.2;
    const high = Math.max(open, close) + 0.6;
    const low = Math.min(open, close) - 0.6;
    ohlcv.push({
      date: d.toISOString().slice(0, 10),
      open: round2(open),
      high: round2(high),
      low: round2(low),
      close: round2(close),
      volume: 1_000_000 + i * 10_000,
    });
  }
  return {
    code: "GP",
    instrument: { symbol: opts.symbol, asset_class: "EQUITY" },
    data: {
      ohlcv,
      indicators: {
        ema20: ohlcv.map((bar) => ({ time: bar.date, value: bar.close - 0.5 })),
      },
    },
    metadata: { fixture: true },
    fetched_at: new Date("2026-05-20T15:00:00Z").toISOString(),
    sources: ["fixture-deterministic"],
    warnings: [],
    elapsed_ms: 17,
    status: "ok" as const,
  };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
