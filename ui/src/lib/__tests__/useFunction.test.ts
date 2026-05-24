/**
 * useFunction — flicker-fix contract (2026-05-24).
 *
 * Pins the new refresh semantics ported from
 * `panes/function_stub/index.tsx:276`:
 *
 *   1. Initial mount     : idle → loading → ok, data populates
 *   2. Auto-refetch      : ok → refreshing → ok, data REMAINS on screen
 *   3. Key change        : ok → loading → ok, data clears then repopulates
 *   4. Refetch error     : ok → refreshing → error, data REMAINS on screen
 *
 * Mocks `./functions` so the hook never tries to reach a sidecar, and
 * leaves `./tauri` real (jsdom resolves `isInTauri()` to false → the
 * sidecar-wait guard is bypassed).
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FunctionCallResult } from "../functions";

// Hoisted mock state — `vi.mock` factories run BEFORE module-level
// initializers, so `runFunctionMock` must live inside `vi.hoisted` to be
// available when the factory executes.
const { runFunctionMock } = vi.hoisted(() => ({
  runFunctionMock: vi.fn<
    (code: string, opts?: unknown) => Promise<unknown>
  >(),
}));

vi.mock("../functions", async () => {
  // Keep FunctionCallError real-ish (we don't use it here) but swap
  // runFunction for our spy.
  const actual = await vi.importActual<typeof import("../functions")>(
    "../functions",
  );
  return {
    ...actual,
    runFunction: runFunctionMock,
  };
});

// Import AFTER vi.mock so the hook picks up the mocked runFunction.
import { useFunction } from "../useFunction";

function payload<T = unknown>(tag: string, data: T): FunctionCallResult<T> {
  return {
    code: tag,
    instrument: null,
    data,
    metadata: {},
    fetched_at: new Date().toISOString(),
    sources: [],
    warnings: [],
    elapsed_ms: 1,
  };
}

beforeEach(() => {
  runFunctionMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useFunction — flicker fix", () => {
  it("initial mount: idle → loading → ok, data populates", async () => {
    runFunctionMock.mockResolvedValueOnce(payload("WEI", { v: 1 }));

    const { result } = renderHook(() =>
      useFunction({ code: "WEI", symbol: "SPX" }),
    );

    // The very first render synchronously commits the "loading" state from
    // the effect — by the time renderHook returns, state has already moved
    // off "idle".
    expect(["idle", "loading"]).toContain(result.current.state);
    expect(result.current.data).toBeUndefined();

    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ v: 1 });
    expect(runFunctionMock).toHaveBeenCalledTimes(1);
  });

  it("refetch (same key): ok → refreshing → ok, data REMAINS visible", async () => {
    runFunctionMock
      .mockResolvedValueOnce(payload("WEI", { v: 1 }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(payload("WEI", { v: 2 })), 50),
          ),
      );

    const { result } = renderHook(() =>
      useFunction({ code: "WEI", symbol: "SPX" }),
    );
    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ v: 1 });

    // Snapshot the first payload reference so we can assert it stays put
    // during the in-flight refresh.
    const firstData = result.current.data;

    act(() => {
      result.current.refetch();
    });

    // CRITICAL: state must be "refreshing", NOT "loading", and data is
    // still the first payload (no skeleton flash).
    expect(result.current.state).toBe("refreshing");
    expect(result.current.data).toBe(firstData);
    expect(result.current.data?.data).toEqual({ v: 1 });

    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ v: 2 });
    expect(runFunctionMock).toHaveBeenCalledTimes(2);
  });

  it("key change (symbol switch): ok → loading → ok, data clears then repopulates", async () => {
    runFunctionMock
      .mockResolvedValueOnce(payload("HP", { sym: "AAPL" }))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve(payload("HP", { sym: "MSFT" })), 50),
          ),
      );

    const { result, rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useFunction({ code: "HP", symbol }),
      { initialProps: { symbol: "AAPL" } },
    );
    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ sym: "AAPL" });

    // Switch symbol → key changes → must hard-load (skeleton path).
    rerender({ symbol: "MSFT" });

    expect(result.current.state).toBe("loading");
    expect(result.current.data).toBeUndefined();

    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ sym: "MSFT" });
  });

  it("refetch error: ok → refreshing → error, data REMAINS visible", async () => {
    runFunctionMock
      .mockResolvedValueOnce(payload("PORT", { equity: 100 }))
      .mockImplementationOnce(
        () =>
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error("network down")), 50),
          ),
      );

    const { result } = renderHook(() => useFunction({ code: "PORT" }));
    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ equity: 100 });
    const firstData = result.current.data;

    act(() => {
      result.current.refetch();
    });

    expect(result.current.state).toBe("refreshing");
    expect(result.current.data).toBe(firstData);

    await waitFor(() => expect(result.current.state).toBe("error"));
    // Data MUST stay on screen so the user sees stale + error pill, not
    // an empty wipe.
    expect(result.current.data).toBe(firstData);
    expect(result.current.data?.data).toEqual({ equity: 100 });
    expect(result.current.error?.message).toBe("network down");
  });

  it("refetch right after an initial error is treated as initial-load (not refresh)", async () => {
    // Belt-and-suspenders: the refresh branch is gated on `data !== undefined`
    // so a failed first fetch followed by refetch still flips to "loading"
    // (no stale data to keep).
    runFunctionMock
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(payload("WEI", { v: 1 }));

    const { result } = renderHook(() => useFunction({ code: "WEI" }));
    await waitFor(() => expect(result.current.state).toBe("error"));
    expect(result.current.data).toBeUndefined();

    act(() => {
      result.current.refetch();
    });

    // No prior data → must fall through to the "loading" path.
    expect(result.current.state).toBe("loading");

    await waitFor(() => expect(result.current.state).toBe("ok"));
    expect(result.current.data?.data).toEqual({ v: 1 });
  });

  it("enabled=false short-circuits to idle without calling runFunction", async () => {
    const { result } = renderHook(() =>
      useFunction({ code: "WEI", enabled: false }),
    );
    expect(result.current.state).toBe("idle");
    expect(runFunctionMock).not.toHaveBeenCalled();
  });
});
