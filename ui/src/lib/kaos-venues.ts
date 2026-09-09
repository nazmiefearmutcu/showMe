/**
 * KAOS Multibot — shared constants + pure helpers (Lane D, 2026-09-09).
 *
 * The frozen contract (kaos-multibot/CONTRACT.md §D) pins these strings:
 *   - default bot name  "KAOS Multibot"
 *   - engine id         "kaos"
 *   - venue ids         "crypto" / "nasdaq"
 *   - paper banner      "PAPER (no Alpaca keys)"
 *
 * The backend (parallel lane) adds `engine` + `venues` to BotRecord:
 *   venues: [{ id, exchange_id, market, symbols[], risk_profile }]
 * Everything in this module is additive and defensive — a payload without
 * the new fields must render exactly as before (hide, never fake).
 *
 * Symbol universes are copied VERBATIM from the backend's
 * backend/showme/bots/kaos/config.py (the source of truth the seed and
 * templates.yml both use):
 *   - crypto: CRYPTO_DEFAULT_SYMBOLS — the 20 liquid USD-M majors in ccxt
 *     unified format for binanceusdm linear perps ("BTC/USDT:USDT").
 *   - nasdaq: NASDAQ_DEFAULT_SYMBOLS — indices (SPY/QQQ/IWM), megacaps,
 *     liquid semis. Plain tickers — the showme bot symbol validator
 *     (`^[A-Z0-9]+(/[A-Z0-9]+)?$`) has no room for class-share dots.
 *
 * `market` / `risk_profile` literals MUST match the backend VenueSpec
 * (`Literal["crypto-futures", "us-equities"]` /
 * `Literal["crypto", "equity"]`) or POST /api/bots rejects the draft 400.
 */

/** Frozen contract §D: the default bot name. */
export const KAOS_BOT_NAME = "KAOS Multibot";

/** Frozen contract §D: the engine id on the bot record. */
export const KAOS_ENGINE_ID = "kaos";

/** Frozen contract §D: venue ids on the bot record's venues array. */
export const KAOS_CRYPTO_VENUE_ID = "crypto";
export const KAOS_NASDAQ_VENUE_ID = "nasdaq";

/** Frozen contract §D: honest banner for the unkeyed equities lane. */
export const KAOS_PAPER_BANNER = "PAPER (no Alpaca keys)";

/** The sizing-only strategy spec id the backend seeds/templates bind (DEFAULT_KAOS_SPEC_ID). */
export const KAOS_SPEC_ID = "kaos-multibot";

/** One venue on a KAOS Multibot record (backend BotRecord.venues shape). */
export interface BotVenue {
  id: string;
  exchange_id: string;
  market: string;
  symbols: string[];
  risk_profile: string;
}

/**
 * One per-venue lane row of the backend get-bot status payload
 * (`venue_rows`). `lane_status` is honest by construction — a NASDAQ venue
 * without an Alpaca broker reports "PAPER (no Alpaca keys)"; a venue never
 * evaluated yet reports "idle".
 */
export interface KaosLaneRow {
  venue_id: string;
  market: string;
  bars_age?: number | null;
  last_eval?: string | null;
  decisions?: number;
  lane_status?: string;
}

/**
 * Crypto venue universe — 20 Binance USD-M perpetual majors, ccxt unified
 * symbols. Order mirrors the engine's DEFAULT_SYMBOLS (zero behavior change
 * on the crypto path — this list only preseeds the UI draft).
 */
export const KAOS_CRYPTO_SYMBOLS: readonly string[] = [
  "BTC/USDT:USDT",
  "ETH/USDT:USDT",
  "SOL/USDT:USDT",
  "BNB/USDT:USDT",
  "XRP/USDT:USDT",
  "DOGE/USDT:USDT",
  "ADA/USDT:USDT",
  "LINK/USDT:USDT",
  "AVAX/USDT:USDT",
  "SUI/USDT:USDT",
  "NEAR/USDT:USDT",
  "ENA/USDT:USDT",
  "LTC/USDT:USDT",
  "DOT/USDT:USDT",
  "APT/USDT:USDT",
  "ARB/USDT:USDT",
  "OP/USDT:USDT",
  "ATOM/USDT:USDT",
  "FIL/USDT:USDT",
  "SEI/USDT:USDT",
];

