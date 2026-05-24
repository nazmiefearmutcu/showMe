/**
 * Strategy-store cascade delete (C9 fragment) — verifies the dependents
 * endpoint is queried and force=true is used when bots are bound, with
 * defensive fallback when the endpoint isn't deployed yet.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useStrategyStore } from "./strategy-store";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch as never);

// Minimal sidecar mock so sidecarFetch's `waitForSidecarReady` succeeds.
vi.mock("./tauri", () => ({
  invoke: vi.fn(async () => ({ port: 8765 })),
  listen: vi.fn(async () => () => {}),
  isInTauri: () => false,
}));

beforeEach(() => {
  mockFetch.mockReset();
  useStrategyStore.setState({
    strategies: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, removing: false, error: null, lastPreview: null,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function makeOk(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    json: async () => body,
    headers: new Headers(),
  } as unknown as Response;
}

function makeErr(status: number): Response {
  return {
    ok: false,
    status,
    statusText: "Not Found",
    json: async () => ({}),
    headers: new Headers(),
  } as unknown as Response;
}

describe("strategy-store cascade delete", () => {
  it("queries dependents and uses force=true when bots bound", async () => {
    // 1: health probe; 2: dependents fetch returns count>0; 3: DELETE; 4: loadList.
    mockFetch
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health
      .mockResolvedValueOnce(makeOk({ bot_count: 2, bot_ids: ["b1", "b2"] }))
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health for DELETE
      .mockResolvedValueOnce(makeOk({ ok: true }))                // DELETE itself
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health for loadList
      .mockResolvedValueOnce(makeOk({ records: [] }));            // loadList result

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const ok = await useStrategyStore.getState().remove("strat-1");

    expect(confirmSpy).toHaveBeenCalled();
    expect(confirmSpy.mock.calls[0][0]).toMatch(/2 bot/);
    expect(ok).toBe(true);
    // Verify the DELETE URL includes force=true.
    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    const deleteCall = calls.find((u) => u.includes("/api/strategies/strat-1") && u.includes("force=true"));
    expect(deleteCall).toBeDefined();
  });

  it("user-cancel aborts the delete", async () => {
    mockFetch
      .mockResolvedValueOnce(makeOk({ ok: true }))                                          // health
      .mockResolvedValueOnce(makeOk({ bot_count: 1, bot_ids: ["b1"] }));                    // dependents

    vi.spyOn(window, "confirm").mockReturnValue(false);
    const ok = await useStrategyStore.getState().remove("strat-1");

    expect(ok).toBe(false);
    // Only health + dependents — no DELETE.
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it("falls back to legacy DELETE when dependents endpoint is 404", async () => {
    mockFetch
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health
      .mockResolvedValueOnce(makeErr(404))                        // dependents not deployed
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health for DELETE
      .mockResolvedValueOnce(makeOk({ ok: true }))                // DELETE
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health for loadList
      .mockResolvedValueOnce(makeOk({ records: [] }));            // loadList result

    const confirmSpy = vi.spyOn(window, "confirm");
    const ok = await useStrategyStore.getState().remove("strat-1");

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(ok).toBe(true);
    const calls = mockFetch.mock.calls.map((c) => c[0] as string);
    const deleteCall = calls.find((u) => u.endsWith("/api/strategies/strat-1"));
    expect(deleteCall).toBeDefined();
  });

  it("removing flag flips during delete", async () => {
    mockFetch
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health
      .mockResolvedValueOnce(makeOk({ bot_count: 0, bot_ids: [] })) // dependents
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health
      .mockResolvedValueOnce(makeOk({ ok: true }))                // DELETE
      .mockResolvedValueOnce(makeOk({ ok: true }))                // health
      .mockResolvedValueOnce(makeOk({ records: [] }));            // loadList

    const p = useStrategyStore.getState().remove("strat-1");
    // Removing flips synchronously to true.
    expect(useStrategyStore.getState().removing).toBe(true);
    await p;
    expect(useStrategyStore.getState().removing).toBe(false);
  });
});
