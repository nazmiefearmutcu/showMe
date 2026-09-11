/**
 * BMC pane — curriculum + interaction tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - the payload renders the module chips, lesson list with progress pills,
 *    and the reader (objective / example / self-check);
 *  - clicking a module chip narrows the lesson list (client-side, honest —
 *    the curriculum is a local reference, not live data);
 *  - clicking a lesson opens it in the reader;
 *  - the module filter persists under `showme.bmc.module`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { BMCPane } from "./BMC";

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

/* ── fixtures (shape mirrors a live /api/fn/BMC probe) ─────────────── */

function okPayload() {
  return {
    status: "ready",
    rows: [
      {
        module: "Equities",
        lesson_no: "1",
        lesson: "Equity index construction",
        objective: "Compare price-weighted and market-cap-weighted indices.",
        example: "S&P 500 vs Dow Jones weighting",
        quiz: "Why can one large-cap stock move a cap-weighted index?",
        progress: "not_started",
      },
      {
        module: "Equities",
        lesson_no: "2",
        lesson: "Valuation multiples",
        objective: "Read P/E, EV/EBITDA, and sales multiples without mixing denominators.",
        example: "High-growth software vs mature utilities",
        quiz: "When is EV/Sales more useful than P/E?",
        progress: "not_started",
      },
      {
        module: "Fixed Income",
        lesson_no: "1",
        lesson: "Yield and duration",
        objective: "Estimate price sensitivity from yield changes.",
        example: "10Y Treasury duration shock",
        quiz: "What happens to price when yield rises?",
        progress: "not_started",
      },
    ],
    cards: [
      { label: "Modules", value: 2 },
      { label: "Lessons", value: 3 },
    ],
    methodology: "BMC is a local market-concepts curriculum.",
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("BMC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<BMCPane code="BMC" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<BMCPane code="BMC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("BMC pane — curriculum body", () => {
  it("renders module chips, lesson list and the reader when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<BMCPane code="BMC" />);
    // Module chips derived from the payload.
    expect(screen.getByRole("button", { name: "Fixed Income" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Equities" })).toBeInTheDocument();
    // Lesson list with progress pills (titles also appear in the reader).
    expect(screen.getAllByText("Equity index construction").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTitle("Open lesson: Yield and duration")).toBeInTheDocument();
    // Backend rows ship not_started — the pane never invents a completed row.
    expect(container.textContent).toContain("not_started");
    const lessonList = screen.getByLabelText("BMC lessons");
    expect(within(lessonList).queryByText(/^completed$/i)).toBeNull();
    // Reader shows the first lesson's fields.
    expect(container.textContent).toContain("Compare price-weighted and market-cap-weighted indices.");
    expect(container.textContent).toContain("Why can one large-cap stock move a cap-weighted index?");
    // Honest synth note in the summary cards.
    expect(container.textContent).toContain("NOT LIVE");
  });

  it("narrows the lesson list when a module chip is clicked", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<BMCPane code="BMC" />);
    fireEvent.click(screen.getByRole("button", { name: "Fixed Income" }));
    expect(screen.getByTitle("Open lesson: Yield and duration")).toBeInTheDocument();
    expect(screen.queryByTitle("Open lesson: Equity index construction")).toBeNull();
    expect(container.textContent).toContain("FIXED INCOME");
    expect(localStorage.getItem("showme.bmc.module")).toBe("fixed income");
  });

  it("opens a clicked lesson in the reader", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<BMCPane code="BMC" />);
    fireEvent.click(screen.getByTitle("Open lesson: Valuation multiples"));
    expect(container.textContent).toContain("Read P/E, EV/EBITDA, and sales multiples without mixing denominators.");
    expect(container.textContent).toContain("When is EV/Sales more useful than P/E?");
  });

  it("tracks lesson completion locally and counts it in the Completed KPI", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<BMCPane code="BMC" />);
    const kpi = screen.getByLabelText("BMC summary");
    // Backend rows are all not_started, so the KPI starts at a real 0 (it used
    // to be hardwired to 0 forever because the backend never emits completed).
    expect(within(kpi).getByText("Completed")).toBeInTheDocument();
    expect(within(kpi).getByText("0")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /mark lesson completed/i }));
    expect(localStorage.getItem("showme.bmc.completed")).toContain("Equities#1");
    expect(within(kpi).getByText("1")).toBeInTheDocument();
    // The pill flips for that lesson only.
    const lessonList = screen.getByLabelText("BMC lessons");
    expect(within(lessonList).getByText("completed")).toBeInTheDocument();
    // Toggling again clears it.
    fireEvent.click(screen.getByRole("button", { name: /mark lesson not started/i }));
    expect(within(kpi).getByText("0")).toBeInTheDocument();
  });

  it("restores persisted completion on a fresh mount", () => {
    localStorage.setItem("showme.bmc.completed", JSON.stringify({ "Fixed Income#1": true }));
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<BMCPane code="BMC" />);
    expect(within(screen.getByLabelText("BMC summary")).getByText("1")).toBeInTheDocument();
    const lessonList = screen.getByLabelText("BMC lessons");
    expect(within(lessonList).getByText("completed")).toBeInTheDocument();
  });
});
