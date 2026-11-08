/**
 * IPO pane — awareness contract tests.
 *
 * Pins: provider_unavailable shows AwarenessUnavailable; empty windows say so;
 * sections render in the order Upcoming, Priced, Filed, Withdrawn; price shows
 * the offer price when priced and the range otherwise; "n/a" when neither
 * exists; the status filter narrows to one section.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { IPOPane } from "./IPO";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

const SECTIONS = {
  upcoming: [
    {
      date: "2026-11-20",
      symbol: "NEWC",
      company: "New Co",
      exchange: "NYSE",
      price: null,
      price_range: "$17.00–19.00",
      shares_offered: 12_000_000,
      deal_size_usd: 220_000_000,
      status: "upcoming",
      sources: [],
    },
  ],
  priced: [
    {
      date: "2026-11-03",
      symbol: "PRCD",
      company: "Priced Inc",
      exchange: "NASDAQ",
      price: 26,
      price_range: null,
      shares_offered: 5_000_000,
      deal_size_usd: 1_300_000_000,
      status: "priced",
      sources: [{ provider: "awareness" }],
    },
  ],
  filed: [],
  withdrawn: [
    {
      date: "2026-10-10",
      symbol: "WDRW",
      company: "Withdrawn Ltd",
      exchange: "NYSE",
      price: null,
      price_range: null,
      shares_offered: null,
      deal_size_usd: null,
      status: "withdrawn",
      sources: [],
    },
  ],
};

beforeEach(() => setMockFn({ state: "idle" }));
afterEach(() => cleanup());

describe("IPOPane", () => {
  it("renders AwarenessUnavailable with the reason and no sections", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "provider_unavailable", reason: "no route", sections: {} } },
    });
    render(<IPOPane code="IPO" />);
    expect(screen.getByRole("alert").textContent).toContain("no route");
    expect(screen.queryByLabelText("Priced IPOs")).toBeNull();
  });

  it("says no activity when every section is empty", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          sections: { upcoming: [], priced: [], filed: [], withdrawn: [] },
        },
      },
    });
    render(<IPOPane code="IPO" />);
    expect(screen.getByText("No IPO activity in this window")).toBeTruthy();
  });

  it("renders sections in the order upcoming, priced, filed, withdrawn", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", sections: SECTIONS } } });
    render(<IPOPane code="IPO" />);
    const sections = Array.from(
      document.querySelectorAll(".aw-ipo__section .aw-ipo__secname"),
    ).map((el) => el.textContent);
    expect(sections).toEqual(["Upcoming", "Priced", "Filed", "Withdrawn"]);
  });

  it("shows the offer price when priced and the range when upcoming", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", sections: SECTIONS } } });
    render(<IPOPane code="IPO" />);
    expect(screen.getByText("$26.00")).toBeTruthy();
    expect(screen.getByText("$17.00–19.00")).toBeTruthy();
  });

  it("shows n/a when neither price nor range is reported", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", sections: SECTIONS } } });
    render(<IPOPane code="IPO" />);
    const withdrawn = screen.getByText("WDRW").closest("[role='row']") as HTMLElement;
    expect(withdrawn.textContent).toContain("n/a");
  });

  it("filters to one section with the status control", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", sections: SECTIONS } } });
    render(<IPOPane code="IPO" />);
    fireEvent.click(screen.getByRole("button", { name: /Priced 1/ }));
    expect(screen.queryByLabelText("Upcoming IPOs")).toBeNull();
    expect(screen.getByLabelText("Priced IPOs")).toBeTruthy();
  });
});
