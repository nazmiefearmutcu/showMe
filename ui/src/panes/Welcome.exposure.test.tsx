/**
 * Welcome exposure panel — live tape + manual add form (2026-09-15).
 *
 * With an empty portfolio book the panel must stay ALIVE: it renders the
 * watchlist's live cross-asset tape from the shared quote fan-out (no extra
 * network) and a manual add-position form that POSTs to the new
 * /api/portfolio/positions route. The masthead's Trade ticket button also
 * points at the real trade-ticket pane (BBGT), not the news squawk line.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import type { QuoteView } from "@/lib/market-data";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";

const hoisted = vi.hoisted(() => ({
  quotes: {} as Record<string, QuoteView>,
  fetchMock: vi.fn(),
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => hoisted.quotes,
}));

vi.mock("@/lib/sidecar", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/sidecar")>();
  return { ...actual, sidecarFetch: hoisted.fetchMock };
});

import { Welcome } from "./Welcome";

beforeEach(() => {
  cleanup();
  localStorage.clear();
  hoisted.quotes = {};
  hoisted.fetchMock.mockReset();
  window.location.hash = "";
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
  });
});

afterEach(() => {
  cleanup();
});

function quote(assetClass: string, price: number, changePct: number): QuoteView {
  return {
    symbol: "X",
    price,
    changePct,
    snapshot: { asset_class: assetClass },
  } as unknown as QuoteView;
}

describe("Welcome exposure panel — live tape", () => {
  it("renders the live cross-asset tape when the portfolio book is empty", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({
        rows: [
          { symbol: "AAPL", label: "Apple" },
          { symbol: "BTCUSDT", label: "Bitcoin" },
        ],
      }),
    );
    hoisted.quotes = {
      AAPL: quote("equity", 210, 1.5),
      BTCUSDT: quote("crypto", 76000, -3),
    };
    const { findByTestId } = render(<Welcome />);
    const tape = await findByTestId("exposure-live-tape");
    await waitFor(() => expect(tape.textContent).toMatch(/equity/i));
    expect(tape.textContent).toMatch(/\+1\.50%/);
    expect(tape.textContent).toMatch(/-3\.00%/);
    expect(tape.textContent).toMatch(/1 sym/);
    // The manual add form rides along so the empty book is actionable.
    expect(tape.querySelector('[data-testid="exposure-add-form"]')).not.toBeNull();
  });

  it("submits the add-position form to /api/portfolio/positions", async () => {
    hoisted.fetchMock.mockResolvedValue({ ok: true });
    const { findByTestId, getByLabelText } = render(<Welcome />);
    const form = await findByTestId("exposure-add-form");
    fireEvent.change(getByLabelText("Position symbol"), { target: { value: "tsla" } });
    fireEvent.change(getByLabelText("Position quantity"), { target: { value: "5" } });
    fireEvent.change(getByLabelText("Average cost"), { target: { value: "240.5" } });
    fireEvent.submit(form);
    await waitFor(() => expect(hoisted.fetchMock).toHaveBeenCalledTimes(1));
    const [path, init] = hoisted.fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/portfolio/positions");
    expect(JSON.parse(String(init?.body))).toEqual({
      symbol: "TSLA",
      quantity: 5,
      avg_cost: 240.5,
    });
  });

  it("surfaces a validation error without calling the sidecar", async () => {
    const { findByTestId, getByLabelText, findByText } = render(<Welcome />);
    const form = await findByTestId("exposure-add-form");
    fireEvent.change(getByLabelText("Position symbol"), { target: { value: "TSLA" } });
    fireEvent.submit(form);
    await findByText(/positive qty/i);
    expect(hoisted.fetchMock).not.toHaveBeenCalled();
  });
});

describe("Welcome masthead — trade ticket target", () => {
  it("opens the multi-asset trade ticket pane (BBGT), not the news squawk line", async () => {
    const { findByText } = render(<Welcome />);
    const button = await findByText("Trade ticket");
    fireEvent.click(button);
    expect(window.location.hash).toBe("#/fn/BBGT");
  });
});
