/**
 * Regression — audit S11.
 *
 * `useFunction` used `JSON.stringify(params ?? {})` to compute the dep key
 * for the fetch effect. JSON.stringify does NOT sort object keys, so a
 * parent re-render that spread / overrode the params object in a different
 * insertion order produced a different string — and the effect re-fired
 * even though the call was semantically identical.
 *
 * The fix sorts top-level keys before stringifying. This test pins the
 * contract by counting `runFunction` invocations when only the property
 * insertion order changes between renders.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { runFunctionMock } = vi.hoisted(() => ({
  runFunctionMock: vi.fn(),
}));

vi.mock("./functions", async () => {
  const actual = await vi.importActual<typeof import("./functions")>("./functions");
  return { ...actual, runFunction: runFunctionMock };
});

import { useFunction } from "./useFunction";

beforeEach(() => {
  runFunctionMock.mockReset();
  runFunctionMock.mockResolvedValue({
    code: "TST",
    instrument: null,
    data: { ok: true },
    metadata: {},
    fetched_at: new Date().toISOString(),
    sources: [],
    warnings: [],
    elapsed_ms: 1,
  });
});

afterEach(() => {
  runFunctionMock.mockReset();
});

describe("useFunction params dep is order-invariant (audit S11)", () => {
  it("does NOT refetch when only the key insertion order changes", async () => {
    const { rerender } = renderHook(
      ({ params }: { params: Record<string, unknown> }) =>
        useFunction({ code: "TST", symbol: "AAPL", params }),
      { initialProps: { params: { a: 1, b: 2, c: 3 } } },
    );
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));

    act(() => {
      // Different insertion order, identical content.
      rerender({ params: { c: 3, a: 1, b: 2 } });
    });

    // Give React a tick to settle.
    await new Promise((r) => setTimeout(r, 5));
    expect(runFunctionMock).toHaveBeenCalledTimes(1);
  });

  it("DOES refetch when a value actually changes", async () => {
    const { rerender } = renderHook(
      ({ params }: { params: Record<string, unknown> }) =>
        useFunction({ code: "TST", symbol: "AAPL", params }),
      { initialProps: { params: { a: 1, b: 2 } } },
    );
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));

    act(() => {
      rerender({ params: { a: 1, b: 99 } });
    });
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(2));
  });

  it("DOES refetch when symbol changes (key is part of fingerprint)", async () => {
    const { rerender } = renderHook(
      ({ symbol }: { symbol: string }) =>
        useFunction({ code: "TST", symbol, params: { a: 1 } }),
      { initialProps: { symbol: "AAPL" } },
    );
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));

    act(() => {
      rerender({ symbol: "MSFT" });
    });
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(2));
  });

  it("handles empty/undefined params without refetching on every render", async () => {
    const { rerender } = renderHook(
      ({ params }: { params?: Record<string, unknown> }) =>
        useFunction({ code: "TST", symbol: "AAPL", params }),
      { initialProps: { params: undefined as Record<string, unknown> | undefined } },
    );
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    act(() => {
      rerender({ params: {} });
    });
    await new Promise((r) => setTimeout(r, 5));
    // {} and undefined both serialize to "{}" with the stable encoder.
    expect(runFunctionMock).toHaveBeenCalledTimes(1);
  });
});
