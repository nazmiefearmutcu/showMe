/**
 * BTMM UI regression — Bug #24.
 *
 * The header used to display a single "HH:MM UTC" pill computed from
 * `new Date()`, which made stale fallback data look freshly polled.
 * The pane now renders TWO stamps:
 *   - "Last poll HH:MM UTC" → wall-clock (unchanged source)
 *   - "Data as of <data.as_of>" → from the backend envelope
 *
 * The live pill must flip to "stale" when the BTMM backend pushes a
 * `data_stale_24h` warning into the warnings array (P1.3 freshness honesty;
 * the old generic "warn" label did not say WHY).
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));

import { BTMMPane } from "../BTMM";

afterEach(() => cleanup());

const baseRow = {
  country_code: "US",
  bis_ref_area: "US",
  country: "United States",
  central_bank: "Federal Reserve",
  currency: "USD",
  region: "americas",
  policy_rate: 3.625,
  as_of: "2026-04-28",
  last_move: "cut",
  change_bp: -25,
  // history left intentionally short so <PolicyRateHistory> short-circuits
  // (it returns null when points.length < 2). jsdom does not provide
  // ResizeObserver — the design-system ResizableChartFrame would crash.
  history: [{ date: "2026-04-28", policy_rate: 3.625 }],
  source: "BIS CBPOL",
};

describe("BTMM pane data-freshness stamps", () => {
  it("renders 'Data as of <payload.as_of>' from the backend envelope", () => {
    useFunctionMock.mockReturnValue({
      state: "ok" as const,
      refetch: vi.fn(),
      error: undefined,
      data: {
        data: {
          country: "ALL",
          region: "all",
          as_of: "2026-04-28",
          stale_seconds: 86400 * 2,
          rows: [baseRow],
          summary: { rows: 1, universe: 1, average_policy_rate: 3.625,
                     max_policy_rate: 3.625, min_policy_rate: 3.625,
                     hikes: 0, cuts: 1, holds: 0 },
        },
        sources: ["BIS CBPOL"],
        warnings: [],
        elapsed_ms: 50,
      },
    });

    const { container } = render(<BTMMPane code="BTMM" />);
    const dataStamp = container.querySelector('[data-testid="btmm-data-stamp"]');
    expect(dataStamp).not.toBeNull();
    expect(dataStamp?.textContent).toContain("Data as of");
    expect(dataStamp?.textContent).toContain("2026-04-28");

    const pollStamp = container.querySelector('[data-testid="btmm-poll-stamp"]');
    expect(pollStamp).not.toBeNull();
    expect(pollStamp?.textContent).toContain("Last poll");
    // Wall-clock pattern HH:MM UTC.
    expect(pollStamp?.textContent).toMatch(/Last poll \d{2}:\d{2} UTC/);
  });

  it("flips live pill to stale when backend emits data_stale_24h warning", () => {
    useFunctionMock.mockReturnValue({
      state: "ok" as const,
      refetch: vi.fn(),
      error: undefined,
      data: {
        data: {
          country: "ALL",
          region: "all",
          as_of: "2026-04-01",
          stale_seconds: 86400 * 23,
          rows: [baseRow],
          summary: { rows: 1, universe: 1, hikes: 0, cuts: 0, holds: 1 },
        },
        sources: ["BIS CBPOL"],
        warnings: ["data_stale_24h: freshest BIS observation 2026-04-01 is 552h old"],
        elapsed_ms: 50,
      },
    });
    const { container } = render(<BTMMPane code="BTMM" />);
    const livePill = container.querySelector('[data-testid="btmm-live-pill"]');
    // P1.3: a >24h-old snapshot reads "stale" (not the old generic "warn").
    expect(livePill?.textContent).toBe("stale");
  });

  it("shows '—' for Data as of when backend omits as_of", () => {
    useFunctionMock.mockReturnValue({
      state: "ok" as const,
      refetch: vi.fn(),
      error: undefined,
      data: {
        data: {
          country: "ALL",
          region: "all",
          rows: [baseRow],
          summary: { rows: 1, universe: 1, hikes: 0, cuts: 0, holds: 1 },
        },
        sources: ["BIS CBPOL"],
        warnings: [],
        elapsed_ms: 50,
      },
    });
    const { container } = render(<BTMMPane code="BTMM" />);
    const dataStamp = container.querySelector('[data-testid="btmm-data-stamp"]');
    expect(dataStamp?.textContent).toContain("Data as of");
    expect(dataStamp?.textContent).toContain("—");
  });
});
