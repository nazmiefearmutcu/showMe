/**
 * Lane D (frozen contract §D) — pure KAOS venue helpers.
 *
 * Pins:
 *   - the default venue drafts match the REAL backend VenueSpec literals
 *     (market "crypto-futures"/"us-equities", risk_profile "crypto"/"equity")
 *     and the universes copied from backend/showme/bots/kaos/config.py;
 *   - venue identity/label helpers;
 *   - defensive lane_status parsing: paper provable → exact text, else null
 *     (hide, never fake);
 *   - stable KAOS-first template pinning.
 */
import { describe, expect, it } from "vitest";
import {
  KAOS_BOT_NAME,
  KAOS_CRYPTO_SYMBOLS,
  KAOS_ENGINE_ID,
  KAOS_NASDAQ_SYMBOLS,
  KAOS_PAPER_BANNER,
  isKaosRecord,
  isNasdaqVenue,
  kaosDefaultVenues,
  nasdaqLaneIsPaper,
  nasdaqLaneStatusText,
  pinKaosTemplatesFirst,
  venueLabel,
} from "./kaos-venues";

describe("kaos default venues (backend VenueSpec parity)", () => {
  it("drafts crypto first with the backend literals", () => {
    const [crypto] = kaosDefaultVenues();
    expect(crypto.id).toBe("crypto");
    expect(crypto.exchange_id).toBe("binanceusdm");
    // Must be the backend's Literal value — POST /api/bots rejects others.
    expect(crypto.market).toBe("crypto-futures");
    expect(crypto.risk_profile).toBe("crypto");
    expect(crypto.symbols).toEqual([...KAOS_CRYPTO_SYMBOLS]);
  });

  it("drafts nasdaq second with the backend literals", () => {
    const [, nasdaq] = kaosDefaultVenues();
    expect(nasdaq.id).toBe("nasdaq");
    expect(nasdaq.exchange_id).toBe("alpaca");
    expect(nasdaq.market).toBe("us-equities");
    expect(nasdaq.risk_profile).toBe("equity");
    expect(nasdaq.symbols).toEqual([...KAOS_NASDAQ_SYMBOLS]);
  });

  it("carries 20 majors per venue, copied from backend kaos/config.py", () => {
    expect(KAOS_CRYPTO_SYMBOLS).toHaveLength(20);
    expect(KAOS_CRYPTO_SYMBOLS[0]).toBe("BTC/USDT:USDT");
    expect(KAOS_NASDAQ_SYMBOLS).toHaveLength(20);
    expect(KAOS_NASDAQ_SYMBOLS.slice(0, 3)).toEqual(["SPY", "QQQ", "IWM"]);
    expect(KAOS_NASDAQ_SYMBOLS).toContain("BRKB");
  });

  it("returns fresh symbol arrays per call (mutation isolation)", () => {
    const a = kaosDefaultVenues();
    a[0].symbols.push("MUTATED/USDT");
    const b = kaosDefaultVenues();
    expect(b[0].symbols).not.toContain("MUTATED/USDT");
  });

  it("pins the frozen contract strings", () => {
    expect(KAOS_BOT_NAME).toBe("KAOS Multibot");
    expect(KAOS_ENGINE_ID).toBe("kaos");
    expect(KAOS_PAPER_BANNER).toBe("PAPER (no Alpaca keys)");
  });
});

describe("kaos record identity", () => {
  it("identifies by engine, name, or the seeded spec id", () => {
    expect(isKaosRecord({ engine: "kaos" })).toBe(true);
    expect(isKaosRecord({ name: "KAOS Multibot" })).toBe(true);
    expect(isKaosRecord({ strategy_id: "kaos-multibot" })).toBe(true);
    expect(isKaosRecord({ strategy_id: "kaos" })).toBe(true);
  });

  it("never identifies spec-rule bots", () => {
    expect(isKaosRecord({ engine: "spec", strategy_id: "rsi-mean-revert" })).toBe(false);
    expect(isKaosRecord({})).toBe(false);
  });

  it("labels venues as chips", () => {
    const [crypto, nasdaq] = kaosDefaultVenues();
    expect(venueLabel(crypto)).toBe("CRYPTO");
    expect(venueLabel(nasdaq)).toBe("NASDAQ");
    expect(isNasdaqVenue(nasdaq)).toBe(true);
    expect(isNasdaqVenue(crypto)).toBe(false);
  });
});

