/**
 * ONCH pane — data-honesty + render-contract tests.
 *
 * Follows the FORM4/GEX mock pattern: `useFunction` is mocked via a mutable
 * shared state so each test drives the pane into a specific branch without
 * the real sidecar transport.
 *
 * Pins:
 *  - the load states (loading / empty-provider / error / ok) render;
 *  - a live payload shows the honest delayed_reference mode pill, the
 *    vitals card ribbon, the projected-mempool bar chart and the metric
 *    table straight from the payload (never invented numbers);
 *  - AUTO refresh actually polls (fake timers advance into refetch).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ONCHPane } from "./ONCH";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      sources: ["mempool", "coingecko"],
      elapsed_ms: 522.6,
      asOf: "2026-09-07T00:52:06+00:00",
      data: {
        status: "ok",
        data_mode: "delayed_reference",
        chain: "BTC",
        rows: [
          {
            metric: "Fastest Fee",
            value: "1",
            unit: "sat/vB",
            source: "mempool",
            context: "Next-block inclusion",
          },
          {
            metric: "Hashrate",
            value: "944.5",
            unit: "EH/s",
            source: "mempool",
            context: "3-day average",
          },
          {
            metric: "BTC Dominance",
            value: "59.18",
            unit: "%",
            source: "coingecko",
            context: "Share of total crypto market cap",
          },
        ],
        series: [
          { bucket: "Block +1", count: 6426 },
          { bucket: "Block +2", count: 7162 },
          { bucket: "Block +8", count: 49138 },
        ],
        cards: [
          { label: "Chain", value: "BTC" },
          { label: "Mempool", value: "78,038 tx" },
          { label: "Fastest Fee", value: "1 sat/vB" },
        ],
        summary:
          "78,038 txs in the mempool; next-block fee 1 sat/vB; hashrate 944.5 EH/s.",
      },
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ONCH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<ONCHPane code="ONCH" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
      refetch,
    });
    render(<ONCHPane code="ONCH" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the honest empty state on provider_unavailable", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          data_mode: "provider_unavailable",
          chain: "BTC",
          rows: [],
          series: [],
        },
      },
    });
    render(<ONCHPane code="ONCH" />);
    expect(
      screen.getByText(/No on-chain vitals returned/i),
    ).toBeInTheDocument();
    // Nothing is fabricated while degraded.
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("ONCH pane — live payload", () => {
  it("renders the delayed_reference pill, vitals cards, mempool bars and metric rows", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<ONCHPane code="ONCH" />);
    // Honest data-mode pill: the feed is delayed_reference even when live
    // (pill + footer status strip both carry it).
    expect(screen.getAllByText("delayed_reference").length).toBeGreaterThan(
      0,
    );
    // Vitals cards straight from payload.cards.
    expect(screen.getByText("78,038 tx")).toBeInTheDocument();
    // Metric rows render with their payload values (strings, not recomputed).
    // "Fastest Fee" appears in both a card and a table row.
    expect(screen.getAllByText("Fastest Fee").length).toBe(2);
    expect(screen.getByText("944.5")).toBeInTheDocument();
    expect(screen.getByText("BTC Dominance")).toBeInTheDocument();
    // Mempool bar chart: one bar group per series bucket.
    expect(container.querySelectorAll("rect").length).toBe(3);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
  });

  it("polls on the AUTO cadence once enabled", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...livePayload(), refetch });
    render(<ONCHPane code="ONCH" />);
    expect(screen.getByText("Off")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "15s" }));
    // The active auto pill appears.
    expect(screen.getByText("auto 15s")).toBeInTheDocument();
    expect(refetch).not.toHaveBeenCalled();
    // The interval only invokes the mocked refetch (no React state updates),
    // so plain timer advancement is sufficient here.
    vi.advanceTimersByTime(45_500);
    // 45.5s at a 15s cadence → 3 polls.
    expect(refetch).toHaveBeenCalledTimes(3);
  });
});

describe("ONCH pane — difficulty epoch progress", () => {
  function payloadWithDifficulty(context: string) {
    const payload = livePayload();
    payload.data.data.rows = [
      ...payload.data.data.rows,
      {
        metric: "Difficulty Change",
        value: "1.02",
        unit: "%",
        source: "mempool",
        context,
      },
    ];
    return payload;
  }

  it("renders the epoch progress bar from the fetched progress/remaining context", () => {
    setMockFn({
      state: "ok",
      ...payloadWithDifficulty("36.4% through epoch, 1,234 blocks left"),
    });
    render(<ONCHPane code="ONCH" />);
    const section = screen.getByLabelText("Difficulty epoch progress");
    expect(section).toHaveTextContent("36% through epoch");
    expect(section).toHaveTextContent("1,234 blocks remaining");
    const bar = screen.getByRole("progressbar", {
      name: /Difficulty epoch 36.4 percent complete, 1234 blocks remaining/i,
    });
    expect(bar).toHaveAttribute("aria-valuenow", "36");
  });

  it("renders an honest note (no bar) when the epoch context is unparsable", () => {
    setMockFn({ state: "ok", ...payloadWithDifficulty("—") });
    render(<ONCHPane code="ONCH" />);
    expect(
      screen.getByText(/Difficulty epoch progress unavailable in this snapshot/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("progressbar", { name: /Difficulty epoch/i }),
    ).toBeNull();
  });
});

describe("ONCH pane — controls", () => {
  it("switches the AUTO cadence back off", () => {
    vi.useFakeTimers();
    setMockFn({ state: "ok", ...livePayload() });
    render(<ONCHPane code="ONCH" />);
    fireEvent.click(screen.getByRole("button", { name: "30s" }));
    expect(screen.getByRole("button", { name: "30s" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Off" }));
    // "Off" becomes the active (disabled) option again.
    expect(screen.getByRole("button", { name: "Off" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "30s" })).not.toBeDisabled();
  });
});

describe("ONCH pane — metric grid sort + keyboard (lane B4)", () => {
  it("defaults to alphabetical metric order and enables keyboard grid navigation", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<ONCHPane code="ONCH" />);

    const grid = screen.getByRole("grid", { name: "ONCH on-chain metrics" });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // Fixture order is Fastest Fee / Hashrate / BTC Dominance; metric
    // ascending -> BTC Dominance first, Hashrate last.
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("BTC Dominance");
    expect(rowsBefore.at(-1)?.textContent).toContain("Hashrate");

    // Activating the sort cycles asc -> desc: Hashrate leads.
    fireEvent.click(container.querySelector('th[aria-sort="ascending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).toContain("Hashrate");
  });
});
