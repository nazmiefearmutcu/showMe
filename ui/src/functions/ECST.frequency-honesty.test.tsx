/**
 * ECST pane — FREQUENCY control and honest not-applied notes (ECST#5 follow-up).
 *
 * The backend reads `frequency` and reports frequency_applied / vintage_applied with a
 * "ECST: frequency ... not applied" warning. The pane must expose the control, send the
 * param only when it is not native, and show the not-applied reason when the backend
 * could not honour the request.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { ECSTPane } from "./ECST";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: unknown;
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

function envelope(extra: Record<string, unknown> = {}, warnings: string[] = []) {
  return {
    data: {
      series_id: "CPIAUCSL",
      series_name: "US CPI all urban consumers",
      unit: "index",
      frequency: "monthly",
      source_mode: "fred",
      transform: "level",
      rows: [
        { date: "2026-04-01", value: 3.1, unit: "index", frequency: "monthly", source_mode: "fred" },
        { date: "2026-05-01", value: 3.4, unit: "index", frequency: "monthly", source_mode: "fred" },
      ],
      cards: [{ label: "Latest", value: 3.4 }],
      methodology: "…",
      field_dictionary: {},
      frequency_applied: true,
      vintage_applied: true,
      ...extra,
    },
    sources: ["fred"],
    warnings,
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  lastFnArgs = undefined;
  mockFn.state = "ok";
  mockFn.data = envelope();
  mockFn.error = null;
  mockFn.refetch = vi.fn();
});
afterEach(() => {
  cleanup();
});

describe("ECST pane — FREQUENCY control", () => {
  it("sends frequency only when a non-native frequency is picked", () => {
    render(<ECSTPane code="ECST" />);
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });

    const freq = screen.getByLabelText("Resampling frequency");
    fireEvent.click(within(freq).getByRole("button", { name: "Quarterly" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL", frequency: "quarterly" });
    expect(localStorage.getItem("showme.ecst.frequency")).toBe("quarterly");

    fireEvent.click(within(freq).getByRole("button", { name: "Native" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });
  });

  it("shows the backend not-applied reason when the frequency was not honoured", () => {
    const reason =
      "ECST: frequency quarterly not applied: no live provider returned observations, so nothing was served with the request";
    mockFn.data = envelope({ frequency_applied: false }, [reason]);
    render(<ECSTPane code="ECST" />);
    const note = screen.getByRole("note", { name: "ECST frequency not applied" });
    expect(note.textContent).toContain("no live provider returned observations");
  });

  it("shows no not-applied note when the frequency was honoured", () => {
    mockFn.data = envelope({ frequency_applied: true }, []);
    render(<ECSTPane code="ECST" />);
    expect(screen.queryByRole("note", { name: "ECST frequency not applied" })).toBeNull();
  });
});
