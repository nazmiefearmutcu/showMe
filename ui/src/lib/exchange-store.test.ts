import { beforeEach, describe, expect, it, vi } from "vitest";
import { useExchangeStore } from "./exchange-store";
import { useBotsSupervisionStore } from "./bots-supervision-store";

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
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
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

  // ─── C9 (FIX_CONTRACT) — dependentBots + cross-store invalidation ────
  it("dependentBots reads /api/exchange/credentials/{id}/dependents", async () => {
    mockSidecar.mockResolvedValueOnce({
      credential_id: "abc",
      bot_count: 4,
      bot_ids: ["b1", "b2", "b3", "b4"],
    });
    const r = await useExchangeStore.getState().dependentBots("abc");
    expect(r.bot_count).toBe(4);
    expect(r.bot_ids).toEqual(["b1", "b2", "b3", "b4"]);
    expect(mockSidecar.mock.calls[0][0]).toBe("/api/exchange/credentials/abc/dependents");
  });

  it("dependentBots falls back to /api/bots client filter on 404", async () => {
    // First call (the dedicated endpoint) errors.
    mockSidecar.mockRejectedValueOnce(new Error("404"));
    // Second call (/api/bots fallback) returns two matching bots.
    mockSidecar.mockResolvedValueOnce({
      records: [
        { id: "b1", credential_id: "abc" },
        { id: "b2", credential_id: "xyz" },
        { id: "b3", credential_id: "abc" },
      ],
    });
    const r = await useExchangeStore.getState().dependentBots("abc");
    expect(r.bot_count).toBe(2);
    expect(r.bot_ids).toEqual(["b1", "b3"]);
  });

  it("deleteCredential forwards force=true and invalidates supervision store", async () => {
    // The DELETE call + the loadCredentials reload + the bots reload.
    mockSidecar.mockResolvedValueOnce({ ok: true });   // DELETE
    mockSidecar.mockResolvedValueOnce({ records: [] }); // loadCredentials
    // loadAll fans out to two fetches:
    mockSidecar.mockResolvedValueOnce({ records: [] }); // bots
    mockSidecar.mockResolvedValueOnce({ generated_at: "x", signals: [] }); // feed

    const ok = await useExchangeStore.getState().deleteCredential("abc", { force: true });
    expect(ok).toBe(true);
    const firstCall = mockSidecar.mock.calls[0];
    expect(firstCall[0]).toBe("/api/exchange/credentials/abc?force=true");
    expect((firstCall[1] as RequestInit).method).toBe("DELETE");
    // Supervision store was refreshed (loadAll called) — check via call ordering.
    expect(mockSidecar.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("deleteCredential without opts omits the force query param", async () => {
    mockSidecar.mockResolvedValueOnce({ ok: true });
    mockSidecar.mockResolvedValueOnce({ records: [] });
    mockSidecar.mockResolvedValueOnce({ records: [] });
    mockSidecar.mockResolvedValueOnce({ generated_at: "x", signals: [] });

    await useExchangeStore.getState().deleteCredential("abc");
    expect(mockSidecar.mock.calls[0][0]).toBe("/api/exchange/credentials/abc");
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
