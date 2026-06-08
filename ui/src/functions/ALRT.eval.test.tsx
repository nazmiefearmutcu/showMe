/**
 * ALRT — client-side evaluation loop (the "make it real" marquee).
 *
 * Before this round the pane never evaluated alerts against live prices:
 * a stale comment claimed "Round 24+ wires a polling loop" but none existed,
 * so `fired_count` only moved via the manual "test fire" button. These specs
 * pin the now-real behaviour:
 *
 *  - an `above` alert fires ONCE on the not-triggered→triggered edge, and
 *    never while it stays armed below the threshold;
 *  - a `cross_up` alert fires only on an actual crossing (prev below →
 *    current above), never on first observation;
 *  - a cooldown blocks an immediate refire;
 *  - the row surfaces the live Current value + an armed/triggered status;
 *  - no fire when there is no quote.
 */
import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// fetchQuote + the fire side-effects are mocked so each spec drives a
// deterministic sequence of prices through the poll loop.
vi.mock("@/lib/quotes", () => ({
  fetchQuote: vi.fn(),
}));
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  isInTauri: vi.fn(() => false),
}));
vi.mock("@/lib/toast", () => ({
  toast: { info: vi.fn(), success: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/confirm", () => ({ confirmAction: vi.fn(async () => true) }));

import { ALRTPane } from "./ALRT";
import { fetchQuote } from "@/lib/quotes";
import { toast } from "@/lib/toast";
import { clearAlerts, addAlert, loadAlerts, type AlertRow } from "@/lib/alerts";

const POLL_MS = 45_000;

function quote(symbol: string, price: number) {
  return {
    symbol,
    asset_class: "EQUITY",
    last: price,
    price,
    previous_close: null,
    change_pct: 1.5,
    volume: 1_000_000,
    bid: null,
    ask: null,
    source: "test",
    provider_symbol: symbol,
    currency: "USD",
    fetched_at: new Date().toISOString(),
  };
}

// Flush the chain of microtasks created by awaited promises (load/fetch).
async function flush() {
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
}

// Drive one poll cycle: advance the interval and resolve all the async
// fetch + state updates it kicks off.
async function advancePoll() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(POLL_MS);
  });
  await flush();
}

beforeEach(async () => {
  vi.useFakeTimers();
  await clearAlerts();
  (fetchQuote as ReturnType<typeof vi.fn>).mockReset();
  (toast.warn as ReturnType<typeof vi.fn>).mockClear();
  (toast.info as ReturnType<typeof vi.fn>).mockClear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

async function seed(row: Partial<AlertRow> & { symbol: string; threshold: number }) {
  await addAlert({
    symbol: row.symbol,
    field: row.field ?? "price",
    direction: row.direction ?? "above",
    threshold: row.threshold,
    note: row.note,
  });
}

async function mountPane() {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ALRTPane code="ALRT" />);
  });
  await flush();
  return utils;
}

describe("ALRT evaluation loop", () => {
  it("an above alert fires ONCE when price crosses above threshold, not every tick", async () => {
    await seed({ symbol: "AAPL", direction: "above", threshold: 200 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    // armed (190) → first crossing (210) → still above (220) → still above (230)
    fq.mockResolvedValueOnce(quote("AAPL", 190))
      .mockResolvedValueOnce(quote("AAPL", 210))
      .mockResolvedValueOnce(quote("AAPL", 220))
      .mockResolvedValueOnce(quote("AAPL", 230));

    await mountPane();
    expect(screen.getByText("AAPL")).toBeInTheDocument();

    await advancePoll(); // 190 — armed, no fire
    expect(toast.info).not.toHaveBeenCalled();

    await advancePoll(); // 210 — edge: fires once
    expect(toast.info).toHaveBeenCalledTimes(1);

    await advancePoll(); // 220 — still above, must NOT refire
    await advancePoll(); // 230 — still above, must NOT refire
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("an above alert does NOT fire while it stays armed (below threshold)", async () => {
    await seed({ symbol: "MSFT", direction: "above", threshold: 500 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    fq.mockResolvedValue(quote("MSFT", 400));

    await mountPane();
    expect(screen.getByText("MSFT")).toBeInTheDocument();

    await advancePoll();
    await advancePoll();
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("a cross_up alert fires only on an actual crossing (prev below → current above)", async () => {
    await seed({ symbol: "NVDA", direction: "cross_up", threshold: 100 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    // 95 (below, first obs — no prev, must NOT fire) → 110 (crossed up, fire)
    fq.mockResolvedValueOnce(quote("NVDA", 95))
      .mockResolvedValueOnce(quote("NVDA", 110))
      .mockResolvedValueOnce(quote("NVDA", 120));

    await mountPane();
    expect(screen.getByText("NVDA")).toBeInTheDocument();

    await advancePoll(); // 95 first observation — no crossing, no fire
    expect(toast.info).not.toHaveBeenCalled();

    await advancePoll(); // 110 — prev below, now above → crossing fires
    expect(toast.info).toHaveBeenCalledTimes(1);

    await advancePoll(); // 120 — still above, no new crossing
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("cooldown prevents an immediate refire after a fresh fire", async () => {
    await seed({ symbol: "SPY", direction: "cross_up", threshold: 100 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    // cross up (fire) → drop below → cross up again immediately (cooldown blocks)
    fq.mockResolvedValueOnce(quote("SPY", 90))
      .mockResolvedValueOnce(quote("SPY", 110)) // fire
      .mockResolvedValueOnce(quote("SPY", 90)) // back below
      .mockResolvedValueOnce(quote("SPY", 110)); // crossing, but within cooldown

    await mountPane();
    expect(screen.getByText("SPY")).toBeInTheDocument();

    await advancePoll(); // 90
    await advancePoll(); // 110 fire
    expect(toast.info).toHaveBeenCalledTimes(1);
    await advancePoll(); // 90
    await advancePoll(); // 110 again, blocked by cooldown
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it("shows the live Current value and a triggered status from the mocked quote", async () => {
    await seed({ symbol: "TSLA", direction: "above", threshold: 200 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    fq.mockResolvedValue(quote("TSLA", 250));

    await mountPane();
    expect(screen.getByText("TSLA")).toBeInTheDocument();

    await advancePoll();
    // Current value column renders the live price.
    expect(screen.getByText("250.00")).toBeInTheDocument();
    // Status surfaces "triggered" (price 250 > threshold 200).
    expect(screen.getByText(/triggered/i)).toBeInTheDocument();
  });

  it("shows armed status when condition not met", async () => {
    await seed({ symbol: "AMD", direction: "above", threshold: 200 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    fq.mockResolvedValue(quote("AMD", 150));

    await mountPane();
    expect(screen.getByText("AMD")).toBeInTheDocument();

    await advancePoll();
    expect(screen.getByText("150.00")).toBeInTheDocument();
    expect(screen.getByText(/armed/i)).toBeInTheDocument();
  });

  it("does not fire when there is no quote (fetch rejects)", async () => {
    await seed({ symbol: "FAIL", direction: "above", threshold: 200 });
    const fq = fetchQuote as ReturnType<typeof vi.fn>;
    fq.mockRejectedValue(new Error("quote unavailable"));

    await mountPane();
    expect(screen.getByText("FAIL")).toBeInTheDocument();

    await advancePoll();
    await advancePoll();
    expect(toast.info).not.toHaveBeenCalled();
    // recordFire must not have run: fired_count stays 0.
    const rows = await loadAlerts();
    expect(rows.find((r) => r.symbol === "FAIL")?.fired_count).toBe(0);
  });
});
