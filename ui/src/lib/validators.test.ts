/**
 * Validator regression tests (FIX_CONTRACT C10).
 */
import { describe, expect, it } from "vitest";
import {
  clampTickInterval,
  duplicateAliasIndices,
  isKnownTimeframe,
  normalizeSymbol,
  SYMBOL_RE,
  validateOperand,
  validateSymbol,
} from "./validators";

describe("validateSymbol", () => {
  it("returns null for canonical BASE/QUOTE", () => {
    expect(validateSymbol("BTC/USDT")).toBeNull();
    expect(validateSymbol("ETH/USD")).toBeNull();
    expect(validateSymbol("AAVE/BTC")).toBeNull();
  });

  it("trims and uppercases before comparing", () => {
    expect(validateSymbol("  btc/usdt  ")).toBeNull();
    expect(validateSymbol("eth/usdt")).toBeNull();
  });

  it("rejects whitespace-only input", () => {
    expect(validateSymbol("   ")).toBe("Sembol gerekli.");
    expect(validateSymbol("")).toBe("Sembol gerekli.");
    expect(validateSymbol("\t\n")).not.toBeNull();
  });

  it("rejects shape that is not BASE/QUOTE", () => {
    expect(validateSymbol("BTC-USDT")).toBe("Format: BASE/QUOTE (ör. BTC/USDT).");
    expect(validateSymbol("BTCUSDT")).toBe("Format: BASE/QUOTE (ör. BTC/USDT).");
    expect(validateSymbol("BTC")).toBe("Format: BASE/QUOTE (ör. BTC/USDT).");
    expect(validateSymbol("/USDT")).toBe("Format: BASE/QUOTE (ör. BTC/USDT).");
    expect(validateSymbol("BTC/")).toBe("Format: BASE/QUOTE (ör. BTC/USDT).");
  });

  it("rejects control characters / newlines", () => {
    expect(validateSymbol("BTC\n/USDT")).not.toBeNull();
    expect(validateSymbol("BTC\t/USDT")).not.toBeNull();
  });

  it("SYMBOL_RE only matches uppercase alnum BASE/QUOTE", () => {
    expect(SYMBOL_RE.test("BTC/USDT")).toBe(true);
    expect(SYMBOL_RE.test("btc/usdt")).toBe(false);
    expect(SYMBOL_RE.test("BTC/USDT/EXTRA")).toBe(false);
  });
});

describe("normalizeSymbol", () => {
  it("uppercases without trimming whitespace mid-word", () => {
    expect(normalizeSymbol("btc/usdt")).toBe("BTC/USDT");
  });

  it("handles null/undefined safely", () => {
    expect(normalizeSymbol("")).toBe("");
    expect(normalizeSymbol(undefined as unknown as string)).toBe("");
  });
});

describe("clampTickInterval", () => {
  it("returns fallback for empty string", () => {
    expect(clampTickInterval("")).toBe(60);
    expect(clampTickInterval("", 30)).toBe(30);
  });

  it("returns fallback for non-numeric", () => {
    expect(clampTickInterval("abc")).toBe(60);
    expect(clampTickInterval("NaN")).toBe(60);
  });

  it("clamps below-min to 5", () => {
    expect(clampTickInterval("0")).toBe(5);
    expect(clampTickInterval("-100")).toBe(5);
    expect(clampTickInterval(-5)).toBe(5);
  });

  it("clamps above-max to 3600", () => {
    expect(clampTickInterval("9999")).toBe(3600);
    expect(clampTickInterval(99999)).toBe(3600);
  });

  it("rounds decimals", () => {
    expect(clampTickInterval("60.7")).toBe(61);
    expect(clampTickInterval("59.4")).toBe(59);
  });

  it("preserves canonical values", () => {
    expect(clampTickInterval("60")).toBe(60);
    expect(clampTickInterval(120)).toBe(120);
    expect(clampTickInterval("3600")).toBe(3600);
  });
});

describe("isKnownTimeframe", () => {
  it("accepts the canonical 6", () => {
    for (const tf of ["1m", "5m", "15m", "1h", "4h", "1d"]) {
      expect(isKnownTimeframe(tf)).toBe(true);
    }
  });

  it("rejects unknown / legacy timeframes", () => {
    expect(isKnownTimeframe("30m")).toBe(false);
    expect(isKnownTimeframe("2h")).toBe(false);
    expect(isKnownTimeframe("")).toBe(false);
    expect(isKnownTimeframe(undefined)).toBe(false);
    expect(isKnownTimeframe(null)).toBe(false);
  });
});

describe("validateOperand", () => {
  const aliases = ["rsi_1", "ema_fast", "close", "open"];

  it("accepts valid literal:<number>", () => {
    expect(validateOperand("literal:30", aliases)).toBeNull();
    expect(validateOperand("literal:-15.5", aliases)).toBeNull();
    expect(validateOperand("literal:0", aliases)).toBeNull();
  });

  it("flags literal without numeric tail", () => {
    expect(validateOperand("literal:", aliases)).not.toBeNull();
    expect(validateOperand("literal:abc", aliases)).not.toBeNull();
  });

  it("hints when user typed a bare number", () => {
    const err = validateOperand("30", aliases);
    expect(err).toMatch(/literal/);
    expect(validateOperand("-1.5", aliases)).toMatch(/literal/);
  });

  it("accepts known aliases", () => {
    expect(validateOperand("rsi_1", aliases)).toBeNull();
    expect(validateOperand("close", aliases)).toBeNull();
  });

  it("rejects unknown alias", () => {
    expect(validateOperand("unknown_x", aliases)).toMatch(/Bilinmeyen/);
  });

  it("rejects empty operand", () => {
    expect(validateOperand("", aliases)).toBe("Operand boş olamaz.");
    expect(validateOperand("   ", aliases)).toBe("Operand boş olamaz.");
  });
});

describe("duplicateAliasIndices", () => {
  it("returns empty set on unique aliases", () => {
    const dups = duplicateAliasIndices(["a", "b", "c"]);
    expect(dups.size).toBe(0);
  });

  it("flags BOTH occurrences of a duplicate", () => {
    const dups = duplicateAliasIndices(["rsi_1", "ema", "rsi_1"]);
    expect(dups.has(0)).toBe(true);
    expect(dups.has(2)).toBe(true);
    expect(dups.has(1)).toBe(false);
  });

  it("ignores empty/whitespace aliases", () => {
    const dups = duplicateAliasIndices(["", "  ", ""]);
    expect(dups.size).toBe(0);
  });

  it("handles three-way collision", () => {
    const dups = duplicateAliasIndices(["x", "x", "x"]);
    expect(dups.size).toBe(3);
  });
});
