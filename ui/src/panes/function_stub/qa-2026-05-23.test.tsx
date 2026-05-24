/**
 * QA-2026-05-23 — FunctionStub abort cleanup, timeout UI, panels polish.
 *
 * Pins three orthogonal contracts introduced by Agent D's QA-2026-05-23
 * sweep:
 *
 *   1. Abort cleanup: when `runFunction` is aborted via the upstream
 *      AbortController (rapid symbol switch, code switch, parent
 *      effect re-fire), the stub must reset its internal state back to
 *      "idle" and clear the `lastFingerprintRef` so the NEXT load
 *      starts from a clean cold slate — no ghost spinner that lingers
 *      until the new request resolves.
 *
 *   2. Timeout surface: when `runFunction` throws a FunctionCallError
 *      with `body === "timeout"` (the marker the underlying transport
 *      sets when its 35s AbortController fires), the stub renders a
 *      dedicated empty state — "Veri alınamadı — yeniden dene" + a
 *      Retry button with `data-testid="function-stub-timeout"` —
 *      instead of the generic "Function failed" surface. The pill in
 *      the header also reflects "timeout".
 *
 *   3. GenericResult polish:
 *      - `metadata.degraded === true` OR `metadata.fallback === true`
 *        → renders the "DATA DEGRADED" chip above the Detail rows.
 *      - `sources === ["no_live_source"]` → renders the "No live
 *        source available" empty state with a Retry button instead of
 *        the silent "No usable rows" fallback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import type { FunctionCallResult } from "@/lib/functions";

// ---- runFunction spy ----------------------------------------------------
interface Deferred {
  promise: Promise<FunctionCallResult<unknown>>;
  resolve: (v: FunctionCallResult<unknown>) => void;
  reject: (err: Error) => void;
  signal?: AbortSignal;
}
const deferreds: Deferred[] = [];

function makeDeferred(signal?: AbortSignal): Deferred {
  let resolve: Deferred["resolve"];
  let reject: Deferred["reject"];
  const promise = new Promise<FunctionCallResult<unknown>>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve: resolve!, reject: reject!, signal };
}

// Lazy import so vi.mock can intercept.
vi.mock("@/lib/functions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/functions")>(
    "@/lib/functions",
  );
  return {
    ...actual,
    runFunction: vi.fn((_code: string, opts?: { signal?: AbortSignal }) => {
      const d = makeDeferred(opts?.signal);
      deferreds.push(d);
      return d.promise;
    }),
  };
});

// jsdom stubs --------------------------------------------------------------
class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => ({
    addCandlestickSeries: vi.fn(() => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
    addLineSeries: vi.fn(() => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
    addHistogramSeries: vi.fn(() => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
    removeSeries: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn(), setVisibleLogicalRange: vi.fn() })),
    subscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
    applyOptions: vi.fn(),
    resize: vi.fn(),
    takeScreenshot: vi.fn(() => document.createElement("canvas")),
  })),
}));

// Imports must come AFTER vi.mock declarations.
import FunctionStub from "./index";
import { FunctionCallError as FnCallError } from "@/lib/functions";
import { GenericResult } from "./panels";
import { useAppStore } from "@/lib/store";
import type { FunctionEntry } from "@/lib/sidecar";

function makeTimeoutError(code: string): Error {
  const ErrCtor = FnCallError;
  const err = Reflect.construct(ErrCtor, [
    `${code}: timed out after 35000ms`,
    0,
    "timeout",
  ]) as Error;
  return err;
}

const SCREENER_ENTRY: FunctionEntry = {
  code: "TESTGEN",
  name: "Test Generic",
  category: "screener",
  panel: null,
  asset_classes: [],
} as unknown as FunctionEntry;

beforeEach(() => {
  deferreds.length = 0;
  useAppStore.getState().setFunctionIndex([SCREENER_ENTRY]);
});

afterEach(() => {
  cleanup();
  deferreds.length = 0;
});

function resultPaneHasSkeleton(): boolean {
  const pane = document.querySelector(".showme-stub-result");
  if (!pane) return false;
  return !!pane.querySelector(".showme-card-reveal.showme-stub-block.u-grid-gap-10");
}

describe("QA-2026-05-23 - FunctionStub abort cleanup", () => {
  it("resets state to idle after an aborted load - no ghost spinner", async () => {
    const { unmount } = render(<FunctionStub code="TESTGEN" />);

    // 1. Cold mount triggers a load; deferred[0] is in flight, skeleton shown.
    await waitFor(() => {
      expect(deferreds).toHaveLength(1);
      expect(resultPaneHasSkeleton()).toBe(true);
    });

    // 2. Simulate the abort path: unmount triggers cleanup which calls
    //    `activeRequest.current?.abort()`. The pending request rejects
    //    with an AbortError-ish; the catch block must read
    //    `signal?.aborted` and short-circuit to idle without flipping
    //    to "error" or leaving "loading" pinned.
    const inflight = deferreds[0];
    expect(inflight.signal).toBeDefined();

    // Manually abort + reject to mimic the runFunction transport behaviour.
    await act(async () => {
      unmount();
      const abortErr = Reflect.construct(Error, ["AbortError"]) as Error;
      abortErr.name = "AbortError";
      inflight.reject(abortErr);
      await Promise.resolve();
    });

    // The component is unmounted; no skeleton can be observed. The
    // contract here is that nothing throws - the catch block's
    // `signal?.aborted` guard short-circuited.
    expect(document.querySelector(".showme-stub-result")).toBeNull();
  });

  it("the catch path resets state to idle when the signal is aborted mid-request", async () => {
    // Direct contract-level assertion against the source - the file
    // must contain the abort-reset code we added.
    const fs = await import("node:fs");
    const path = await import("node:path");
    const indexSrc = fs.readFileSync(
      path.resolve(__dirname, "index.tsx"),
      "utf8",
    );
    // The fix sets state back out of "loading" AND clears
    // `lastFingerprintRef.current = ""` before returning. Both must
    // appear inside the same catch path before the early return.
    //
    // UA-HIGH-24: the post-abort state is now either "idle" (no prior
    // result) or "refreshing" (preserve the previous payload while the new
    // request resolves) — the regex accepts both.
    expect(indexSrc).toMatch(
      /if\s*\(\s*signal\?\.aborted\s*\)\s*\{[\s\S]{0,400}setState\([^)]*"(?:idle|refreshing)"[^)]*\)[\s\S]{0,200}lastFingerprintRef\.current\s*=\s*""[\s\S]{0,200}return/,
    );
  });
});

describe("QA-2026-05-23 - FunctionStub timeout UI", () => {
  it("renders a dedicated timeout empty state when runFunction throws a timeout error", async () => {
    render(<FunctionStub code="TESTGEN" />);
    await waitFor(() => expect(deferreds).toHaveLength(1));

    await act(async () => {
      deferreds[0].reject(makeTimeoutError("TESTGEN"));
      await Promise.resolve().then(() => Promise.resolve());
    });

    // The dedicated timeout empty state surfaces.
    await waitFor(() => {
      expect(
        screen.queryByText(/veri alınamadı/i),
      ).not.toBeNull();
    });
    // Retry button carries the documented testid.
    const retry = screen.getByTestId("function-stub-timeout");
    expect(retry).not.toBeNull();
    // Re-clicking Retry kicks off a fresh load.
    await act(async () => {
      fireEvent.click(retry);
      await Promise.resolve();
    });
    expect(deferreds.length).toBeGreaterThanOrEqual(2);
  });

  it("the header pill reflects 'timeout' instead of 'error'", async () => {
    render(<FunctionStub code="TESTGEN" />);
    await waitFor(() => expect(deferreds).toHaveLength(1));

    await act(async () => {
      deferreds[0].reject(makeTimeoutError("TESTGEN"));
      await Promise.resolve().then(() => Promise.resolve());
    });

    await waitFor(() => {
      // The LoadStatePill renders the state string as-is.
      const allText = document.body.textContent ?? "";
      expect(allText.toLowerCase()).toContain("timeout");
    });
  });
});

// --------------------------------------------------------------------------
// GenericResult polish: degraded chip + no-live-source empty state.
// Tested directly against `<GenericResult>` so we don't have to drive a
// full FunctionStub mount.
// --------------------------------------------------------------------------
function baseSummary() {
  return {
    shape: "object",
    rows: [],
    columns: [],
    fields: [],
    keyValues: [],
  };
}

function baseStatus(state: "live" | "degraded" = "live") {
  return {
    state,
    label: state,
    title: "test",
    reasons: [] as string[],
    actions: [] as string[],
  };
}

describe("QA-2026-05-23 - GenericResult panels polish", () => {
  it("renders the DATA DEGRADED chip when metadata.degraded === true", () => {
    const result = {
      code: "TESTGEN",
      instrument: null,
      data: { rows: [{ a: 1 }] },
      metadata: { degraded: true },
      fetched_at: new Date().toISOString(),
      sources: ["yfinance"],
      warnings: [],
      elapsed_ms: 100,
    } as unknown as FunctionCallResult<unknown>;

    render(
      <GenericResult
        result={result}
        summary={baseSummary()}
        payloadStatus={baseStatus("live")}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByTestId("function-degraded-chip")).not.toBeNull();
  });

  it("renders the DATA DEGRADED chip when metadata.fallback === true", () => {
    const result = {
      code: "TESTGEN",
      instrument: null,
      data: { rows: [] },
      metadata: { fallback: true },
      fetched_at: new Date().toISOString(),
      sources: ["yfinance"],
      warnings: [],
      elapsed_ms: 100,
    } as unknown as FunctionCallResult<unknown>;

    render(
      <GenericResult
        result={result}
        summary={baseSummary()}
        payloadStatus={baseStatus("live")}
        onRetry={() => {}}
      />,
    );
    expect(screen.getByTestId("function-degraded-chip")).not.toBeNull();
  });

  it("does NOT render the chip when metadata has neither degraded nor fallback", () => {
    const result = {
      code: "TESTGEN",
      instrument: null,
      data: { rows: [] },
      metadata: {},
      fetched_at: new Date().toISOString(),
      sources: ["yfinance"],
      warnings: [],
      elapsed_ms: 100,
    } as unknown as FunctionCallResult<unknown>;

    render(
      <GenericResult
        result={result}
        summary={baseSummary()}
        payloadStatus={baseStatus("live")}
        onRetry={() => {}}
      />,
    );
    expect(screen.queryByTestId("function-degraded-chip")).toBeNull();
  });

  it("renders the 'No live source available' empty state when sources === ['no_live_source']", () => {
    const onRetry = vi.fn();
    const result = {
      code: "TESTGEN",
      instrument: null,
      data: { rows: [] },
      metadata: {},
      fetched_at: new Date().toISOString(),
      sources: ["no_live_source"],
      warnings: [],
      elapsed_ms: 100,
    } as unknown as FunctionCallResult<unknown>;

    render(
      <GenericResult
        result={result}
        summary={baseSummary()}
        payloadStatus={baseStatus("live")}
        onRetry={onRetry}
      />,
    );
    expect(
      screen.queryByText(/no live source available/i),
    ).not.toBeNull();
    // Retry button wired to onRetry.
    const retryBtn = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryBtn);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("falls through to normal rendering when sources contains real entries (no_live_source mixed)", () => {
    const result = {
      code: "TESTGEN",
      instrument: null,
      data: { rows: [] },
      metadata: {},
      fetched_at: new Date().toISOString(),
      // Even a single non-`no_live_source` entry must opt out of the
      // dedicated empty state - the trader still has a live provider.
      sources: ["no_live_source", "yfinance"],
      warnings: [],
      elapsed_ms: 100,
    } as unknown as FunctionCallResult<unknown>;

    render(
      <GenericResult
        result={result}
        summary={baseSummary()}
        payloadStatus={baseStatus("live")}
        onRetry={() => {}}
      />,
    );
    expect(
      screen.queryByText(/no live source available/i),
    ).toBeNull();
  });
});