/**
 * NASDAQ venue universe — copied verbatim from
 * backend/showme/bots/kaos/config.py NASDAQ_DEFAULT_SYMBOLS (index ETFs +
 * megacaps + liquid semis), plain Alpaca-routable tickers.
 */
export const KAOS_NASDAQ_SYMBOLS: readonly string[] = [
  "SPY",
  "QQQ",
  "IWM",
  "AAPL",
  "MSFT",
  "NVDA",
  "AMZN",
  "GOOGL",
  "META",
  "AVGO",
  "TSLA",
  "BRKB",
  "LLY",
  "AMD",
  "INTC",
  "MU",
  "QCOM",
  "TXN",
  "ASML",
  "AMAT",
];

/** Fresh crypto venue descriptor (new array each call — callers may mutate their copy). */
export function kaosCryptoVenue(): BotVenue {
  return {
    id: KAOS_CRYPTO_VENUE_ID,
    exchange_id: "binanceusdm",
    market: "crypto-futures",
    symbols: [...KAOS_CRYPTO_SYMBOLS],
    risk_profile: "crypto",
  };
}

/** Fresh NASDAQ venue descriptor. Boots PAPER until real Alpaca keys exist. */
export function kaosNasdaqVenue(): BotVenue {
  return {
    id: KAOS_NASDAQ_VENUE_ID,
    exchange_id: "alpaca",
    market: "us-equities",
    symbols: [...KAOS_NASDAQ_SYMBOLS],
    risk_profile: "equity",
  };
}

/** Both venues, in contract order (crypto first, nasdaq second). */
export function kaosDefaultVenues(): BotVenue[] {
  return [kaosCryptoVenue(), kaosNasdaqVenue()];
}

/** True when the record is (or drafts as) the KAOS Multibot default engine. */
export function isKaosRecord(rec: {
  engine?: string | null;
  name?: string | null;
  strategy_id?: string | null;
}): boolean {
  return (
    rec.engine === KAOS_ENGINE_ID ||
    rec.name === KAOS_BOT_NAME ||
    rec.strategy_id === KAOS_ENGINE_ID ||
    rec.strategy_id === KAOS_SPEC_ID
  );
}

/** True when the venue is the equities/NASDAQ lane. */
export function isNasdaqVenue(venue: BotVenue): boolean {
  return (
    venue.id === KAOS_NASDAQ_VENUE_ID ||
    venue.market === "us-equities" ||
    venue.market === "us_equities"
  );
}

/** Short chip label for a venue badge. */
export function venueLabel(venue: BotVenue): string {
  if (isNasdaqVenue(venue)) return "NASDAQ";
  if (venue.market.startsWith("crypto")) return "CRYPTO";
  return venue.market.toUpperCase();
}

/** One-line venue tooltip: exchange + market + symbol count. */
export function venueTitle(venue: BotVenue): string {
  return `${venueLabel(venue)} — ${venue.exchange_id} (${venue.market}), ${venue.symbols.length} symbols`;
}

/**
 * Defensive read of the backend status payload's `lane_status` field
 * (contract §C: an unkeyed equity venue surfaces "PAPER (no keys)").
 *
 * The exact payload shape may evolve, so accept the plausible ones:
 *   - string                          → the lane status itself
 *   - { nasdaq: <lane> }              → keyed by venue id
 *   - { lanes: { nasdaq: <lane> } }   → nested map
 *   - [{ id|venue|venue_id, ... }]    → array of lane entries
 * A lane value may be a status string or an object with one of
 * `status` / `state` / `mode` (string), a boolean `paper`,
 * or an explicit `has_keys` / `keys` flag.
 *
 * Returns:
 *   true  → the NASDAQ lane is provably PAPER (no keys)
 *   false → provably not paper (keyed/live)
 *   null  → field absent or undecidable — the caller must HIDE the banner
 *           (honesty contract: render defensively, never fake).
 */
