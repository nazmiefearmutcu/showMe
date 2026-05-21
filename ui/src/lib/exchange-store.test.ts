import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useExchangeStore } from "./exchange-store";

const ORIGINAL_FETCH = global.fetch;

function mockFetch(responses: Record<string, unknown>): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [pattern, body] of Object.entries(responses)) {
      if (url.includes(pattern)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }
    return new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
});

describe("exchange-store", () => {
  it("loadCatalog populates entries", async () => {
    global.fetch = mockFetch({
      "/api/exchange/catalog": [
        { id: "binance", display_name: "Binance", aliases: [], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [], capabilities: {}, ccxt_id: "binance", notes: "" },
      ],
    });
    await useExchangeStore.getState().loadCatalog();
    const cat = useExchangeStore.getState().catalog;
    expect(cat.length).toBe(1);
    expect(cat[0].id).toBe("binance");
  });

  it("loadCredentials populates records", async () => {
    global.fetch = mockFetch({
      "/api/exchange/credentials": {
        records: [
          { id: "abc", exchange_id: "binance", account_label: "main", permissions: ["read"], created_at: "2026-05-21T10:00:00Z" },
        ],
      },
    });
    await useExchangeStore.getState().loadCredentials();
    expect(useExchangeStore.getState().credentials.length).toBe(1);
  });

  it("saveCredential POSTs and re-loads", async () => {
    const posted: unknown[] = [];
    global.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("/api/exchange/credentials") && init?.method === "POST") {
        posted.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({
          id: "new-id", exchange_id: "binance", account_label: "main",
          permissions: ["read"], created_at: "2026-05-21",
        }), { status: 200 });
      }
      if (url.endsWith("/api/exchange/credentials")) {
        return new Response(JSON.stringify({ records: [] }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    const ok = await useExchangeStore.getState().saveCredential({
      exchange_id: "binance",
      account_label: "main",
      secrets: { api_key: "k", api_secret: "s" },
      permissions: ["read"],
      skip_test: true,
    });
    expect(ok).toBe(true);
    expect((posted[0] as { exchange_id: string }).exchange_id).toBe("binance");
  });

  it("testCredential returns ok:false on backend failure", async () => {
    global.fetch = mockFetch({
      "/test": { ok: false, error: "boom" },
    });
    const r = await useExchangeStore.getState().testCredential("any-id");
    expect(r.ok).toBe(false);
    expect(r.error).toBe("boom");
  });

  it("filterCatalog searches across name + aliases", () => {
    useExchangeStore.setState({
      catalog: [
        { id: "binance", display_name: "Binance", aliases: ["binance.com"], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: [], optional: [], capabilities: {}, ccxt_id: "binance", notes: "" },
        { id: "kraken", display_name: "Kraken", aliases: [], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: [], optional: [], capabilities: {}, ccxt_id: "kraken", notes: "" },
      ],
    });
    const hits = useExchangeStore.getState().filterCatalog({
      query: "binance.com", assetClasses: [], regions: [],
    });
    expect(hits.map((e) => e.id)).toEqual(["binance"]);
  });
});
