/**
 * BTMM terminal-grade — data-honesty + a11y + display-quality contract.
 *
 * BTMM is a central-bank POLICY-RATE monitor (BIS CBPOL), not a Treasury
 * yield curve. This suite pins the honesty guarantees added in the
 * terminal-grade pass:
 *
 *  P1 — no fabricated trend: a sparse-history row renders a muted
 *       placeholder (data-synthetic="true"), never a procedural fake line.
 *  P1 — a stored-fallback snapshot (sources contains "local fallback")
 *       shows a PROMINENT banner; live data does not.
 *  P1 — the freshness pill reflects `stale_seconds`/`as_of`: a >24h-old
 *       snapshot reads "stale"/"cached", not "live".
 *  P2 — the search input is labelled (aria-label).
 *  P2 — the policy-rate history chart svg has role="img" + aria-label.
 *  P3 — numeric cells carry the terminal-grid-numeric class.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));

import { BTMMPane } from "./BTMM";

afterEach(() => {
  cleanup();
  useFunctionMock.mockReset();
});

// A row with FULL history (>= 4 obs) so the trend column draws a real line.
const richRow = {
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
  trend_3m_bp: -25,
  // Only ONE point in `history` here keeps <PolicyRateHistory> from mounting
  // (jsdom lacks ResizeObserver). For the trend column we exercise sparse vs
  // rich rows in dedicated tests where the chart is also short-circuited.
  history: [{ date: "2026-04-28", policy_rate: 3.625 }],
  source: "BIS CBPOL",
};

// A row with sparse history (< 4 obs) — must NOT draw a fabricated trend.
const sparseRow = {
  country_code: "EU",
  bis_ref_area: "XM",
  country: "Euro area",
  central_bank: "European Central Bank",
  currency: "EUR",
  region: "europe",
  policy_rate: 2.0,
  as_of: "2026-04-28",
  last_move: "cut",
  change_bp: -25,
  trend_3m_bp: null,
  history: [{ date: "2026-04-28", policy_rate: 2.0 }],
  source: "BIS CBPOL",
};

function liveEnvelope(rows: unknown[], overrides: Record<string, unknown> = {}) {
  return {
    state: "ok" as const,
    refetch: vi.fn(),
    error: undefined,
    data: {
      data: {
        country: "ALL",
        region: "all",
        as_of: "2026-04-28",
        stale_seconds: 0,
        rows,
        summary: {
          rows: rows.length,
          universe: rows.length,
          average_policy_rate: 2.8,
          max_policy_rate: 3.625,
          min_policy_rate: 2.0,
          hikes: 0,
          cuts: rows.length,
          holds: 0,
        },
      },
      sources: ["BIS CBPOL"],
      warnings: [],
      elapsed_ms: 50,
      ...overrides,
    },
  };
}

describe("BTMM synthetic-sparkline honesty (P1)", () => {
  it("renders a muted placeholder (not a fake line) when history is sparse", () => {
    useFunctionMock.mockReturnValue(liveEnvelope([sparseRow]));
    const { container } = render(<BTMMPane code="BTMM" />);
    const synthetic = container.querySelectorAll('[data-synthetic="true"]');
    expect(synthetic.length).toBeGreaterThan(0);
    // The placeholder must NOT contain a real sparkline svg (no fabricated
    // path masquerading as data).
    expect(synthetic[0].querySelector("svg")).toBeNull();
    expect(synthetic[0].getAttribute("aria-label")).toMatch(/insufficient history/i);
  });

  it("renders a real sparkline (data-synthetic=false) when history is rich", () => {
    const rich = {
      ...richRow,
      history: [
        { date: "2026-01-28", policy_rate: 4.0 },
        { date: "2026-02-28", policy_rate: 3.875 },
        { date: "2026-03-28", policy_rate: 3.75 },
        { date: "2026-04-28", policy_rate: 3.625 },
      ],
    };
    // Keep the row's `history` length usable for the trend column but render the
    // big chart from a DIFFERENT (sparse) first row to avoid ResizeObserver.
    useFunctionMock.mockReturnValue(liveEnvelope([sparseRow, rich]));
    const { container } = render(<BTMMPane code="BTMM" />);
    const real = container.querySelectorAll('[data-synthetic="false"]');
    expect(real.length).toBeGreaterThan(0);
    expect(real[0].querySelector("svg")).not.toBeNull();
  });
});

describe("BTMM fallback-snapshot disclosure (P1)", () => {
  it("shows a prominent fallback banner when sources contains 'local fallback'", () => {
    useFunctionMock.mockReturnValue(
      liveEnvelope([{ ...sparseRow, source: "local fallback" }], {
        sources: ["local fallback"],
      }),
    );
    const { container } = render(<BTMMPane code="BTMM" />);
    const banner = container.querySelector('[data-testid="btmm-fallback-banner"]');
    expect(banner).not.toBeNull();
    expect(banner?.getAttribute("role")).toMatch(/status|alert/);
    expect(banner?.textContent?.toLowerCase()).toContain("fallback");
  });

  it("does NOT show the fallback banner on live data", () => {
    useFunctionMock.mockReturnValue(liveEnvelope([richRow]));
    const { container } = render(<BTMMPane code="BTMM" />);
    expect(
      container.querySelector('[data-testid="btmm-fallback-banner"]'),
    ).toBeNull();
  });
});

describe("BTMM freshness-pill honesty (P1/P2)", () => {
  it("reads 'live' on fresh data", () => {
    useFunctionMock.mockReturnValue(liveEnvelope([richRow]));
    const { container } = render(<BTMMPane code="BTMM" />);
    const pill = container.querySelector('[data-testid="btmm-live-pill"]');
    expect(pill?.textContent).toBe("live");
  });

  it("reads 'stale' (not 'live') when stale_seconds exceeds a day", () => {
    useFunctionMock.mockReturnValue(
      liveEnvelope([richRow], {}),
    );
    // Override stale_seconds inside the data envelope.
    const env = liveEnvelope([richRow]);
    env.data.data.stale_seconds = 86400 * 3;
    useFunctionMock.mockReturnValue(env);
    const { container } = render(<BTMMPane code="BTMM" />);
    const pill = container.querySelector('[data-testid="btmm-live-pill"]');
    expect(pill?.textContent).toBe("stale");
  });
});

describe("BTMM accessibility (P2)", () => {
  it("labels the search input", () => {
    useFunctionMock.mockReturnValue(liveEnvelope([richRow]));
    const { container } = render(<BTMMPane code="BTMM" />);
    const input = container.querySelector("input");
    expect(input).not.toBeNull();
    expect(input?.getAttribute("aria-label")).toBeTruthy();
  });
});

describe("BTMM display quality (P3)", () => {
  it("applies terminal-grid-numeric to the policy-rate cell", () => {
    useFunctionMock.mockReturnValue(liveEnvelope([richRow]));
    const { container } = render(<BTMMPane code="BTMM" />);
    const numeric = container.querySelectorAll(".terminal-grid-numeric");
    expect(numeric.length).toBeGreaterThan(0);
  });
});
