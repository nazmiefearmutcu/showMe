import { describe, expect, it } from "vitest";
import { parseCandidateText } from "./agent";

describe("parseCandidateText", () => {
  it("accepts comma, semicolon and newline separated symbols", () => {
    expect(parseCandidateText("btcusdt, AAPL\nmsft; eurusd")).toEqual([
      "BTCUSDT",
      "AAPL",
      "MSFT",
      "EURUSD",
    ]);
  });
});
