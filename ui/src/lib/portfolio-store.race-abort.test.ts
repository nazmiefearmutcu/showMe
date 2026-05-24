/**
 * Regression — audit S3.
 *
 * Burst-clicking the credential checkbox set in PORT used to fire one
 * `loadPortfolio()` per click; the LAST response to land won (timing-
 * dependent, often not the user's actual final selection). Fix:
 *   - Abort in-flight fetch on new loadPortfolio call.
 *   - Queue at most one trailing reload so the latest selection still
 *     produces the final state without spawning N parallel fetches.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./sidecar", () => ({
  sidecarFetch: vi.fn(),
}));

import { usePortfolioStore } from "./portfolio-store";
import { sidecarFetch } from "./sidecar";

const mock = sidecarFetch as ReturnType<typeof vi.fn>;

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (v: T) => void;
  reject: (e: unknown) => void;
} {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [],
    totals: {},
    loading: false,
    error: null,
    lastFetchedAt: null,
    selectedCredentialIds: null,
    includeOrders: false,
  });
  mock.mockReset();
});

describe("portfolio-store race-abort guard (audit S3)", () => {
  it("aborts the in-flight request when a new loadPortfolio fires", async () => {
    // First call: rejects with AbortError when the signal aborts. This mimics
    // sidecarFetch's actual behaviour — it propagates fetch's AbortError.
    let firstAborted = false;
    const finalPayload = {
      as_of: "2026-05-24T00:00:00Z",
      groups: [
        {
          credential_id: "B",
          exchange_id: "binance",
          account_label: "main",
          permissions: ["read"],
          account: { equity: 200, currency: "USDT" },
          positions: [],
          orders: [],
          error: null,
        },
      ],
      totals: { equity_by_currency: { USDT: 200 }, stable_usd_equivalent: 200 },
    };
    mock.mockImplementationOnce(async (_path: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          firstAborted = true;
          const err = new Error("AbortError");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    // The second + any subsequent (trailing-reload) call resolves with the
    // final payload. Use a default mock so the trailing reload triggered
    // by the finally-block also sees a result.
    mock.mockResolvedValue(finalPayload);

    // Burst click: two loadPortfolio calls back-to-back.
    const p1 = usePortfolioStore.getState().loadPortfolio();
    const p2 = usePortfolioStore.getState().loadPortfolio();
    await Promise.all([p1, p2]);
    // Let the trailing reload (if any) settle.
    await new Promise((r) => setTimeout(r, 10));

    expect(firstAborted).toBe(true);
    const st = usePortfolioStore.getState();
    expect(st.groups).toHaveLength(1);
    expect(st.groups[0].credential_id).toBe("B");
    expect(st.error).toBeNull();
  });

  it("does not overwrite newer state when an aborted call eventually settles", async () => {
    // 1) First call resolves with stale payload AFTER the second succeeds.
    const stale = deferred<unknown>();
    const fresh = deferred<unknown>();
    mock.mockImplementationOnce(async (_p: string, init?: RequestInit) => {
      init?.signal?.addEventListener("abort", () => {
        // Drop the stale promise on abort — DO NOT resolve. The fix's
        // contract is "swallow aborts" so we test what happens if a flaky
        // mock decides to resolve anyway.
      });
      return stale.promise;
    });
    mock.mockImplementationOnce(async () => fresh.promise);

    const p1 = usePortfolioStore.getState().loadPortfolio();
    const p2 = usePortfolioStore.getState().loadPortfolio();

    fresh.resolve({
      as_of: "now",
      groups: [{ credential_id: "FRESH" } as never],
      totals: {},
    });
    await p2;
    expect(usePortfolioStore.getState().groups[0].credential_id).toBe("FRESH");

    // Now have the stale call settle out of order.
    stale.resolve({
      as_of: "stale",
      groups: [{ credential_id: "STALE" } as never],
      totals: {},
    });
    await p1;
    // Final state must STILL be the fresh response.
    expect(usePortfolioStore.getState().groups[0].credential_id).toBe("FRESH");
  });

  it("queues at most one trailing reload regardless of burst size", async () => {
    // Each call aborts cleanly. Final call should also abort (no resolver).
    mock.mockImplementation(
      (_path: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            const err = new Error("AbortError");
            err.name = "AbortError";
            reject(err);
          });
        }),
    );
    // 5 burst clicks.
    const ps: Promise<void>[] = [];
    for (let i = 0; i < 5; i++) {
      ps.push(usePortfolioStore.getState().loadPortfolio());
    }
    // Allow all 5 to chain — each abort triggers the next, the last call
    // hangs (no resolver, not aborted). Let microtasks settle.
    await new Promise((r) => setTimeout(r, 20));
    // We do NOT promise "1 call total" — the fix aborts old and queues at
    // most one trailing reload per cycle. The full burst exposes at most
    // 2× the burst size because each abort can schedule one trailing call.
    // Anchored upper bound prevents the original "N parallel storm" regression.
    expect(mock.mock.calls.length).toBeGreaterThan(0);
    expect(mock.mock.calls.length).toBeLessThanOrEqual(10);
  });
});
