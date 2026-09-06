/**
 * Regression — UI-ROBUSTNESS F4.
 *
 * performance-store was the one store the abort+last-wins fix waves missed:
 *   - rapidly selecting bot A then bot B let A's slow response land after
 *     B's and overwrite `selected` with the wrong bot's detail;
 *   - `loadLeaderboard` and `loadBot` shared a single `loading` flag, so one
 *     finishing flipped the other's spinner off.
 *
 * Mirrors portfolio-store.race-abort.test.ts: module-scoped AbortController,
 * aborted results are dropped, at most one trailing reload per lane, and
 * separate `loadingLeaderboard` / `loadingBot` tracking.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePerformanceStore } from "./performance-store";

vi.mock("./sidecar", () => ({
  sidecarFetch: vi.fn(),
}));

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

function botPayload(id: string) {
  return {
    bot_id: id,
    symbol: "BTC/USDT",
    strategy_id: "s",
    metrics: { total_pnl: 1, win_rate: 1, trade_count: 1, avg_pnl: 1, max_drawdown: 0 },
    trades: [],
    equity_curve: [],
  };
}

beforeEach(() => {
  usePerformanceStore.setState({
    leaderboard: [],
    selected: null,
    loading: false,
    loadingLeaderboard: false,
    loadingBot: false,
    error: null,
    generatedAt: null,
  });
  mock.mockReset();
});

describe("performance-store race-abort guard (UI-ROBUSTNESS F4)", () => {
  it("aborts the in-flight loadBot when a newer loadBot fires", async () => {
    let firstAborted = false;
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
    mock.mockResolvedValue(botPayload("B"));

    const p1 = usePerformanceStore.getState().loadBot("A");
    const p2 = usePerformanceStore.getState().loadBot("B");
    await Promise.all([p1, p2]);
    // Let any trailing reload settle.
    await new Promise((r) => setTimeout(r, 10));

    expect(firstAborted).toBe(true);
    expect(usePerformanceStore.getState().selected?.bot_id).toBe("B");
    expect(usePerformanceStore.getState().error).toBeNull();
  });

  it("does not overwrite the newer bot when the aborted call settles late", async () => {
    const stale = deferred<unknown>();
    const fresh = deferred<unknown>();
    mock.mockImplementationOnce(async (_p: string, init?: RequestInit) => {
      init?.signal?.addEventListener("abort", () => {
        // Drop the stale promise on abort — the fix's contract is "swallow
        // aborts", but a flaky transport may still resolve later.
      });
      return stale.promise;
    });
    mock.mockImplementationOnce(async () => fresh.promise);
    // The trailing reload (queued because the first call was aborted) needs
    // a valid payload too — it re-runs loadBot with the latest id.
    mock.mockResolvedValue(botPayload("B"));

    const p1 = usePerformanceStore.getState().loadBot("A");
    const p2 = usePerformanceStore.getState().loadBot("B");

    fresh.resolve(botPayload("B"));
    await p2;
    expect(usePerformanceStore.getState().selected?.bot_id).toBe("B");

    // Out-of-order landing of the aborted call must NOT win.
    stale.resolve(botPayload("A"));
    await p1;
    expect(usePerformanceStore.getState().selected?.bot_id).toBe("B");
  });

  it("leaderboard and bot lanes track loading independently", async () => {
    const lb = deferred<unknown>();
    mock.mockImplementationOnce(async (path: string) => {
      expect(path).toBe("/api/bots/performance");
      return lb.promise;
    });

    const lbPromise = usePerformanceStore.getState().loadLeaderboard();
    await Promise.resolve();
    expect(usePerformanceStore.getState().loadingLeaderboard).toBe(true);

    // Bot detail resolves while the leaderboard is still in flight.
    mock.mockResolvedValueOnce(botPayload("B"));
    await usePerformanceStore.getState().loadBot("B");
    const mid = usePerformanceStore.getState();
    expect(mid.loadingBot).toBe(false);
    expect(mid.loadingLeaderboard).toBe(true);
    // Combined flag still true — but the BOT spinner is not masked on.
    expect(mid.loading).toBe(true);

    lb.resolve({ records: [] });
    await lbPromise;
    const end = usePerformanceStore.getState();
    expect(end.loadingLeaderboard).toBe(false);
    expect(end.loadingBot).toBe(false);
    expect(end.loading).toBe(false);
  });

  it("an aborted leaderboard call does not surface an error", async () => {
    mock.mockImplementationOnce(async (_p: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          const err = new Error("AbortError");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    mock.mockResolvedValue({ records: [], generated_at: "now" });

    const p1 = usePerformanceStore.getState().loadLeaderboard();
    const p2 = usePerformanceStore.getState().loadLeaderboard();
    await Promise.all([p1, p2]);
    await new Promise((r) => setTimeout(r, 10));

    expect(usePerformanceStore.getState().error).toBeNull();
    expect(usePerformanceStore.getState().loadingLeaderboard).toBe(false);
  });
});
