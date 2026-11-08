/**
 * ESG pane — header names the data it shows (P2A G14, ESG#6).
 *
 * The header used to say "vendor scoring" for every non-outage payload, so an
 * SEC filing-mention proxy or an empty payload was headed as a vendor score.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: unknown;
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

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("ESG pane — header honesty", () => {
  it("labels a payload with a vendor score as a vendor score", () => {
    mockFn.data = {
      status: "ok",
      sources: ["yfinance"],
      data: {
        status: "ok",
        symbol: "AAPL",
        totalEsg: 22,
        environmentScore: 5,
        socialScore: 9,
        governanceScore: 8,
        controversyLevel: 1,
        rows: [
          { pillar: "total", score: 22, source_mode: "live_yfinance", scale: "vendor risk scale (lower=better)" },
        ],
      },
    };
    const { container } = render(<ESGPane code="ESG" symbol="AAPL" />);
    expect(container.textContent).toContain("AAPL · vendor score");
    expect(container.textContent).not.toContain("vendor scoring");
    expect(container.textContent).not.toContain("ESG scores");
  });

  it("labels the SEC text proxy as a proxy, not a vendor score", () => {
    mockFn.data = {
      status: "ok",
      sources: ["sec_edgar"],
      data: {
        status: "ok",
        symbol: "AAPL",
        rows: [
          { pillar: "total", score: 14, source_mode: "sec_text_proxy", scale: "filing mentions" },
        ],
      },
    };
    const { container } = render(<ESGPane code="ESG" symbol="AAPL" />);
    expect(container.textContent).toContain("SEC filing-mention proxy (no vendor score)");
    expect(container.textContent).not.toContain("AAPL · vendor score");
    expect(container.textContent).not.toContain("vendor scoring");
  });

  it("does not claim a vendor score when the payload carries no score", () => {
    mockFn.data = {
      status: "ok",
      sources: [],
      data: { status: "ok", symbol: "AAPL", rows: [] },
    };
    const { container } = render(<ESGPane code="ESG" symbol="AAPL" />);
    expect(container.textContent).toContain("no score returned");
    expect(container.textContent).not.toContain("vendor score");
    expect(container.textContent).not.toContain("vendor scoring");
  });
});
