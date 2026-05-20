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
  it("matches exact code with the highest score", () => {
    expect(fuzzyScore(ITEMS[0], "xsen")?.score).toBe(1000);
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
});
