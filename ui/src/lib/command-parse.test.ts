/**
 * Lane L2 — command grammar parser (campaign 2026-09-11).
 *
 * Pins the frozen `ParsedCommand` matrix: GO stripping, both token orders
 * of the security+function grammar, verb detection, and the no-catalog
 * default (nothing is a code/symbol without predicates).
 */
import { describe, expect, it } from "vitest";
import { makeCommandPredicates, parseCommandInput } from "./command-parse";

const opts = makeCommandPredicates({
  codes: ["GP", "DES", "FA"],
  symbols: ["MSFT", "AAPL", "NVDA"],
});

describe("parseCommandInput — empty + GO", () => {
  it("empty and whitespace → empty", () => {
    expect(parseCommandInput("").kind).toBe("empty");
    expect(parseCommandInput("   ").kind).toBe("empty");
  });

  it("a lone GO / <GO> is an empty command with the terminator consumed", () => {
    expect(parseCommandInput("GO").kind).toBe("empty");
    expect(parseCommandInput("<go>").kind).toBe("empty");
  });

  it("strips a trailing GO token case-insensitively and sets go:true", () => {
    expect(parseCommandInput("MSFT GO", opts)).toEqual({
      kind: "security",
      symbol: "MSFT",
      go: true,
    });
    expect(parseCommandInput("MSFT <go>", opts)).toEqual({
      kind: "security",
      symbol: "MSFT",
      go: true,
    });
    expect(parseCommandInput("GP <GO>", opts)).toEqual({
      kind: "function",
      code: "GP",
      go: true,
    });
    expect(parseCommandInput("MSFT GP GO", opts)).toEqual({
      kind: "security-function",
      symbol: "MSFT",
      code: "GP",
      go: true,
    });
  });

  it("GO only terminates as the LAST token", () => {
    expect(parseCommandInput("GO MSFT", opts).kind).toBe("unknown");
  });
});

describe("parseCommandInput — single token", () => {
  it("known code → function, uppercased (case-insensitive)", () => {
    expect(parseCommandInput("GP", opts)).toEqual({
      kind: "function",
      code: "GP",
      go: false,
    });
    expect(parseCommandInput("gp", opts)).toEqual({
      kind: "function",
      code: "GP",
      go: false,
    });
  });

  it("known symbol → security", () => {
    expect(parseCommandInput("MSFT", opts)).toEqual({
      kind: "security",
      symbol: "MSFT",
      go: false,
    });
    expect(parseCommandInput("msft", opts)).toEqual({
      kind: "security",
      symbol: "MSFT",
      go: false,
    });
  });

  it("code wins when a token is both a code and a symbol", () => {
    const ambiguous = makeCommandPredicates({ codes: ["AAPL"], symbols: ["AAPL"] });
    expect(parseCommandInput("AAPL", ambiguous)).toEqual({
      kind: "function",
      code: "AAPL",
      go: false,
    });
  });

  it("lowercase word that is neither → verb", () => {
    expect(parseCommandInput("theme", opts)).toEqual({
      kind: "verb",
      verb: "theme",
      go: false,
    });
    expect(parseCommandInput("theme GO", opts)).toEqual({
      kind: "verb",
      verb: "theme",
      go: true,
    });
  });

  it("uppercase unknown token → unknown (verbs must be lowercase)", () => {
    expect(parseCommandInput("ZZZZ", opts)).toEqual({
      kind: "unknown",
      input: "ZZZZ",
    });
  });

  it("keeps the trimmed input on unknown", () => {
    expect(parseCommandInput("   foo/bar   ", opts)).toEqual({
      kind: "unknown",
      input: "foo/bar",
    });
  });
});

describe("parseCommandInput — security + function grammar", () => {
  it("CODE SYMBOL (MSFT GP / GP MSFT)", () => {
    expect(parseCommandInput("MSFT GP", opts)).toEqual({
      kind: "security-function",
      symbol: "MSFT",
      code: "GP",
      go: false,
    });
    expect(parseCommandInput("GP MSFT", opts)).toEqual({
      kind: "security-function",
      symbol: "MSFT",
      code: "GP",
      go: false,
    });
  });

  it("DES MSFT and MSFT DES both resolve", () => {
    expect(parseCommandInput("DES MSFT", opts)).toEqual({
      kind: "security-function",
      symbol: "MSFT",
      code: "DES",
      go: false,
    });
    expect(parseCommandInput("MSFT DES", opts)).toEqual({
      kind: "security-function",
      symbol: "MSFT",
      code: "DES",
      go: false,
    });
  });

  it("code + code and symbol + symbol are unknown", () => {
    expect(parseCommandInput("GP DES", opts).kind).toBe("unknown");
    expect(parseCommandInput("MSFT AAPL", opts).kind).toBe("unknown");
  });

  it("symbol + unknown and code + unknown are unknown", () => {
    expect(parseCommandInput("MSFT ZZZ", opts).kind).toBe("unknown");
    expect(parseCommandInput("GP ZZZ", opts).kind).toBe("unknown");
  });
});

describe("parseCommandInput — arity + defaults", () => {
  it("three or more tokens → unknown", () => {
    expect(parseCommandInput("MSFT GP EXTRA", opts).kind).toBe("unknown");
    expect(parseCommandInput("a b c d").kind).toBe("unknown");
  });

  it("without opts no token is a code or symbol (no catalog → no guessing)", () => {
    expect(parseCommandInput("MSFT").kind).toBe("unknown");
    expect(parseCommandInput("GP").kind).toBe("unknown");
    expect(parseCommandInput("MSFT GP").kind).toBe("unknown");
  });

  it("makeCommandPredicates is case-insensitive on both sides", () => {
    const lowercaseCatalog = makeCommandPredicates({
      codes: ["gp"],
      symbols: ["msft"],
    });
    expect(lowercaseCatalog.isCode("GP")).toBe(true);
    expect(lowercaseCatalog.isCode("gp")).toBe(true);
    expect(lowercaseCatalog.isSymbol("Msft")).toBe(true);
    expect(lowercaseCatalog.isCode("MSFT")).toBe(false);
  });
});
