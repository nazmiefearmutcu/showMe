/**
 * Regression — UI-ROBUSTNESS F1 (HIGH), integration level.
 *
 * `useLiveQuotesInternal.refresh` used to wedge forever when the snapshot
 * fetch hung: `polling` was only released in `finally`, and `finally` never
 * ran because `await Promise.all(...)` never settled. With the sidecar
 * default deadline (sidecar.ts F1), a hung fetch now rejects, `finally`
 * releases the loop, and the next poll issues a fresh request.
 *
 * Drives the REAL default fetcher (`fetchQuote` → `sidecarFetch`) against a
 * mocked global fetch whose `/api/quote/AAPL` response never resolves.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useLiveQuotes } from "./market-data";

const origFetch = globalThis.fetch;

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = origFetch;
});

describe("poll loop recovers from a hung snapshot fetch (F1)", () => {
  it("a never-resolving fetch no longer wedges the 30s poll loop", async () => {
    vi.useFakeTimers();
    let quoteCalls = 0;
    globalThis.fetch = vi.fn(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/health")) {
          return Promise.resolve(
            new Response(JSON.stringify({ ok: true }), { status: 200 }),
          );
        }
        if (url.includes("/api/quote/")) {
          quoteCalls += 1;
          // Never resolves; honour the abort the deadline fires so the
          // promise settles (mirrors real fetch semantics).
          return new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              const err = new Error("The operation was aborted");
              err.name = "AbortError";
              reject(err);
            });
          });
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      },
    ) as unknown as typeof fetch;

    const { result } = renderHook(() =>
      useLiveQuotes(["AAPL"], { pollMs: 1_000, subscriber: () => ({ close: () => undefined }) }),
    );

    // Past the default 15 s deadline: the initial fetch aborts, the error
    // lands per-symbol, and `polling` is released — the interval ticks that
    // fire after the deadline within this window already issue new requests.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16_000);
    });
    expect(quoteCalls).toBeGreaterThanOrEqual(1);
    expect(result.current.AAPL.error).toMatch(/timed out/);

    // The loop is no longer wedged — the poll interval keeps issuing NEW
    // requests instead of being skipped forever.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(quoteCalls).toBeGreaterThanOrEqual(2);
  });
});
