/**
 * ECST compare pill — an unavailable compare leg is disclosed (G5 review).
 *
 * When the backend reports compare_source_mode "provider_unavailable" the
 * overlay is omitted. The pill must say the compare leg failed, not render a
 * neutral "vs <id>" as if the overlay were simply a plain series.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
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

/** Main series live; the compare leg reports the given source mode with no rows. */
function unavailableComparePayload(compareSourceMode: string) {
  return {
    data: {
      data: {
        series_id: "CPIAUCSL",
        series_name: "US CPI all urban consumers",
        unit: "index",
        frequency: "monthly",
        source_mode: "fred",
        status: "ok",
        rows: [
          { date: "2026-04-01", value: 310.1, unit: "index", frequency: "monthly", source_mode: "fred" },
          { date: "2026-05-01", value: 311.4, unit: "index", frequency: "monthly", source_mode: "fred" },
        ],
        cards: [{ label: "Latest", value: 311.4 }],
        methodology: "…",
        field_dictionary: {},
        compare_series_id: "DGS2",
        compare_series_name: "US 2Y Treasury yield",
        compare_source_mode: compareSourceMode,
      },
    },
    sources: ["fred"],
    warnings: ["DGS2 compare series was unavailable from the providers — the overlay is omitted."],
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("ECST pane — unavailable compare leg", () => {
  it("names the failed compare leg in the pill instead of a neutral vs label", () => {
    setMockFn({ state: "ok", ...unavailableComparePayload("provider_unavailable") });
    render(<ECSTPane code="ECST" />);
    const pill = screen.getByTestId("ecst-compare-pill");
    expect(pill.textContent).toContain("vs US 2Y Treasury yield");
    expect(pill.textContent).toContain("unavailable");
  });

  it("keeps the neutral pill when the compare leg is live", () => {
    setMockFn({ state: "ok", ...unavailableComparePayload("fred") });
    render(<ECSTPane code="ECST" />);
    const pill = screen.getByTestId("ecst-compare-pill");
    expect(pill.textContent).not.toContain("unavailable");
    expect(pill.textContent).not.toContain("baseline");
  });
});
