/**
 * PEOP pane — P2A-G03 honesty states.
 *
 * - PEOP#3: a provider outage shows the failure reason in the empty state,
 *   not the "add a person" next action.
 * - PEOP#2: rows served from the bundled reference snapshot carry a visible
 *   snapshot-date note, so they are never read as a live lookup.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PEOPPane } from "./PEOP";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

function search(query: string) {
  fireEvent.change(screen.getByLabelText(/People search query/i), {
    target: { value: query },
  });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
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

describe("PEOP pane — provider outage (PEOP#3)", () => {
  it("shows the failure reason and the retry hint, not 'add a person'", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        query: "jensen",
        items: [],
        source_mode: "provider_unavailable",
        reason: "wikipedia 503 from api.php",
        next_actions: [
          "Retry once the Wikipedia/Wikidata public API is reachable.",
          "Add a person with action=upsert to keep a private local record.",
        ],
      },
    };
    const { container } = render(<PEOPPane code="PEOP" />);
    search("jensen");

    expect(screen.getByText("People search unavailable")).toBeInTheDocument();
    expect(container.textContent).toContain("wikipedia 503 from api.php");
    expect(container.textContent).toContain("Retry once the Wikipedia");
    expect(container.textContent).not.toContain("Add a person");
    expect(container.textContent).not.toContain("No people matched");
  });
});

describe("PEOP pane — reference snapshot note (PEOP#2)", () => {
  it("labels public_reference rows with the snapshot date", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "needs_data",
        query: "apple",
        source_mode: "public_reference",
        reference_as_of: "2026-04-20",
        items: [
          {
            full_name: "Tim Cook",
            role: "Apple CEO; announced to become Executive Chairman",
            company: "Apple",
            contact_status: "public_profile_only",
            source_url: "https://www.apple.com/newsroom",
          },
        ],
      },
    };
    const { container } = render(<PEOPPane code="PEOP" />);
    search("apple");

    const note = screen.getByRole("note");
    expect(note.textContent).toContain("2026-04-20");
    expect(note.textContent).toContain("not a live lookup");
    expect(container.textContent).toContain("public_reference");
  });
});
