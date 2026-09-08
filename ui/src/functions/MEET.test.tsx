/**
 * MEET pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - a live briefing payload renders section chips, grouped rows with honest
 *    status pills, connector summary and pre-meeting questions;
 *  - connector statuses that are not ready surface honestly (granola
 *    `not_configured_or_empty`, news `not_available`) — nothing fabricated;
 *  - the section filter chips narrow the row list on click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MEETPane } from "./MEET";

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

/* ── fixtures (shape mirrors a live /api/fn/MEET probe) ────────────── */

function okPayload() {
  return {
    topic: "Apple",
    status: "ok",
    meeting_date: "2026-09-06",
    company: { name: "Apple", sector: "Technology", ceo: "Tim Cook" },
    rows: [
      {
        section: "participant",
        name: "Tim Cook",
        role: "Executive Chairman effective 2026-09-01",
        company: "Apple",
        status: "public_profile_only",
        source: "apple_newsroom_public_reference",
        source_url: "https://www.apple.com/newsroom",
      },
      {
        section: "meeting_note",
        title: "No recent Granola notes returned",
        status: "not_configured_or_empty",
        source: "granola",
      },
      {
        section: "news",
        title: "No recent live news returned for Apple",
        status: "not_available",
        source: "news",
      },
      {
        section: "portfolio",
        title: "No matching portfolio position found",
        status: "not_linked",
        source: "portfolio_state",
      },
    ],
    briefing_sections: [
      { section: "participants", status: "ready", count: 1 },
      { section: "meeting_notes", status: "not_configured_or_empty", count: 0 },
      { section: "news", status: "not_available", count: 0 },
      { section: "portfolio", status: "not_linked", count: 0 },
    ],
    connection_status: [
      { source: "notion", status: "configured" },
      { source: "granola", status: "configured" },
      { source: "gdelt", status: "configured" },
      { source: "people_public_reference", status: "used" },
    ],
    questions: [
      "What changed since the last meeting or review?",
      "Which person owns the next follow-up?",
    ],
    methodology: "MEET builds a meeting brief from configured connectors.",
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("MEET pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<MEETPane code="MEET" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<MEETPane code="MEET" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("MEET pane — briefing body", () => {
  it("renders section chips, grouped rows and questions when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<MEETPane code="MEET" symbol="AAPL" />);
    // Participants row with honest contact status.
    expect(screen.getByText("Tim Cook")).toBeInTheDocument();
    expect(container.textContent).toContain("public_profile_only");
    // Section status chips carry the honest connector outcome.
    expect(container.textContent).toContain("meeting_notes · not_configured_or_empty (0)");
    expect(container.textContent).toContain("news · not_available (0)");
    // Honest placeholder rows (backend-provided, not fabricated by the pane).
    expect(container.textContent).toContain("No recent Granola notes returned");
    expect(container.textContent).toContain("No recent live news returned for Apple");
    // Connector summary card.
    expect(container.textContent).toContain("4/4");
    // Pre-meeting questions.
    expect(screen.getByText(/What changed since the last meeting/i)).toBeInTheDocument();
  });

  it("narrows the row list when a section filter chip is clicked", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<MEETPane code="MEET" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "news" }));
    expect(screen.queryByText("Tim Cook")).toBeNull();
    expect(screen.getByText(/No recent live news returned for Apple/i)).toBeInTheDocument();
  });
});

describe("MEET pane — topic interaction", () => {
  it("commits a typed topic via the Brief button", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<MEETPane code="MEET" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText(/Meeting topic/i), {
      target: { value: "Nvidia" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Brief" }));
    expect(container.textContent).toContain("Nvidia");
  });
});
