import { describe, expect, it } from "vitest";
import { parseRoute } from "./router";

describe("parseRoute", () => {
  it("treats empty hash as welcome", () => {
    expect(parseRoute("")).toEqual({ kind: "welcome" });
    expect(parseRoute("#")).toEqual({ kind: "welcome" });
    expect(parseRoute("#/")).toEqual({ kind: "welcome" });
  });

  it("parses preferences with optional section", () => {
    expect(parseRoute("#/preferences")).toEqual({
      kind: "preferences",
      section: undefined,
    });
    expect(parseRoute("#/preferences/data")).toEqual({
      kind: "preferences",
      section: "data",
    });
  });

  it("parses fn/<CODE> upper-cased", () => {
    expect(parseRoute("#/fn/des")).toEqual({ kind: "function", code: "DES" });
    expect(parseRoute("#/fn/EQS")).toEqual({ kind: "function", code: "EQS" });
  });

  it("parses symbol-bound functions", () => {
    expect(parseRoute("#/symbol/aapl/fa")).toEqual({
      kind: "function",
      code: "FA",
      symbol: "aapl",
    });
  });

  it("returns not-found for garbage paths", () => {
    expect(parseRoute("#/totally/not/a/route")).toEqual({
      kind: "not-found",
      raw: "totally/not/a/route",
    });
  });
});
