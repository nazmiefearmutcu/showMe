import { describe, expect, it } from "vitest";
import { fuzzyRank, fuzzyScore, type FuzzyTarget } from "./fuzzy";

const ITEMS: FuzzyTarget[] = [
  { code: "XSEN", name: "X Sentiment AI", category: "news" },
  { code: "ASK", name: "Ask", category: "screen" },
  { code: "PORT", name: "Portfolio", category: "portfolio" },
  { code: "BTMM", name: "Banker Trends", category: "macro" },
  { code: "BTFW", name: "Banker Forward", category: "macro" },
];

describe("fuzzyScore", () => {
  it("matches exact code with the highest score (QA-2026-05-23: bumped to 2000)", () => {
    expect(fuzzyScore(ITEMS[0], "xsen")?.score).toBe(2000);
  });

  it("matches code prefix above substring", () => {
    const port = fuzzyScore(ITEMS[2], "po")?.score ?? 0;
    const btmm = fuzzyScore(ITEMS[3], "po")?.score ?? 0;
    expect(port).toBeGreaterThan(btmm);
  });

  it("matches name token prefix when code does not contain query", () => {
    const port = fuzzyScore(ITEMS[2], "portf")?.score ?? 0;
    expect(port).toBeGreaterThanOrEqual(700);
  });

  it("handles fuzzy subsequence (UI-INT-04 P2): 'xsentai' finds 'XSEN X Sentiment AI'", () => {
    const result = fuzzyScore(ITEMS[0], "xsentai");
    expect(result).not.toBeNull();
    expect(result!.score).toBeGreaterThanOrEqual(200);
  });

  it("returns null when nothing matches", () => {
    expect(fuzzyScore(ITEMS[0], "zzz")).toBeNull();
  });

  it("QA-2026-05-23: exact code 'DES' beats subsequence-match 'DDM' for query 'DES'", () => {
    const DES: FuzzyTarget = { code: "DES", name: "Description", category: "equity" };
    const DDM: FuzzyTarget = {
      code: "DDM",
      name: "Dividend Discount Model",
      category: "equity",
    };
    const desScore = fuzzyScore(DES, "DES")?.score ?? 0;
    const ddmScore = fuzzyScore(DDM, "DES")?.score ?? 0;
    expect(desScore).toBeGreaterThan(ddmScore);
    expect(desScore).toBe(2000);
  });

  it("QA-2026-05-23: multi-word query requires every token to match", () => {
    const GP: FuzzyTarget = { code: "GP", name: "Generic Price", category: "chart" };
    const HP: FuzzyTarget = {
      code: "HP",
      name: "Historical Price",
      category: "chart",
    };
    expect(fuzzyScore(GP, "generic price")).not.toBeNull();
    // Single-token "price" matches both, multi-token "generic price" only GP.
    expect(fuzzyScore(HP, "generic price")).toBeNull();
    expect(fuzzyScore(GP, "price generic")).not.toBeNull(); // order-insensitive.
  });

  it("QA-2026-05-23: multi-word with no matching token returns null", () => {
    const GP: FuzzyTarget = { code: "GP", name: "Generic Price", category: "chart" };
    expect(fuzzyScore(GP, "generic zzzzzz")).toBeNull();
  });
});

describe("fuzzyRank", () => {
  it("returns recents on top of equally-ranked results", () => {
    const ranked = fuzzyRank(ITEMS, "bt", ["BTFW"]);
    expect(ranked[0].code).toBe("BTFW");
  });

  it("limits results", () => {
    const big: FuzzyTarget[] = Array.from({ length: 200 }, (_, i) => ({
      code: `CODE${i}`,
      name: `Function ${i}`,
      category: "test",
    }));
    expect(fuzzyRank(big, "code", [], 10)).toHaveLength(10);
  });

  it("QA-2026-05-23: 'DES' query returns Description (DES) as the top result", () => {
    const items: FuzzyTarget[] = [
      { code: "DDM", name: "Dividend Discount Model", category: "equity" },
      { code: "DEBT", name: "Debt Summary", category: "equity" },
      { code: "DES", name: "Description", category: "equity" },
      { code: "FA", name: "Financial Analysis", category: "equity" },
    ];
    const ranked = fuzzyRank(items, "DES");
    expect(ranked[0]?.code).toBe("DES");
  });

  it("QA-2026-05-23: 'generic price' multi-word query finds GP first", () => {
    const items: FuzzyTarget[] = [
      { code: "GP", name: "Generic Price", category: "chart" },
      { code: "HP", name: "Historical Price", category: "chart" },
      { code: "TP", name: "Trade Price Box", category: "chart" },
    ];
    const ranked = fuzzyRank(items, "generic price");
    expect(ranked[0]?.code).toBe("GP");
    expect(ranked).toHaveLength(1); // HP / TP filtered out — they don't match both tokens.
  });
});
