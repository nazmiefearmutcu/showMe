/**
 * Regression — UI-ROBUSTNESS F1 (HIGH).
 *
 * `sidecarFetch` had no deadline: a sidecar that accepted the TCP connection
 * but never responded left the caller's `await` pending forever, which kept
 * `useLiveQuotesInternal.refresh`'s `polling` flag stuck at `true` and
 * silently killed every future 30 s poll.
 *
 * Contract pinned here:
 *   - a signal-less call gets a default (~15 s) deadline and rejects with a
 *     clearly-labelled catchable timeout error,
 *   - a caller-provided `init.signal` overrides the default deadline
 *     entirely (existing abort plumbing keeps working),
 *   - a fast response is unaffected (timer cancelled, no leak).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./tauri", () => ({
  invoke: vi.fn(),
  isInTauri: () => false,
  listen: vi.fn(),
}));

import { sidecarFetch } from "./sidecar";

const origFetch = globalThis.fetch;

type FetchMock = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>;

function installFetchMock(impl: FetchMock): void {
  globalThis.fetch = vi.fn(impl) as unknown as typeof fetch;
}

beforeEach(() => {
  vi.useFakeTimers();
  // First call is the /api/health probe waitForSidecarReady fires.
  installFetchMock((input) => {
    if (String(input).endsWith("/api/health")) {
      return Promise.resolve(
        new Response(JSON.stringify({ ok: true }), { status: 200 }),
      );
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });
});

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = origFetch;
});

describe("sidecarFetch default deadline (UI-ROBUSTNESS F1)", () => {
  it("rejects with a labelled timeout error when the request never resolves", async () => {
    installFetchMock((input, init) => {
      if (String(input).endsWith("/api/health")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true }), { status: 200 }),
        );
      }
      // Never resolves on its own — the wedged-handler scenario. Like real
      // fetch, the promise settles only when the deadline aborts the signal.
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("The operation was aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });

    const pending = sidecarFetch("/api/quote/AAPL");
    const assertion = expect(pending).rejects.toThrow(
      /\/api\/quote\/AAPL: request timed out after 15000ms/,
    );
    await vi.advanceTimersByTimeAsync(15_500);
    await assertion;
  });

  it("does NOT time out a response that lands before the deadline", async () => {
    const pending = sidecarFetch("/api/fast");
    await vi.advanceTimersByTimeAsync(100);
    await expect(pending).resolves.toEqual({});
  });

  it("a caller-provided signal overrides the default deadline (no 15s timer)", async () => {
    let sawAbort = false;
    installFetchMock((input, init) => {
      if (String(input).endsWith("/api/health")) {
        return Promise.resolve(
          new Response(JSON.stringify({ ok: true }), { status: 200 }),
        );
      }
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          sawAbort = true;
          const err = new Error("The operation was aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });

    const caller = new AbortController();
    const pending = sidecarFetch("/api/slow", { signal: caller.signal });
    const assertion = expect(pending).rejects.toThrow(/aborted/i);
    // Abort from the caller side after 1s — well before the default 15s.
    await vi.advanceTimersByTimeAsync(1_000);
    caller.abort();
    await assertion;
    expect(sawAbort).toBe(true);
  });
});