describe("nasdaq lane paper parsing (defensive — hide, never fake)", () => {
  const paperRows = [
    { venue_id: "crypto", market: "crypto-futures", lane_status: "shadow (paper fills)" },
    { venue_id: "nasdaq", market: "us-equities", lane_status: "PAPER (no Alpaca keys)" },
  ];

  it("returns the backend's exact banner text when the nasdaq lane is paper", () => {
    expect(nasdaqLaneStatusText(paperRows)).toBe("PAPER (no Alpaca keys)");
    expect(nasdaqLaneIsPaper(paperRows)).toBe(true);
  });

  it("accepts the bars-unavailable paper variant verbatim", () => {
    const rows = [
      { venue_id: "nasdaq", lane_status: "PAPER (no Alpaca keys) — bars unavailable" },
    ];
    expect(nasdaqLaneStatusText(rows)).toBe("PAPER (no Alpaca keys) — bars unavailable");
  });

  it("returns null when venue_rows is absent or empty", () => {
    expect(nasdaqLaneStatusText(undefined)).toBeNull();
    expect(nasdaqLaneStatusText(null)).toBeNull();
    expect(nasdaqLaneStatusText([])).toBeNull();
  });

  it("returns null when no nasdaq row exists (crypto-only payload)", () => {
    const rows = [{ venue_id: "crypto", lane_status: "shadow (paper fills)" }];
    expect(nasdaqLaneStatusText(rows)).toBeNull();
  });

  it("returns null when the nasdaq lane is NOT paper (keyed/shadow)", () => {
    expect(nasdaqLaneStatusText([
      { venue_id: "nasdaq", lane_status: "shadow (paper fills)" },
    ])).toBeNull();
    expect(nasdaqLaneStatusText([
      { venue_id: "nasdaq", lane_status: "idle" },
    ])).toBeNull();
    expect(nasdaqLaneIsPaper([{ venue_id: "nasdaq", lane_status: "live" }])).toBe(false);
  });

  it("tolerates alternative payload shapes", () => {
    expect(nasdaqLaneIsPaper({ nasdaq: "PAPER (no keys)" })).toBe(true);
    expect(nasdaqLaneIsPaper({ lanes: { nasdaq: { status: "PAPER (no Alpaca keys)" } } })).toBe(true);
    expect(nasdaqLaneIsPaper([{ venue: "nasdaq", has_keys: false }])).toBe(true);
    expect(nasdaqLaneIsPaper([{ id: "nasdaq", keys: true }])).toBe(false);
    expect(nasdaqLaneIsPaper("shadow")).toBeNull();
  });
});

describe("pinKaosTemplatesFirst", () => {
  it("moves kaos entries first, preserving relative order elsewhere", () => {
    const entries = [
      { id: "rsi-mean-revert", name: "RSI Mean Revert" },
      { id: "ema-crossover", name: "EMA Crossover" },
      { id: "kaos-multibot", name: "KAOS Multibot" },
    ];
    const pinned = pinKaosTemplatesFirst(entries);
    expect(pinned.map((e) => e.id)).toEqual([
      "kaos-multibot", "rsi-mean-revert", "ema-crossover",
    ]);
    // Pure — the input array is untouched.
    expect(entries.map((e) => e.id)).toEqual([
      "rsi-mean-revert", "ema-crossover", "kaos-multibot",
    ]);
  });

  it("detects kaos by id or name, case-insensitively", () => {
    const pinned = pinKaosTemplatesFirst([
      { id: "a", name: "A" },
      { id: "other", name: "The KAOS Engine" },
    ]);
    expect(pinned[0].id).toBe("other");
  });
});
