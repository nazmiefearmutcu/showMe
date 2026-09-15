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
import { downloadGridCsv } from "@/design-system/grid-csv";

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

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

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
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
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

function wikiPayload() {
  return {
    status: "ok",
    query: "jensen",
    source_mode: "wikipedia_live",
    items: [
      {
        full_name: "Jensen Huang",
        role: "entrepreneur, engineer",
        company: "Nvidia",
        description: "Taiwanese and American businessman (born 1963)",
        summary:
          'Jen-Hsun "Jensen" Huang is a Taiwanese and American business executive.',
        nationality: "Taiwan / United States",
        profile_url: "https://en.wikipedia.org/wiki/Jensen_Huang",
        wikidata_id: "Q305177",
        source: "wikipedia",
        source_url: "https://en.wikipedia.org/wiki/Jensen_Huang",
        source_date: "2026-09-11T16:51:37Z",
        contact_status: "public_profile_only",
        match_score: 1,
      },
    ],
    connection_status: [
      { source: "local_people_directory", status: "checked" },
      { source: "wikipedia", status: "used" },
    ],
  };
}

describe("PEOP pane — live wikipedia rows", () => {
  it("renders description, nationality and the wikipedia profile link", () => {
    setMockFn({ state: "ok", data: { data: wikiPayload() } });
    const { container } = render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "jensen" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    // "Jensen Huang" renders in the table AND as the top-match card.
    expect(screen.getAllByText("Jensen Huang").length).toBe(2);
    expect(container.textContent).toContain("entrepreneur, engineer");
    expect(container.textContent).toContain(
      "Taiwanese and American businessman (born 1963)",
    );
    expect(container.textContent).toContain("Nvidia");
    expect(container.textContent).toContain("Taiwan / United States");
    expect(container.textContent).toContain("wikipedia_live");
    // The wikipedia profile URL is the rendered source link.
    const links = screen.getAllByLabelText(/Open source for/);
    expect(links[0].getAttribute("href")).toBe(
      "https://en.wikipedia.org/wiki/Jensen_Huang",
    );
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

describe("PEOP pane — grid upgrade (L7)", () => {
  it("sorts people by name from the header", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "apple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    // Original order: Tim Cook, John Ternus.
    expect(container.querySelector("tbody tr")?.textContent).toContain("Tim Cook");
    fireEvent.click(screen.getByRole("columnheader", { name: /^Name/ }));
    // Ascending: John Ternus sorts first.
    expect(container.querySelector("tbody tr")?.textContent).toContain("John Ternus");
  });

  it("copies a contact row as TSV from the row copy button", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "apple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByTitle("Copy Tim Cook contact row"));
    expect(writeText).toHaveBeenCalledTimes(1);
    const payload = writeText.mock.calls[0][0] as string;
    expect(payload.split("\t")[0]).toBe("Tim Cook");
    expect(payload).toContain("Apple");
    expect(payload).toContain("https://www.apple.com/newsroom");
    Reflect.deleteProperty(navigator, "clipboard");
  });
});

describe("PEOP pane — grid CSV export", () => {
  it("exports the raw people results via the CSV button", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<PEOPPane code="PEOP" />);
    fireEvent.change(screen.getByLabelText(/People search query/i), {
      target: { value: "apple" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^peop-apple-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain(
      "Name,Role / title,Firm,Bio,Contact,Source,Source URL,Source date,Match score",
    );
    expect(csv).toContain(
      "Tim Cook,CEO through summer 2026; Executive Chairman effective 2026-09-01,Apple,,public_profile_only,apple_newsroom_public_reference,https://www.apple.com/newsroom,,2",
    );
  });

  it("keeps the CSV button disabled before any query is committed", () => {
    render(<PEOPPane code="PEOP" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
