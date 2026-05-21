import { beforeEach, describe, expect, it, vi } from "vitest";
import { useExchangeStore } from "./exchange-store";

// vi.mock must come BEFORE the imports that use it. vitest hoists vi.mock calls.
vi.mock("./sidecar", () => ({
  sidecarFetch: vi.fn(),
}));

import { sidecarFetch } from "./sidecar";
const mockSidecar = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
  mockSidecar.mockReset();
});

describe("exchange-store", () => {
  it("loadCatalog populates entries", async () => {
    mockSidecar.mockResolvedValueOnce([
      { id: "binance", display_name: "Binance", aliases: [], asset_classes: ["spot"], regions: ["global"], adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [], capabilities: {}, ccxt_id: "binance", notes: "" },
    ]);
    await useExchangeStore.getState().loadCatalog();
    expect(useExchangeStore.getState().catalog).toHaveLength(1);
    expect(useExchangeStore.getState().catalog[0].id).toBe("binance");
  });

  it("loadCredentials populates records", async () => {
    mockSidecar.mockResolvedValueOnce({
      records: [{ id: "abc", exchange_id: "binance", account_label: "main", permissions: ["read"], created_at: "2026-05-21T10:00:00Z" }],
    });
    await useExchangeStore.getState().loadCredentials();
    expect(useExchangeStore.getState().credentials).toHaveLength(1);
  });

  it("saveCredential POSTs and re-loads", async () => {
    // First call: POST returns the new credential.
    mockSidecar.mockResolvedValueOnce({
      id: "new-id", exchange_id: "binance", account_label: "main",
      permissions: ["read"], created_at: "2026-05-21",
    });
    // Second call: loadCredentials reload.
    mockSidecar.mockResolvedValueOnce({ records: [] });

    const ok = await useExchangeStore.getState().saveCredential({
      exchange_id: "binance",
      account_label: "main",
      secrets: { api_key: "k", api_secret: "s" },
      permissions: ["read"],
      skip_test: true,
    });
    expect(ok).toBe(true);
    // First call args check:
    const firstCall = mockSidecar.mock.calls[0];
    expect(firstCall[0]).toBe("/api/exchange/credentials");
    expect((firstCall[1] as RequestInit).method).toBe("POST");
    expect(JSON.parse(String((firstCall[1] as RequestInit).body))).toMatchObject({
      exchange_id: "binance",
    });
  });

  it("testCredential returns ok:false on backend failure", async () => {
    mockSidecar.mockResolvedValueOnce({ ok: false, error: "boom" });
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
