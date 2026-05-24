/**
 * Round 24 CRITICAL 3 — CONN duplicate-credential / double-submit regression.
 *
 * The audit's S5 finding: the "Bağlan" form's submit button had no
 * store-level guard, so a double-click pattern created two
 * POST /api/exchange/credentials rows for the same API key (and on
 * Binance/Coinbase the second 409'd silently, masking the duplicate).
 *
 * Also covers:
 *  - Per-credential delete guard (deleting Set).
 *  - Per-credential test guard (testing Set).
 *  - Per-credential upgrade guard (upgrading Set).
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  useExchangeStore,
  type CreateCredentialPayload,
} from "@/lib/exchange-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("@/lib/bots-supervision-store", () => ({
  useBotsSupervisionStore: { getState: () => ({ loadAll: vi.fn() }) },
}));

import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    saving: false,
    deleting: new Set<string>(),
    testing: new Set<string>(),
    upgrading: new Set<string>(),
    error: null,
  });
  mock.mockReset();
});

describe("CONN duplicate-guard — Round 24 CRITICAL 3", () => {
  it("two parallel saveCredential() calls fire ONE POST", async () => {
    let resolvePost!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolvePost = res; }));
    mock.mockResolvedValueOnce({ records: [] }); // loadCredentials

    const payload: CreateCredentialPayload = {
      exchange_id: "binance",
      account_label: "main",
      secrets: { api_key: "k", api_secret: "s" },
      permissions: ["read"],
    };
    const p1 = useExchangeStore.getState().saveCredential(payload);
    const p2 = useExchangeStore.getState().saveCredential(payload);

    // p2 short-circuits via `if (get().saving) return false`.
    expect(await p2).toBe(false);

    resolvePost({ id: "c-1", exchange_id: "binance", account_label: "main", permissions: ["read"], created_at: "x" });
    expect(await p1).toBe(true);
    // 1 POST + 1 loadCredentials = 2 calls (NOT 3 — no duplicate POST).
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("per-credential delete guard short-circuits the 2nd call", async () => {
    // 1st call: dependents lookup + DELETE + loadCredentials.
    mock.mockResolvedValueOnce({ bot_count: 0, bot_ids: [] }); // dependents (unused here, deleteCredential doesn't pre-flight)
    let resolveDelete!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolveDelete = res; }));
    mock.mockResolvedValueOnce({ records: [] });

    const p1 = useExchangeStore.getState().deleteCredential("c-1");
    // 2nd call before p1 completes — must short-circuit.
    const p2 = useExchangeStore.getState().deleteCredential("c-1");
    expect(await p2).toBe(false);

    resolveDelete({ ok: true });
    await p1;
    // Sanity: testing.has(c-1) for the OTHER credential id should be false.
    expect(useExchangeStore.getState().deleting.has("c-1")).toBe(false);
  });

  it("testCredential guard prevents parallel exchange pings for the same id", async () => {
    let resolveTest!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolveTest = res; }));

    const p1 = useExchangeStore.getState().testCredential("c-1");
    const p2 = useExchangeStore.getState().testCredential("c-1");
    expect(await p2).toEqual({ ok: false, error: "test_in_flight" });

    resolveTest({ ok: true, account: { balance: 0 } });
    expect(await p1).toEqual({ ok: true, account: { balance: 0 } });
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("testCredential on DIFFERENT ids run in parallel (per-row, not global)", async () => {
    let resolveA!: (v: unknown) => void;
    let resolveB!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolveA = res; }));
    mock.mockReturnValueOnce(new Promise((res) => { resolveB = res; }));

    const pA = useExchangeStore.getState().testCredential("c-A");
    const pB = useExchangeStore.getState().testCredential("c-B");

    resolveA({ ok: true });
    resolveB({ ok: true });
    expect(await pA).toEqual({ ok: true });
    expect(await pB).toEqual({ ok: true });
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("upgradeToTrade guard short-circuits double-PATCH on the same id", async () => {
    let resolvePatch!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolvePatch = res; }));
    mock.mockResolvedValueOnce({ records: [] }); // loadCredentials

    const p1 = useExchangeStore.getState().upgradeToTrade("c-1", "main");
    const p2 = useExchangeStore.getState().upgradeToTrade("c-1", "main");
    expect(await p2).toBe(false);

    resolvePatch({ id: "c-1", exchange_id: "binance", account_label: "main", permissions: ["read", "trade"], created_at: "x" });
    expect(await p1).toBe(true);
    // 1 PATCH + 1 loadCredentials = 2.
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("saving flag resets after error", async () => {
    mock.mockRejectedValueOnce(new Error("401 invalid_key"));
    await useExchangeStore.getState().saveCredential({
      exchange_id: "binance", account_label: "main",
      secrets: {}, permissions: ["read"],
    });
    expect(useExchangeStore.getState().saving).toBe(false);
    expect(useExchangeStore.getState().error).toMatch(/invalid_key/);
  });
});
