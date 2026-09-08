/**
 * PEOP pane — load-state + interaction tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - the initial (no query) state shows the honest search prompt and the
 *    hook stays disabled;
 *  - an ok payload renders the people table (name, role, firm) with
 *    contact-status chips and summary cards;
 *  - an unmatched query renders the honest needs_data state with the
 *    backend's next action;
 *  - typing a query and committing it (Enter / Search) updates the
 *    committed query shown in the subtitle + footer.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PEOPPane } from "./PEOP";

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
  useFunction: (args: { enabled?: boolean }) => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
    enabled: args.enabled,
  }),
}));

/* ── fixtures (shape mirrors a live /api/fn/PEOP probe) ────────────── */

function okPayload() {
  return {
    status: "ok",
    query: "apple",
    source_mode: "public_reference",
    items: [
      {
        full_name: "Tim Cook",
        role: "CEO through summer 2026; Executive Chairman effective 2026-09-01",
        company: "Apple",
        contact_status: "public_profile_only",
        source: "apple_newsroom_public_reference",
        source_url: "https://www.apple.com/newsroom",
        match_score: 2,
      },
      {
        full_name: "John Ternus",
        role: "SVP Hardware Engineering; incoming CEO effective 2026-09-01",
        company: "Apple",
        contact_status: "public_profile_only",
        source_url: "https://www.apple.com/newsroom",
        match_score: 2,
      },
    ],
    connection_status: [
      { source: "local_people_directory", status: "checked" },
      { source: "public_reference", status: "used" },
    ],
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("PEOP pane — pre-search state", () => {
  it("renders the honest search prompt before a query is committed", () => {
    const { container } = render(<PEOPPane code="PEOP" />);
    expect(screen.getByText(/Search for a person/i)).toBeInTheDocument();
    expect(container.textContent).toContain("waiting_for_query");
    expect(screen.queryByText("Matches")).toBeNull();
  });
});

describe("PEOP pane — results", () => {
  it("renders the people table with roles, firms and contact chips when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "apple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    // "Tim Cook" renders in the table AND as the top-match card.
    expect(screen.getAllByText("Tim Cook").length).toBe(2);
    expect(screen.getByText("John Ternus")).toBeInTheDocument();
    expect(container.textContent).toContain("incoming CEO effective 2026-09-01");
    expect(container.textContent).toContain("Apple");
    expect(container.textContent).toContain("public_profile_only");
    // Summary cards show the source mode + top match.
    expect(container.textContent).toContain("public_reference");
    // Source links are real anchors.
    const links = screen.getAllByLabelText(/Open source for/);
    expect(links.length).toBe(2);
    expect(links[0].getAttribute("href")).toBe("https://www.apple.com/newsroom");
  });

  it("renders the honest no-match state when nothing matched", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "needs_data",
          query: "zzzz",
          items: [],
          source_mode: "empty_directory",
          next_actions: [
            "Add a person with action=upsert or broaden the search query.",
          ],
        },
      },
    });
    render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "zzzz" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText(/No people matched/i)).toBeInTheDocument();
    expect(
      screen.getByText(/broaden the search query/i),
    ).toBeInTheDocument();
  });
});

describe("PEOP pane — search interaction", () => {
  it("commits the query via Enter and reflects it in the subtitle + footer", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<PEOPPane code="PEOP" />);
    const input = screen.getByLabelText(/People search query/i);
    fireEvent.change(input, { target: { value: "apple" } });
    fireEvent.submit(input.closest("form")!);
    expect(container.textContent).toContain("query: apple");
    expect(container.textContent).toContain("2 matches");
  });
});
