/**
 * TRAN pane — load-state + transcript-render + interaction tests.
 *
 * The backend TRAN function harvests earnings-call transcripts from SEC 8-K
 * exhibits. When the SEC fetch path is down it answers with an honest
 * `status="provider_unavailable"` + reason; the pane must surface that
 * explicitly and never render fabricated transcript text. These tests pin:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - an ok payload (2 sections, 3 utterances, 2 speakers) renders sections,
 *    speaker+role labels and jump-to-section buttons;
 *  - the persisted speaker filter actually filters utterances;
 *  - a provider_unavailable payload shows the honest reason, no fake text.
 *
 * `useFunction` is mocked via a mutable shared state (GEX.test.tsx pattern)
 * so each test drives the pane into a specific branch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TRANPane } from "./TRAN";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

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
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    sources: ["sec_edgar"],
    elapsed_ms: 812.4,
    data: {
      symbol: "AAPL",
      status: "ok",
      event: {
        symbol: "AAPL",
        quarter: "Q3 FY26",
        form: "8-K",
        event_date: "2026-07-30",
        source: "sec_edgar",
        source_url: "https://www.sec.gov/Archives/edgar/data/320193/x/",
      },
      utterances: [
        {
          section: "prepared_remarks",
          speaker: "Tim Cook",
          role: "CEO",
          utterance: "We delivered our strongest June quarter ever.",
          timestamp_seconds: null,
          position: 1,
        },
        {
          section: "prepared_remarks",
          speaker: "Kevan Parekh",
          role: "CFO",
          utterance: "EPS set a new June quarter record.",
          timestamp_seconds: 421,
          position: 2,
        },
        {
          section: "qa",
          speaker: "Tim Cook",
          role: "CEO",
          utterance: "Taking your question on Services growth.",
          timestamp_seconds: 1505,
          position: 3,
        },
      ],
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      symbol: "AAPL",
      status: "provider_unavailable",
      reason: "SEC fetch failed: provider unreachable — no transcript text available.",
      event: undefined,
      utterances: [],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  window.localStorage.removeItem("showme.tran.speaker");
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("TRAN pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable state with no fake text", () => {
    setMockFn({ state: "ok", data: providerDownPayload() });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(
      screen.getByText(/transcript provider unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/provider unreachable/i),
    ).toBeInTheDocument();
    // No fabricated utterances / speakers are rendered.
    expect(screen.queryByText("Tim Cook")).toBeNull();
    expect(screen.queryByText(/Prepared Remarks/)).toBeNull();
  });
});

describe("TRAN pane — transcript render", () => {
  it("renders both sections, all utterances, and speaker roles", () => {
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    const utts = Array.from(container.querySelectorAll(".tran-utterance"));
    expect(utts.length).toBe(3);
    // Speaker + role labels live inside the utterance articles (the same
    // names also appear in the speaker-filter buttons by design).
    const texts = utts.map((u) => u.textContent ?? "");
    expect(texts.some((t) => t.includes("Tim Cook"))).toBe(true);
    expect(texts.some((t) => t.includes("Kevan Parekh"))).toBe(true);
    expect(texts.some((t) => t.includes("CEO"))).toBe(true);
    expect(texts.some((t) => t.includes("CFO"))).toBe(true);
    expect(screen.getAllByText(/Prepared Remarks/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Q&A").length).toBeGreaterThan(0);
    // Event context is shown in the header subtitle.
    expect(container.textContent).toContain("Q3 FY26");
    // Timestamps render as mm:ss.
    expect(screen.getByText("07:01")).toBeInTheDocument();
  });

  it("renders a jump button per section that scrolls to the section anchor", () => {
    const scrollSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollSpy;
    setMockFn({ state: "ok", data: okPayload() });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    const qaJump = screen.getByRole("button", { name: /jump to q&a/i });
    expect(screen.getByRole("button", { name: /jump to prepared remarks/i })).toBeInTheDocument();
    fireEvent.click(qaJump);
    expect(scrollSpy).toHaveBeenCalled();
    expect(document.getElementById("tran-section-qa")).not.toBeNull();
    expect(document.getElementById("tran-section-prepared-remarks")).not.toBeNull();
  });
});

describe("TRAN pane — in-transcript search (C3)", () => {
  function typeSearch(value: string) {
    fireEvent.change(screen.getByTestId("tran-search-input"), {
      target: { value },
    });
  }

  it("filters the utterance ladder client-side, highlights matches and shows X of N", () => {
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(container.querySelectorAll(".tran-utterance").length).toBe(3);

    typeSearch("services");

    const utts = Array.from(container.querySelectorAll(".tran-utterance"));
    expect(utts.length).toBe(1);
    expect(utts[0].textContent ?? "").toContain("Taking your question on Services growth.");
    // Highlight preserves the original casing while matching case-insensitively.
    const marks = Array.from(utts[0].querySelectorAll("mark"));
    expect(marks.length).toBe(1);
    expect(marks[0].textContent).toBe("Services");
    // "X of N" counts against the current speaker scope (all ⇒ 3).
    expect(screen.getByTestId("tran-search-count").textContent).toMatch(/1 of 3/);
  });

  it("composes with the speaker filter (search only narrows the speaker's rows)", () => {
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    // Speaker filter first — Tim Cook has 2 utterances in the fixture.
    fireEvent.click(screen.getByRole("button", { name: "Tim Cook" }));
    expect(container.querySelectorAll(".tran-utterance").length).toBe(2);

    typeSearch("june");
    const utts = Array.from(container.querySelectorAll(".tran-utterance"));
    expect(utts.length).toBe(1);
    expect(utts[0].textContent ?? "").toContain("strongest June quarter");
    // Scope is the speaker's 2 utterances, NOT the full transcript.
    expect(screen.getByTestId("tran-search-count").textContent).toMatch(/1 of 2/);
    expect(screen.getByTestId("tran-search-count").getAttribute("title")).toMatch(
      /Tim Cook's 2 utterances/,
    );
  });

  it("shows an honest no-match state and clears back to the full ladder", () => {
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    typeSearch("zzz-nothing");
    expect(screen.getByText(/No utterances match/i)).toBeInTheDocument();
    expect(screen.getByText(/never fabricates rows/i)).toBeInTheDocument();
    // No utterance cards are rendered while zero rows match.
    expect(container.querySelectorAll(".tran-utterance").length).toBe(0);

    fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
    expect(container.querySelectorAll(".tran-utterance").length).toBe(3);
    expect(screen.queryByTestId("tran-search-count")).toBeNull();
  });
});

describe("TRAN pane — source link (C3)", () => {
  it("renders the event source_url as a safe absolute link in the header", () => {
    setMockFn({ state: "ok", data: okPayload() });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    const link = screen.getByTestId("tran-source-link");
    expect(link).toHaveAttribute(
      "href",
      "https://www.sec.gov/Archives/edgar/data/320193/x/",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("guards the link: non-absolute source_urls render NO anchor", () => {
    for (const bad of ["javascript:alert(1)", "/Archives/edgar/data/320193/"]) {
      cleanup();
      const payload = okPayload();
      payload.data.event = { ...payload.data.event, source_url: bad };
      setMockFn({ state: "ok", data: payload });
      const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
      expect(screen.queryByTestId("tran-source-link")).toBeNull();
      // The unsafe token never leaks into any href attribute.
      expect(container.querySelector('a[href^="javascript:"]')).toBeNull();
    }
  });
});

describe("TRAN pane — speaker filter", () => {
  it("filters utterances to the selected speaker and offers a reset", () => {
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Tim Cook" }));
    const utts = Array.from(container.querySelectorAll(".tran-utterance"));
    expect(utts.length).toBe(2);
    expect(
      utts.some((u) => (u.textContent ?? "").includes("Kevan Parekh")),
    ).toBe(false);
  });

  it("restores the persisted speaker from localStorage", () => {
    window.localStorage.setItem("showme.tran.speaker", "Kevan Parekh");
    setMockFn({ state: "ok", data: okPayload() });
    const { container } = render(<TRANPane code="TRAN" symbol="AAPL" />);
    const utts = Array.from(container.querySelectorAll(".tran-utterance"));
    expect(utts.length).toBe(1);
    expect(utts[0].textContent ?? "").toContain("Kevan Parekh");
    expect(
      utts.some((u) => (u.textContent ?? "").includes("Tim Cook")),
    ).toBe(false);
  });

  it("shows an honest empty state when the selected speaker has no utterances", () => {
    window.localStorage.setItem("showme.tran.speaker", "Ghost Speaker");
    setMockFn({ state: "ok", data: okPayload() });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(screen.getByText(/no utterances for this speaker/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show all speakers/i }),
    ).toBeInTheDocument();
  });
});
