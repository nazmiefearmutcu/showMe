import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchQuote } from "./quotes";

beforeEach(() => {
  vi.spyOn(globalThis, "fetch" as never);
});

afterEach(() => vi.restoreAllMocks());

function mockHealth() {
  (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => ({ ok: true }),
  } as unknown as Response);
}

describe("fetchQuote", () => {
  it("loads normalized quote snapshots from the sidecar", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        data: {
          symbol: "AAPL",
          asset_class: "EQUITY",
          last: 200,
          price: 200,
          previous_close: 195,
          change_pct: 2.56,
          volume: 10_000_000,
          bid: null,
          ask: null,
          source: "yahoo_chart",
          provider_symbol: "AAPL",
          currency: "USD",
          fetched_at: "2026-05-01T12:00:00Z",
        },
      }),
    } as unknown as Response);

    const quote = await fetchQuote("aapl");

    expect(quote.symbol).toBe("AAPL");
    expect(quote.last).toBe(200);
    expect(quote.source).toBe("yahoo_chart");
    expect(String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[1][0])).toContain(
      "/api/quote/AAPL",
    );
  });

  it("rejects empty symbols before hitting the network", async () => {
    await expect(fetchQuote(" ")).rejects.toThrow("empty symbol");
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});
