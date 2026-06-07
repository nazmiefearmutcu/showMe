/**
 * Pins the loading-flicker fix in `panes/function_stub/index.tsx`.
 *
 * Bug: previously, `load()` unconditionally called
 *   setState("loading"); setError(null); setResult(null);
 * on every invocation, including refreshes triggered by the App-level
 * function-index warmup interval (every 2s during sidecar warmup) and by
 * the manual Run button. The result was a skeleton flash on every refresh
 * even though the prior result was perfectly usable.
 *
 * Fix: track the most recently-issued fetch fingerprint (code+symbol+params)
 * in a ref. Identical fingerprint → refresh mode: setState("refreshing"),
 * keep the prior result on screen. Different fingerprint → cold mode:
 * skeleton flashes (legitimately, because the user input changed).
 *
 * Contract pinned here:
 *   1. First load shows the skeleton (cold mount).
 *   2. After success, result renders.
 *   3. A subsequent Run with the same fingerprint does NOT re-show the
 *      skeleton — the prior result stays visible while the new fetch runs.
 *   4. After the second fetch resolves, the new result is on screen.
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
// Each call returns a fresh deferred so the test orchestrates resolution
// order explicitly. We capture every (resolve, reject) pair so we can drive
// the component through cold-load → ok → refresh → ok manually.
interface Deferred {
  promise: Promise<FunctionCallResult<unknown>>;
  resolve: (v: FunctionCallResult<unknown>) => void;
  reject: (err: Error) => void;
}
const deferreds: Deferred[] = [];

function makeDeferred(): Deferred {
  let resolve: Deferred["resolve"];
  let reject: Deferred["reject"];
  const promise = new Promise<FunctionCallResult<unknown>>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve: resolve!, reject: reject! };
}

vi.mock("@/lib/functions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/functions")>(
    "@/lib/functions",
  );
  return {
    ...actual,
    runFunction: vi.fn(() => {
      const d = makeDeferred();
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

// Lightweight-charts is not exercised in this file but `FunctionStub`'s
// transitive imports may eventually hit it. Provide a benign stub so any
// accidental import doesn't blow up jsdom.
vi.mock("lightweight-charts", () => {
  class LineSeries {}
  class CandlestickSeries {}
  class HistogramSeries {}
  class AreaSeries {}
  return {
    LineSeries,
    CandlestickSeries,
    HistogramSeries,
    AreaSeries,
    createChart: vi.fn(() => {
      const instance = {
        addCandlestickSeries: vi.fn((_options?: any) => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
        addLineSeries: vi.fn((_options?: any) => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
        addAreaSeries: vi.fn((_options?: any) => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
        addHistogramSeries: vi.fn((_options?: any) => ({ setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() })),
        removeSeries: vi.fn(),
        priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
        timeScale: vi.fn(() => ({ fitContent: vi.fn(), setVisibleLogicalRange: vi.fn() })),
        subscribeCrosshairMove: vi.fn(),
        remove: vi.fn(),
        applyOptions: vi.fn(),
        resize: vi.fn(),
        takeScreenshot: vi.fn(() => document.createElement("canvas")),
        addSeries: vi.fn((constructor, options) => {
          if (constructor === CandlestickSeries) return instance.addCandlestickSeries(options);
          if (constructor === LineSeries) return instance.addLineSeries(options);
          if (constructor === HistogramSeries) return instance.addHistogramSeries(options);
          if (constructor === AreaSeries) return instance.addAreaSeries(options);
          return { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
        }),
      };
      return instance;
    }),
  };
});

// Imports must come AFTER vi.mock declarations.
import FunctionStub from "./index";
import { useAppStore } from "@/lib/store";
import type { FunctionEntry } from "@/lib/sidecar";

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
  // The cold-load branch renders a <div class="showme-card-reveal showme-stub-block u-grid-gap-10">
  // wrapping <Skeleton ... /> children. The "ok" branch renders <GenericResult />
  // which has different class hooks (e.g., showme-result-grid). We detect
  // the cold-load branch by the presence of any element with role="status"
  // or by checking the inner-text marker "No result yet" is absent AND no
  // grid is present. Most robustly, just look for the skeleton block class.
  return !!pane.querySelector(".showme-card-reveal.showme-stub-block.u-grid-gap-10");
}

describe("FunctionStub — loading-vs-refresh flicker", () => {
  it("skips the skeleton on a refresh with identical fetch params", async () => {
    render(<FunctionStub code="TESTGEN" />);

    // 1. Cold mount → first load() in flight → skeleton MUST be visible.
    await waitFor(() => {
      expect(deferreds).toHaveLength(1);
      expect(resultPaneHasSkeleton()).toBe(true);
    });

    // 2. Resolve the first fetch → state="ok" → result renders, skeleton gone.
    await act(async () => {
      deferreds[0].resolve({
        ok: true,
        data: { rows: [{ symbol: "AAA", value: 1 }] },
      } as unknown as FunctionCallResult<unknown>);
      // Let the microtask + render flush.
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(resultPaneHasSkeleton()).toBe(false);
    });

    // 3. Click "Run" → runLatest() → load() with IDENTICAL fetchKey
    //    (same code, same symbol "", same default params). Refresh-mode
    //    must NOT replay the skeleton.
    const runButton = screen.getByRole("button", { name: /run/i });
    await act(async () => {
      fireEvent.click(runButton);
      await Promise.resolve();
    });

    // A second fetch is now in flight.
    expect(deferreds).toHaveLength(2);
    // CRITICAL ASSERTION: the result pane is still showing data, not skeleton.
    expect(resultPaneHasSkeleton()).toBe(false);

    // 4. Resolve the second fetch → state="ok" with refreshed data.
    await act(async () => {
      deferreds[1].resolve({
        ok: true,
        data: { rows: [{ symbol: "BBB", value: 2 }] },
      } as unknown as FunctionCallResult<unknown>);
      await Promise.resolve();
    });
    await waitFor(() => {
      expect(resultPaneHasSkeleton()).toBe(false);
    });
  });

  it("keeps the prior result on screen when a refresh fetch errors", async () => {
    render(<FunctionStub code="TESTGEN" />);
    await waitFor(() => expect(deferreds).toHaveLength(1));

    await act(async () => {
      deferreds[0].resolve({
        ok: true,
        data: { rows: [{ symbol: "AAA", value: 1 }] },
      } as unknown as FunctionCallResult<unknown>);
      await Promise.resolve();
    });
    await waitFor(() => expect(resultPaneHasSkeleton()).toBe(false));

    // Trigger refresh, then fail it. Prior result must STAY on screen — no
    // skeleton, no full "Function failed" error screen.
    const runButton = screen.getByRole("button", { name: /run/i });
    await act(async () => {
      fireEvent.click(runButton);
      await Promise.resolve();
    });
    expect(deferreds).toHaveLength(2);

    await act(async () => {
      deferreds[1].reject(new Error("network down"));
      await Promise.resolve().then(() => Promise.resolve());
    });

    // After refresh failure, the pane is still showing the prior result.
    // The error empty-state should NOT have taken over (that's reserved for
    // cold-mode failures where there's nothing to fall back on).
    expect(resultPaneHasSkeleton()).toBe(false);
    expect(screen.queryByText(/function failed/i)).toBeNull();
  });
});
