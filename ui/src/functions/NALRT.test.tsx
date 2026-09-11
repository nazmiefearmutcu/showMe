/**
 * NALRT pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - an ok payload renders the alert list with severity pills + impact
 *    scores, the KPI ribbon and the feed_health strip;
 *  - "no alerts above threshold" is distinct from "no headlines returned"
 *    (provider outage) and neither fabricates rows;
 *  - threshold and freshness-window controls persist under
 *    `showme.nalrt.*` and activate on click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NALRTPane } from "./NALRT";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures (shape mirrors a live /api/fn/NALRT probe) ───────────── */

function okPayload() {
  return {
    alerts: [
      {
        title: "Fed signals surprise hike",
        source: "reuters",
        age_minutes: 42,
        importance_score: 88.5,
        severity: "critical",
        alert: true,
        matched_terms: ["FED"],
        url: "https://example.com/a",
      },
      {
        title: "Semis rally on raised guidance",
        source: "cnbc",
        age_minutes: 300,
        importance_score: 74.2,
        severity: "high",
        alert: true,
        matched_terms: ["NVDA"],
        url: "https://example.com/b",
      },
    ],
    top: [
      {
        title: "Fed signals surprise hike",
        source: "reuters",
        age_minutes: 42,
        importance_score: 88.5,
        severity: "critical",
      },
      {
        title: "Retail sales steady",
        source: "bloomberg",
        age_minutes: 700,
        importance_score: 55.1,
        severity: "medium",
      },
    ],
    health: { feeds: 12, ok: 11, failed: 1, ok_rate: 0.917, median_latency_ms: 412, items: 87 },
    feed_health: [
      { feed: "reuters", ok: true, latency_ms: 212, items: 30 },
      { feed: "cnbc", ok: false, error: "timeout" },
    ],
    threshold: 70,
    freshness_max_hours: 24,
    query: "AAPL",
    symbol: "AAPL",
    alert_count: 2,
    top_importance_score: 88.5,
    methodology: "deterministic_impact_score_v2",
  };
}

beforeEach(() => {
  // NALRT controls persist under showme.nalrt.* — clear between tests.
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("NALRT pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<NALRTPane code="NALRT" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("NALRT pane — alerts", () => {
  it("renders severity pills, impact scores and the feed_health strip when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<NALRTPane code="NALRT" symbol="AAPL" />);
    // Both severity pills render with their scores nearby.
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(container.textContent).toContain("88.5");
    expect(container.textContent).toContain("74.2");
    expect(screen.getByText("Fed signals surprise hike")).toBeInTheDocument();
    // Alert age formatting: 42m and 5.0h.
    expect(container.textContent).toContain("42m");
    expect(container.textContent).toContain("5.0h");
    // Feed health strip: one healthy feed, one failed.
    expect(screen.getByText(/reuters 212ms/)).toBeInTheDocument();
    expect(screen.getByText(/cnbc failed/)).toBeInTheDocument();
    // KPI: feeds ok ribbon.
    expect(container.textContent).toContain("11/12");
  });

  it("distinguishes 'no alerts above threshold' from a provider outage", () => {
    const payload = okPayload();
    setMockFn({
      state: "ok",
      data: { data: { ...payload, alerts: [], alert_count: 0 } },
    });
    const { container } = render(<NALRTPane code="NALRT" symbol="AAPL" />);
    expect(screen.getByText(/No alerts above threshold/i)).toBeInTheDocument();
    // The empty state explains WHY: top ranked score + freshness window.
    expect(container.textContent).toContain("top ranked score 88.5");
  });

  it("renders the honest outage state when no headlines came back at all", () => {
    const payload = okPayload();
    setMockFn({
      state: "ok",
      data: {
        data: {
          ...payload,
          alerts: [],
          alert_count: 0,
          top: [],
          feed_health: [],
          health: { feeds: 0, ok: 0, failed: 0, ok_rate: 0, median_latency_ms: null, items: 0 },
        },
      },
    });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    expect(screen.getByText(/No headlines returned/i)).toBeInTheDocument();
    expect(screen.queryByText(/No alerts above threshold/i)).toBeNull();
  });
});

describe("NALRT pane — alert links (AUDIT A10 [M])", () => {
  it("renders the title as an absolute-URL link in a new tab", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    const link = screen.getByRole("link", { name: /Fed signals surprise hike/i });
    expect(link).toHaveAttribute("href", "https://example.com/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("refuses to link a non-absolute or script URL (guarded like BRIEF/READ)", () => {
    const payload = okPayload();
    const alerts = [
      {
        title: "Unsafe url story",
        source: "wire",
        age_minutes: 10,
        importance_score: 81,
        severity: "high",
        alert: true,
        matched_terms: [],
        url: "javascript:alert(1)",
        link: "//evil.example.com/story",
      },
    ];
    setMockFn({ state: "ok", data: { data: { ...payload, alerts, alert_count: 1 } } });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    // The headline still renders — as plain text, never as a link.
    expect(screen.getByText("Unsafe url story")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Unsafe url story/i })).toBeNull();
  });
});

describe("NALRT pane — controls", () => {
  it("persists and activates the threshold control", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    const strict = screen.getByRole("button", { name: "85" });
    expect(strict).not.toBeDisabled();
    fireEvent.click(strict);
    expect(strict).toBeDisabled();
    expect(strict.className).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.nalrt.threshold")).toBe("85");
  });

  it("persists and activates the freshness window control", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<NALRTPane code="NALRT" symbol="AAPL" />);
    const wide = screen.getByRole("button", { name: "48h" });
    fireEvent.click(wide);
    expect(wide).toBeDisabled();
    expect(wide.className).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.nalrt.age")).toBe("48");
  });
});
