/**
 * ESG pane — score polarity + proxy caption truth (F6).
 *
 * Backend semantics: lower vendor ESG risk score = better. The pane used to
 * paint `score >= 50` green (an 85-risk company showed green, a 30-risk one
 * red) and hard-coded the KPI caption "VENDOR SCORE" even when the payload
 * was an SEC EDGAR text-proxy filing-mention count. These tests pin:
 *  - vendor polarity (low = positive, high = negative);
 *  - proxy rows get the proxy caption, neutral tone and visible warnings;
 *  - the outage state never claims a vendor score.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?:
    | {
        data?: unknown;
        status?: string;
        sources?: string[];
        elapsed_ms?: number;
        metadata?: Record<string, unknown>;
      }
    | undefined;
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
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { ESGPane } from "./ESG";

function vendorData(score: number) {
  const rows = [
    { pillar: "total", score, scale: "vendor risk scale (lower=better)", source_mode: "live_yfinance" },
    { pillar: "environment", score: score - 5, scale: "vendor risk scale (lower=better)", source_mode: "live_yfinance" },
    { pillar: "social", score: score - 8, scale: "vendor risk scale (lower=better)", source_mode: "live_yfinance" },
    { pillar: "governance", score: score - 3, scale: "vendor risk scale (lower=better)", source_mode: "live_yfinance" },
    { pillar: "controversy", score: 1, scale: "level 1-5", source_mode: "live_yfinance" },
  ];
  return {
    status: "ok",
    data: {
      status: "ok",
      symbol: "AAPL",
      totalEsg: score,
      environmentScore: score - 5,
      socialScore: score - 8,
      governanceScore: score - 3,
      controversyLevel: 1,
      data_mode: "delayed_reference",
      rows,
    },
    sources: ["yfinance"],
    metadata: { source_kind: "sustainalytics" },
    elapsed_ms: 10,
  };
}

function proxyData() {
  return {
    status: "ok",
    data: {
      status: "ok",
      symbol: "ZZZZ",
      totalEsg: 15,
      environmentScore: 3,
      socialScore: 5,
      governanceScore: 7,
      controversyLevel: null,
      data_mode: "cached_snapshot",
      rows: [
        { pillar: "total", score: 15, scale: "filing mentions (proxy)", source_mode: "sec_text_proxy" },
        { pillar: "environment", score: 3, scale: "filing mentions (proxy)", source_mode: "sec_text_proxy" },
        { pillar: "social", score: 5, scale: "filing mentions (proxy)", source_mode: "sec_text_proxy" },
        { pillar: "governance", score: 7, scale: "filing mentions (proxy)", source_mode: "sec_text_proxy" },
      ],
      warnings: [
        "No vendor ESG score available for this ticker; values are a derived SEC text proxy (filing-mention counts), not risk scores.",
      ],
    },
    sources: ["sec_edgar"],
    metadata: { source_kind: "sec_text_proxy" },
    elapsed_ms: 12,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("ESG pane — score polarity + proxy captions", () => {
  it("paints a HIGH vendor risk score negative (lower is better)", () => {
    mockFn.state = "ok";
    mockFn.data = vendorData(85);
    const { container } = render(<ESGPane code="ESG" symbol="AAPL" />);
    const total = screen.getByText("Total").closest(".stat-card");
    expect(total).not.toBeNull();
    expect(total!.className).toContain("stat-card--negative");
    expect(container.textContent).toContain("VENDOR RISK SCORE (LOWER IS BETTER)");
  });

  it("paints a LOW vendor risk score positive", () => {
    mockFn.state = "ok";
    mockFn.data = vendorData(20);
    render(<ESGPane code="ESG" symbol="AAPL" />);
    const total = screen.getByText("Total").closest(".stat-card");
    expect(total).not.toBeNull();
    expect(total!.className).toContain("stat-card--positive");
  });

  it("captions SEC text-proxy counts as a filing-mention proxy and renders warnings", () => {
    mockFn.state = "ok";
    mockFn.data = proxyData();
    const { container } = render(<ESGPane code="ESG" symbol="ZZZZ" />);
    expect(container.textContent).toContain("SEC FILING-MENTION PROXY");
    expect(container.textContent).not.toContain("VENDOR SCORE");
    // Counts have no risk polarity — never painted green/red like a score.
    const total = screen.getByText("Total").closest(".stat-card");
    expect(total!.className).toContain("stat-card--neutral");
    // Backend warnings are surfaced, not dropped.
    expect(screen.getByTestId("esg-warnings")).toBeInTheDocument();
    expect(screen.getByText(/not risk scores/i)).toBeInTheDocument();
  });

  it("never claims a vendor score during a provider outage", () => {
    mockFn.state = "ok";
    mockFn.data = {
      status: "provider_unavailable",
      data: {
        status: "provider_unavailable",
        rows: [],
        totalEsg: null,
        environmentScore: null,
        socialScore: null,
        governanceScore: null,
        controversyLevel: null,
        reason: "No Yahoo Finance sustainability data and SEC EDGAR full-text search is unavailable.",
        next_actions: ["Retry later", "Verify the ticker is a US SEC filer"],
        rows_empty: true,
      },
      sources: ["yfinance", "sec_edgar"],
      metadata: {},
      elapsed_ms: 4,
    };
    const { container } = render(<ESGPane code="ESG" symbol="AAPL" />);
    expect(container.textContent).toContain("VENDOR UNAVAILABLE");
    expect(container.textContent).not.toContain("VENDOR SCORE");
    expect(screen.getByText(/retry later/i)).toBeInTheDocument();
  });
});