export function nasdaqLaneIsPaper(laneStatus: unknown): boolean | null {
  if (laneStatus == null) return null;
  const lane = findNasdaqLane(laneStatus);
  if (lane === undefined) return null;
  return laneIsPaper(lane);
}

function findNasdaqLane(laneStatus: unknown): unknown {
  if (typeof laneStatus === "string") return laneStatus;
  if (Array.isArray(laneStatus)) {
    for (const entry of laneStatus) {
      if (entry == null || typeof entry !== "object") continue;
      const o = entry as Record<string, unknown>;
      if (
        o.id === KAOS_NASDAQ_VENUE_ID ||
        o.venue === KAOS_NASDAQ_VENUE_ID ||
        o.venue_id === KAOS_NASDAQ_VENUE_ID
      ) {
        return entry;
      }
    }
    return undefined;
  }
  if (typeof laneStatus === "object") {
    const rec = laneStatus as Record<string, unknown>;
    if (KAOS_NASDAQ_VENUE_ID in rec) return rec[KAOS_NASDAQ_VENUE_ID];
    const lanes = rec.lanes;
    if (lanes != null && typeof lanes === "object" && KAOS_NASDAQ_VENUE_ID in (lanes as object)) {
      return (lanes as Record<string, unknown>)[KAOS_NASDAQ_VENUE_ID];
    }
  }
  return undefined;
}

function laneIsPaper(lane: unknown): boolean | null {
  if (lane == null) return null;
  if (typeof lane === "string") {
    const low = lane.toLowerCase();
    if (low.includes("paper")) {
      // Distinguish the KEYLESS paper lane ("PAPER (no Alpaca keys)") from a
      // keyed shadow evaluation ("shadow (paper fills)"): only the keyless
      // state earns the no-keys banner.
      return (
        low.includes("no keys") ||
        low.includes("no alpaca") ||
        low.includes("keyless") ||
        low.includes("unkeyed")
      );
    }
    if (low.includes("live") || low.includes("keyed")) return false;
    return null;
  }
  if (typeof lane === "object") {
    const o = lane as Record<string, unknown>;
    if (typeof o.lane_status === "string") return laneIsPaper(o.lane_status);
    if (typeof o.status === "string") return laneIsPaper(o.status);
    if (typeof o.state === "string") return laneIsPaper(o.state);
    if (typeof o.mode === "string") return laneIsPaper(o.mode);
    if (typeof o.paper === "boolean") return o.paper;
    if (o.has_keys === false || o.keys === false) return true;
    if (o.has_keys === true || o.keys === true) return false;
  }
  return null;
}

/**
 * Exact lane_status TEXT for the NASDAQ lane when it is provably PAPER —
 * the string the UI banner renders verbatim (frozen contract §D banner
 * "PAPER (no Alpaca keys)" — the backend's own words, never a UI-invented
 * label). Returns null when the rows are absent, undecidable, or the lane
 * is not paper — callers must HIDE the banner in that case.
 */
export function nasdaqLaneStatusText(venueRows: unknown): string | null {
  if (venueRows == null) return null;
  const lane = findNasdaqLane(venueRows);
  if (lane == null) return null;
  if (!laneIsPaper(lane)) return null;
  if (typeof lane === "string") return lane;
  if (typeof lane === "object") {
    const o = lane as Record<string, unknown>;
    if (typeof o.lane_status === "string") return o.lane_status;
  }
  return null;
}

/**
 * Stable reorder: KAOS templates (id "kaos" / name containing "kaos")
 * first, everything else keeps its relative order. Pure — returns a new
 * array, never mutates the catalog the backend shipped.
 */
export function pinKaosTemplatesFirst<T extends { id: string; name: string }>(
  entries: readonly T[],
): T[] {
  const kaos: T[] = [];
  const rest: T[] = [];
  for (const e of entries) {
    if (e.id.toLowerCase() === KAOS_ENGINE_ID || /kaos/i.test(e.name)) kaos.push(e);
    else rest.push(e);
  }
  return [...kaos, ...rest];
}
