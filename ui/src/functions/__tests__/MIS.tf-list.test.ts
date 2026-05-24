/**
 * Bug #19 — MIS UI advertised 1wk/1mo for EQUITY/ETF, but the backend
 * `_ZAK` map has no weight for those keys → the scan hangs indefinitely
 * (request never resolves). Until the backend ships weekly/monthly weights
 * the UI must not offer them.
 */
import { describe, expect, it } from "vitest";
import { MIS_FALLBACK_TFS, MIS_TFS_BY_MARKET } from "@/lib/mis";

describe("MIS_TFS_BY_MARKET — Bug #19", () => {
  it("EQUITY does NOT advertise 1wk or 1mo", () => {
    expect(MIS_TFS_BY_MARKET.EQUITY).not.toContain("1wk");
    expect(MIS_TFS_BY_MARKET.EQUITY).not.toContain("1mo");
  });

  it("ETF does NOT advertise 1wk or 1mo", () => {
    expect(MIS_TFS_BY_MARKET.ETF).not.toContain("1wk");
    expect(MIS_TFS_BY_MARKET.ETF).not.toContain("1mo");
  });

  it("FX/COMMODITY/BOND also drop 1wk/1mo (same backend gap)", () => {
    expect(MIS_TFS_BY_MARKET.FX).not.toContain("1wk");
    expect(MIS_TFS_BY_MARKET.FX).not.toContain("1mo");
    expect(MIS_TFS_BY_MARKET.COMMODITY).not.toContain("1wk");
    expect(MIS_TFS_BY_MARKET.COMMODITY).not.toContain("1mo");
    expect(MIS_TFS_BY_MARKET.BOND).not.toContain("1wk");
    expect(MIS_TFS_BY_MARKET.BOND).not.toContain("1mo");
  });

  it("CRYPTO still ships the full 12-TF ZAK matrix (1m..1d)", () => {
    // CRYPTO is untouched by this fix — TBV3 weights every one of these.
    expect(MIS_TFS_BY_MARKET.CRYPTO.length).toBe(12);
    expect(MIS_TFS_BY_MARKET.CRYPTO).toContain("1m");
    expect(MIS_TFS_BY_MARKET.CRYPTO).toContain("1d");
  });

  it("legacy MIS_FALLBACK_TFS alias matches MIS_TFS_BY_MARKET", () => {
    // Both exports must be the same object so consumers can pick either name.
    expect(MIS_FALLBACK_TFS).toBe(MIS_TFS_BY_MARKET);
  });

  it("every advertised TF must be in the canonical TF whitelist", () => {
    // Defense-in-depth: catch any future typo (e.g. "1H" instead of "1h").
    const CANONICAL = new Set([
      "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d",
    ]);
    for (const [market, tfs] of Object.entries(MIS_TFS_BY_MARKET)) {
      for (const tf of tfs) {
        expect(CANONICAL.has(tf), `${market} → ${tf}`).toBe(true);
      }
    }
  });
});
