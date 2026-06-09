/**
 * ANR pane — a11y + honesty-surface + display contract tests.
 *
 * ANR is the Analyst Recommendations pane (consensus-first, with a Veryfinder
 * social overlay). The backend is already honest (synthetic targets are flagged
 * not_analyst_target, crypto consensus is labelled a market proxy, stale rows
 * are excluded by a 1Y rule, and aggregate buckets are left empty rather than
 * fabricated). These tests pin the FRONTEND upgrade that SURFACES those honest
 * fields and fixes the a11y/date gaps:
 *
 *  A1. the Veryfinder source <select> has an accessible name;
 *  A2. the Veryfinder load screen scopes its live region to the status message
 *      (the static step cards must sit OUTSIDE the aria-live region);
 *  A3. the consensus score renders as a role=meter clamped to [0,5];
 *  A4. the main RefreshButton reports aria-busy while a refresh is in flight;
 *  A5. the consensus rating Pills carry a buy/sell/hold aria-label;
 *  D1. backend data_notes (honesty caveats) are rendered when present;
 *  D2. providerLabel has human labels for article_context / unavailable;
 *  D3. raw ISO timestamps are formatted (with a UTC/"as of" marker) and an
 *      absent timestamp falls back to the "—" sentinel.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the pane
 * into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ANRPane } from "./anr_pane";
import { providerLabel } from "./anr_pane/formatters";
import { VeryfinderSearchLoadScreen } from "./anr_pane/veryfinder";
import { ConsensusCard } from "./anr_pane/cards";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch,
  }),
}));

// Visibility poll is irrelevant to render assertions — return a stable tick.
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

// Veryfinder transport is mocked so the pane never hits the real network. The
// fetch never resolves in tests; render assertions cover the static shell.
vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderQuery: vi.fn(() => new Promise(() => {})),
  recommendedVeryfinderSampleForSymbol: () => 50,
  normalizeVeryfinderSample: (value: string | number, fallback = 50) => {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.round(n) : fallback;
  },
}));

vi.mock("@/lib/symbols", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/symbols")>();
  return {
    ...actual,
    // Keep the background-refresh loop a no-op in tests.
    listRecentSymbols: () => [],
  };
});

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const AS_OF = "2026-06-09T11:55:00.000Z";

function okData(extra: Record<string, unknown> = {}) {
  return {
    status: "ok",
    symbol: "AMZN",
    summary: {
      label: "Buy",
      consensus_score: 3.8,
      analyst_count: 24,
      positive_pct: 62.5,
      neutral_pct: 25,
      negative_pct: 12.5,
      included_count: 24,
      excluded_stale_count: 2,
      last_updated: AS_OF,
      oldest_included_rating_date: "2025-09-01T00:00:00.000Z",
      target_price_source: "Derived from spot",
      consensus_source: "yfinance_recommendations",
    },
    analyst_rows: [],
    bucket_rows: [],
    target_rows: [],
    target_price_source: { mode: "derived", label: "Derived from spot", not_analyst_target: true },
    stale_rule: { rule_type: "stale_rating", cutoff_date: "2025-06-09", included_count: 24 },
    source_details: [],
    spot: 185.4,
    ...extra,
  };
}

function okPayload(extra: Record<string, unknown> = {}) {
  return {
    data: {
      data: okData(extra),
      sources: ["yfinance_recommendations"],
      elapsed_ms: 14,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  refetch.mockClear();
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("ANR pane — A1 Veryfinder source select accessible name", () => {
  it("labels the Veryfinder source <select> (getByLabelText)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    const select = screen.getByLabelText("Veryfinder kaynağı");
    expect(select.tagName).toBe("SELECT");
  });
});

describe("ANR pane — A2 scoped Veryfinder load live region", () => {
  it("announces the status message but NOT the static step cards", () => {
    render(
      <VeryfinderSearchLoadScreen
        target={50}
        requestedInput={50}
        source="auto"
        startedAt={null}
        previous={null}
        postsOpen={false}
        onTogglePosts={() => {}}
      />,
    );
    // The transient status/progress message is announced.
    const status = screen.getByRole("status");
    expect(status.textContent ?? "").toMatch(/Searching social reaction/i);
    // The static step cards (e.g. "Dedupe") must sit OUTSIDE the live region —
    // otherwise the 30s poll re-announces the whole shell (SR-spam).
    const stepCard = screen.getByText("Dedupe");
    expect(stepCard.closest("[aria-live]")).toBeNull();
  });
});

describe("ANR pane — A3 consensus score meter", () => {
  it("renders a role=meter clamped to [0,5] for an in-range score", () => {
    render(<ConsensusCard summary={{ label: "Buy", consensus_score: 3.8 }} symbol="AMZN" />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuemin", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "5");
    expect(meter).toHaveAttribute("aria-valuenow", "3.8");
    // Keep the visible text.
    expect(meter.textContent ?? "").toMatch(/3\.80 \/ 5/);
  });

  it("clamps an out-of-range score to the [0,5] band (does not leak)", () => {
    render(<ConsensusCard summary={{ label: "Buy", consensus_score: 7.2 }} symbol="AMZN" />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "5");
  });

  it("clamps a negative score up to 0", () => {
    render(<ConsensusCard summary={{ label: "Sell", consensus_score: -1 }} symbol="AMZN" />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "0");
  });
});

describe("ANR pane — A4 RefreshButton aria-busy", () => {
  it("flags the main RefreshButton aria-busy while a refresh is in flight", () => {
    setMockFn({ state: "refreshing", ...okPayload() });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    const refresh = screen.getByRole("button", { name: /Refresh analyst recommendations/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });

  it("does NOT flag aria-busy in the steady ok state", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    const refresh = screen.getByRole("button", { name: /Refresh analyst recommendations/i });
    expect(refresh).not.toHaveAttribute("aria-busy", "true");
  });
});

describe("ANR pane — A5 consensus rating aria-label", () => {
  it("labels the ConsensusCard rating pill with a consensus aria-label", () => {
    render(<ConsensusCard summary={{ label: "Buy", consensus_score: 3.8 }} symbol="AMZN" />);
    expect(screen.getByLabelText(/konsensüs: Buy/i)).toBeInTheDocument();
  });

  it("labels the header consensus pill in the full pane", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    expect(screen.getByLabelText(/konsensüs: BUY-LEANING/i)).toBeInTheDocument();
  });
});

describe("ANR pane — D1 surface backend data_notes", () => {
  it("renders data_notes when present", () => {
    setMockFn({
      state: "ok",
      ...okPayload({
        data_notes: [
          "Broker-level analyst rows require a provider that supplies analyst-detail recommendations.",
          "Derived target-price ranges are display references, not analyst targets.",
        ],
      }),
    });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    expect(screen.getByText(/Veri notları/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Derived target-price ranges are display references/i),
    ).toBeInTheDocument();
  });

  it("does NOT render a Veri notları section when data_notes is empty", () => {
    setMockFn({ state: "ok", ...okPayload({ data_notes: [] }) });
    render(<ANRPane code="ANR" symbol="AMZN" />);
    expect(screen.queryByText(/Veri notları/i)).toBeNull();
  });
});

describe("ANR pane — D2 providerLabel coverage", () => {
  it("labels article_context and unavailable (not raw snake_case)", () => {
    expect(providerLabel("article_context")).not.toBe("article_context");
    expect(providerLabel("article_context")).toBe("Makale bağlamı");
    expect(providerLabel("unavailable")).not.toBe("unavailable");
    expect(providerLabel("unavailable")).toBe("Kullanılamıyor");
  });

  it("keeps existing labels intact", () => {
    expect(providerLabel("yfinance")).toBe("Yahoo Finance");
  });
});

describe("ANR pane — D3 formatted consensus date", () => {
  it("formats a raw ISO last_updated with a UTC marker", () => {
    render(
      <ConsensusCard
        summary={{ label: "Buy", consensus_score: 3.8, last_updated: AS_OF }}
        symbol="AMZN"
      />,
    );
    const meta = screen.getByText(/last updated/i);
    // 11:55 UTC, not the raw ISO blob.
    expect(meta.textContent ?? "").toMatch(/11:55/);
    expect(meta.textContent ?? "").toMatch(/UTC/);
    expect(meta.textContent ?? "").not.toContain("2026-06-09T11:55:00.000Z");
  });

  it("falls back to the — sentinel when last_updated is absent", () => {
    render(<ConsensusCard summary={{ label: "Buy", consensus_score: 3.8 }} symbol="AMZN" />);
    const meta = screen.getByText(/last updated/i);
    expect(meta.textContent ?? "").toContain("—");
  });
});
