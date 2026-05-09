import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runFunction, FunctionCallError } from "./functions";

const successPayload = {
  code: "PORT",
  instrument: null,
  data: { positions: [], totals: { market_value: 0 } },
  metadata: {},
  fetched_at: "2026-04-30T12:00:00Z",
  sources: ["function"],
  warnings: [],
  elapsed_ms: 12.3,
};

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

function functionFetchCall() {
  const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
  const call = calls.find(([url]) => String(url).includes("/api/fn/"));
  if (!call) throw new Error("missing function fetch call");
  return call;
}

describe("runFunction", () => {
  it("issues a GET when only primitive params present", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => successPayload,
    } as unknown as Response);
    const res = await runFunction("PORT", { params: { limit: 50 } });
    expect(res.code).toBe("PORT");
    const call = functionFetchCall();
    const url = call[0] as string;
    expect(url).toContain("/api/fn/PORT");
    expect(url).toContain("limit=50");
    expect(call[1]?.method).toBeUndefined();
  });

  it("uses POST when params contain a nested object", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => successPayload,
    } as unknown as Response);
    await runFunction("STRS", {
      params: { symbol_shocks: { BTCUSDT: -0.5 } },
    });
    const call = functionFetchCall();
    expect(call[1]?.method).toBe("POST");
    const body = JSON.parse(call[1]?.body as string);
    expect(body).toEqual({ symbol_shocks: { BTCUSDT: -0.5 } });
  });

  it("fills elapsed_ms when the backend leaves it empty", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ ...successPayload, elapsed_ms: null }),
    } as unknown as Response);
    const res = await runFunction("HP", { symbol: "AAPL" });
    expect(res.elapsed_ms).toBeGreaterThanOrEqual(0);
  });

  it("throws FunctionCallError on non-2xx", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
      text: async () => "{\"detail\":\"unknown function ZZZ\"}",
    } as unknown as Response);
    await expect(runFunction("ZZZ")).rejects.toBeInstanceOf(FunctionCallError);
  });

  it("retries transient network failures", async () => {
    mockHealth();
    (globalThis.fetch as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new TypeError("Load failed"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ...successPayload, code: "CN" }),
      } as unknown as Response);
    const res = await runFunction("CN", { symbol: "BTCUSDT" });
    expect(res.code).toBe("CN");
    const functionCalls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([url]) =>
      String(url).includes("/api/fn/"),
    );
    expect(functionCalls).toHaveLength(2);
  });

  it("propagates abort signals", async () => {
    mockHealth();
    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(abortError);
    await expect(runFunction("PORT")).rejects.toThrow("aborted");
  });
});
