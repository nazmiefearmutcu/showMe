/**
 * ECST pane — RANGE and TRANSFORM controls (ECST#5).
 *
 * The backend reads date_range and transform; the pane must send them. Only the
 * non-default values go on the wire, so the default request is unchanged.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { ECSTPane } from "./ECST";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

function okPayload(unit: string) {
  return {
    data: {
      data: {
        series_id: "CPIAUCSL",
        series_name: "US CPI all urban consumers",
        unit,
        frequency: "monthly",
        source_mode: "fred",
        transform: unit === "% y/y" ? "yoy" : "level",
        rows: [
          { date: "2026-04-01", value: 3.1, unit, frequency: "monthly", source_mode: "fred" },
          { date: "2026-05-01", value: 3.4, unit, frequency: "monthly", source_mode: "fred" },
        ],
        cards: [{ label: "Latest", value: 3.4 }],
        methodology: "…",
        field_dictionary: {},
      },
    },
    sources: ["fred"],
    warnings: [],
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  lastFnArgs = undefined;
  mockFn.state = "ok";
  mockFn.data = okPayload("index").data;
  mockFn.error = null;
  mockFn.refetch = vi.fn();
});
afterEach(() => {
  cleanup();
});

describe("ECST pane — RANGE control", () => {
  it("sends date_range only when a non-default window is picked", () => {
    render(<ECSTPane code="ECST" />);
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });

    const range = screen.getByLabelText("Observation window");
    fireEvent.click(within(range).getByRole("button", { name: "5Y" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL", date_range: "5Y" });
    expect(localStorage.getItem("showme.ecst.range")).toBe("5Y");

    fireEvent.click(within(range).getByRole("button", { name: "10Y" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });
  });

  it("sends MAX for the full history", () => {
    render(<ECSTPane code="ECST" />);
    const range = screen.getByLabelText("Observation window");
    fireEvent.click(within(range).getByRole("button", { name: "MAX" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL", date_range: "MAX" });
  });
});

describe("ECST pane — TRANSFORM control", () => {
  it("sends transform=yoy when Y/Y % is picked, and drops it back to level", () => {
    render(<ECSTPane code="ECST" />);
    const transform = screen.getByLabelText("Level or year-over-year percent change");
    fireEvent.click(within(transform).getByRole("button", { name: "Y/Y %" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL", transform: "yoy" });
    expect(localStorage.getItem("showme.ecst.transform")).toBe("yoy");

    fireEvent.click(within(transform).getByRole("button", { name: "Level" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });
  });

  it("shows the y/y unit from the backend payload, not the level unit", () => {
    mockFn.data = okPayload("% y/y").data;
    render(<ECSTPane code="ECST" />);
    expect(screen.getAllByText("% y/y").length).toBeGreaterThan(0);
  });

  it("combines range, transform and compare params", () => {
    render(<ECSTPane code="ECST" />);
    fireEvent.click(within(screen.getByLabelText("Observation window")).getByRole("button", { name: "3Y" }));
    fireEvent.click(within(screen.getByLabelText("Level or year-over-year percent change")).getByRole("button", { name: "Y/Y %" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL", date_range: "3Y", transform: "yoy" });
  });
});
