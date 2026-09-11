/**
 * ASK — natural-language query pane. Render-level tests for the HONESTY-first
 * upgrade.
 *
 * HONESTY: the ANSWER (narrative + highlights) is composed DETERMINISTICALLY
 * from real function outputs — it is NOT AI-written. Only the PLAN step may
 * call an LLM (a small Haiku/4o-mini model, gated on keys + a daily cap). The
 * UI surfaces the REAL model/cost/plan-method the backend returns instead of a
 * hardcoded "claude-sonnet-4.6" + a fabricated cost.
 *
 * The ask() client + router navigate are mocked so the suite is deterministic
 * and never touches the sidecar.
 *
 * Covers:
 *   - renders the empty state
 *   - submit disabled when empty; aria-busy while running; bound textarea label
 *   - model pill shows the REAL model_used when was_llm_called, the honest
 *     "rule-based" label otherwise (never "claude-sonnet-4.6")
 *   - cost reflects response.cost_usd (deterministic → $0.00, no fake minimum)
 *   - plan-method badge renders AI vs rule-based correctly
 *   - answer turn wrapped in role=status; error turn announced
 *   - a citation/evidence is an actionable button that navigates
 *   - suggestion chips disabled while running
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ASKPane } from "./ASK";
import * as askLib from "@/lib/ask";
import * as router from "@/lib/router";
import type { AskResponse } from "@/lib/ask";

// The pane reads the real LLM ledger (GET /api/llm/cost) on mount; keep the
// suite deterministic by defaulting that fetch to "ledger unavailable".
vi.mock("@/lib/sidecar", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/sidecar")>();
  return {
    ...actual,
    sidecarFetch: vi.fn(() => Promise.reject(new Error("no sidecar in tests"))),
  };
});
import { sidecarFetch } from "@/lib/sidecar";
const sidecarMock = sidecarFetch as unknown as ReturnType<typeof vi.fn>;

function makeResponse(overrides: Partial<AskResponse> = {}): AskResponse {
  return {
    query: "test query",
    plan: {
      intent: "scan",
      action: "run scanner",
      rationale: "user asked for opportunities",
      args: {},
      agents: ["search", "summarizer", "viz"],
    },
    search: {
      kind: "scan",
      code: "SCAN",
      evidence: [
        {
          branch: "root",
          code: "SCAN",
          sources: ["binance"],
          status: "ok",
          rows: 5,
          top: ["BTCUSDT", "ETHUSDT"],
          elapsed_ms: 12,
        },
      ],
    },
    narrative: "Deterministic narrative built from real function outputs.",
    highlights: [{ label: "candidates", value: 5, tone: "positive" }],
    viz: { kind: "table", title: "Scan", rows_n: 5 },
    phases: [{ name: "plan", elapsed_ms: 3, output: {} }],
    elapsed_ms: 42,
    warnings: [],
    plan_method: "deterministic",
    model_used: null,
    provider: null,
    cost_usd: 0,
    was_llm_called: false,
    ...overrides,
  };
}

function llmResponse(overrides: Partial<AskResponse> = {}): AskResponse {
  return makeResponse({
    plan_method: "llm",
    model_used: "claude-haiku-4-5",
    provider: "anthropic",
    cost_usd: 0.0123,
    was_llm_called: true,
    ...overrides,
  });
}

async function submitQuery(text = "find crypto opportunities") {
  const ta = document.getElementById(
    "ask-composer-input",
  ) as HTMLTextAreaElement;
  fireEvent.change(ta, { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /run query/i }));
}

beforeEach(() => {
  vi.spyOn(router, "navigate").mockImplementation(() => undefined);
  // The pane persists its thread per session (sessionStorage); isolate tests.
  sessionStorage.clear();
  // Pending forever by default: no state update fires outside act() for the
  // tests that don't care about the ledger. Ledger tests override per-call.
  sidecarMock.mockImplementation(() => new Promise(() => {}));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ASK pane — empty state + composer a11y", () => {
  it("renders the empty state", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    expect(screen.getByText(/what can i help you with/i)).toBeInTheDocument();
  });

  it("binds a label to the query textarea", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    const ta = document.getElementById("ask-composer-input");
    expect(ta).not.toBeNull();
    expect(ta?.tagName).toBe("TEXTAREA");
    // The bound label is queryable as a labelled element.
    expect(
      screen.getByLabelText(/type your query/i),
    ).toBe(ta);
  });

  it("disables the submit button when the draft is empty", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    expect(
      screen.getByRole("button", { name: /type a query first/i }),
    ).toBeDisabled();
  });

  it("sets aria-busy on submit while running", async () => {
    let resolve!: (r: AskResponse) => void;
    vi.spyOn(askLib, "ask").mockReturnValue(
      new Promise<AskResponse>((r) => {
        resolve = r;
      }),
    );
    render(<ASKPane code="ASK" />);
    await submitQuery();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /query running/i }),
      ).toHaveAttribute("aria-busy", "true");
    });
    resolve(makeResponse());
    // The draft was cleared on submit, so after resolution the submit button's
    // accessible name reflects the empty-draft disabled reason.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /type a query first/i }),
      ).toHaveAttribute("aria-busy", "false"),
    );
  });
});

describe("ASK pane — honest model + cost (F1/F2)", () => {
  it("shows the honest rule-based label (NOT claude-sonnet-4.6) on the deterministic path", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    // The fabricated Sonnet label must be gone entirely.
    expect(screen.queryByText(/claude-sonnet-4\.6/i)).not.toBeInTheDocument();
    // The honest rule-based label is present (header + status strip).
    expect(
      screen.getAllByText(/rule-based plan/i).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("shows the REAL model_used in the header when the LLM actually planned", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(llmResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    await waitFor(() =>
      expect(
        screen.getAllByText(/claude-haiku-4-5/i).length,
      ).toBeGreaterThanOrEqual(1),
    );
    expect(screen.queryByText(/claude-sonnet-4\.6/i)).not.toBeInTheDocument();
  });

  it("renders the REAL cost ($0.00 deterministic, no fake minimum)", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    await screen.findByText(/deterministic narrative/i);
    // Footer cost reflects the real $0 — never the old fake "$0.005+" minimum.
    expect(screen.getByText(/cost · \$0\.0000/i)).toBeInTheDocument();
    expect(screen.queryByText(/\$0\.005/)).not.toBeInTheDocument();
  });

  it("accumulates the real cost_usd for the session total", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(llmResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    await screen.findByText(/deterministic narrative/i);
    expect(screen.getByText(/cost · \$0\.0123/i)).toBeInTheDocument();
  });
});

describe("ASK pane — plan-method badge (F3)", () => {
  it("renders the rule-based plan badge on the deterministic path", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    const badge = await screen.findByTestId("ask-plan-method");
    expect(badge).toHaveTextContent(/plan: rule-based/i);
  });

  it("renders the AI plan badge with the real model when the LLM planned", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(llmResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    const badge = await screen.findByTestId("ask-plan-method");
    expect(badge).toHaveTextContent(/plan: ai \(claude-haiku-4-5\)/i);
  });

  it("shows the deterministic-answer disclosure", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    const disc = screen.getByTestId("ask-disclosure");
    expect(disc.textContent ?? "").toMatch(/determ/i);
    expect(disc.textContent ?? "").toMatch(/not AI-written/i);
  });
});

describe("ASK pane — announced turns (A3)", () => {
  it("wraps the agent answer in a role=status live region", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    const narrative = await screen.findByText(/deterministic narrative/i);
    const region = narrative.closest('[role="status"]');
    expect(region).not.toBeNull();
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("announces an error turn", async () => {
    vi.spyOn(askLib, "ask").mockRejectedValue(new Error("ask boom"));
    render(<ASKPane code="ASK" />);
    await submitQuery();
    const errText = await screen.findByText(/ask boom/i);
    const region = errText.closest('[role="status"]');
    expect(region).not.toBeNull();
    expect(region).toHaveAttribute("aria-live", "polite");
  });
});

describe("ASK pane — actionable citations (A4)", () => {
  it("opens the cited function when a highlight citation is clicked", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    await screen.findByText(/deterministic narrative/i);
    const cite = await screen.findByRole("button", {
      name: /source \[1\] — open scan pane/i,
    });
    fireEvent.click(cite);
    expect(router.navigate).toHaveBeenCalledWith("/fn/SCAN");
  });

  it("evidence code is a focusable button that navigates", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery();
    // Expand the reasoning trace to reveal the evidence table.
    fireEvent.click(await screen.findByRole("button", { name: /show reasoning trace/i }));
    const codeBtn = await screen.findByRole("button", {
      name: /^open scan pane/i,
    });
    fireEvent.click(codeBtn);
    expect(router.navigate).toHaveBeenCalledWith("/fn/SCAN");
  });
});

describe("ASK pane — usability (U1)", () => {
  it("disables the suggestion chips while a query is running", async () => {
    let resolve!: (r: AskResponse) => void;
    vi.spyOn(askLib, "ask").mockReturnValue(
      new Promise<AskResponse>((r) => {
        resolve = r;
      }),
    );
    render(<ASKPane code="ASK" />);
    // Suggestion chips are enabled before a run.
    const chip = screen.getByRole("button", { name: /what's driving nvda today/i });
    expect(chip).not.toBeDisabled();
    await submitQuery();
    await waitFor(() => expect(chip).toBeDisabled());
    resolve(makeResponse());
    await waitFor(() => expect(chip).not.toBeDisabled());
  });

  it("exposes a Stop affordance while running", async () => {
    let resolve!: (r: AskResponse) => void;
    vi.spyOn(askLib, "ask").mockReturnValue(
      new Promise<AskResponse>((r) => {
        resolve = r;
      }),
    );
    render(<ASKPane code="ASK" />);
    await submitQuery();
    const stop = await screen.findByTestId("ask-stop");
    expect(stop).toBeInTheDocument();
    fireEvent.click(stop);
    // Cancelling restores the ready state (submit no longer aria-busy).
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /run query|type a query/i }),
      ).toHaveAttribute("aria-busy", "false"),
    );
    resolve(makeResponse());
  });

  it("cancels the in-flight query when Escape is pressed in the textarea (U2)", async () => {
    let resolve!: (r: AskResponse) => void;
    vi.spyOn(askLib, "ask").mockReturnValue(
      new Promise<AskResponse>((r) => {
        resolve = r;
      }),
    );
    render(<ASKPane code="ASK" />);
    await submitQuery();
    // The Stop affordance proves a query is in flight.
    const ta = document.getElementById(
      "ask-composer-input",
    ) as HTMLTextAreaElement;
    await screen.findByTestId("ask-stop");
    // Esc in the textarea cancels the abortable fetch and clears running.
    fireEvent.keyDown(ta, { key: "Escape" });
    // Stop affordance disappears and the submit button is no longer aria-busy.
    await waitFor(() =>
      expect(screen.queryByTestId("ask-stop")).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /run query|type a query/i }),
    ).toHaveAttribute("aria-busy", "false");
    resolve(makeResponse());
  });
});

describe("ASK pane - session thread + multi-turn history (G4 OPP wave)", () => {
  it("renders the compact thread strip and reuses a previous query", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    expect(screen.queryByTestId("ask-thread-strip")).toBeNull();
    await submitQuery("first question");
    await screen.findByText(/deterministic narrative/i);
    const strip = await screen.findByTestId("ask-thread-strip");
    const chip = within(strip).getByRole("button", { name: /first question/i });
    fireEvent.click(chip);
    const ta = document.getElementById(
      "ask-composer-input",
    ) as HTMLTextAreaElement;
    expect(ta.value).toBe("first question");
  });

  it("restores the thread from sessionStorage when the pane remounts in the same session", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    const first = render(<ASKPane code="ASK" />);
    await submitQuery("persist me");
    await screen.findByText(/deterministic narrative/i);
    first.unmount();
    render(<ASKPane code="ASK" />);
    expect(screen.getByText("persist me")).toBeInTheDocument();
    expect(screen.getByText(/deterministic narrative/i)).toBeInTheDocument();
  });

  it("sends the trailing Q/A turns as history on the next ask", async () => {
    const spy = vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery("first question");
    await screen.findByText(/deterministic narrative/i);
    await submitQuery("second question");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    const secondCall = spy.mock.calls[1] as unknown as [
      string,
      AbortSignal | undefined,
      Array<{ role: string; content: string }> | undefined,
    ];
    expect(secondCall[0]).toBe("second question");
    expect(secondCall[2]).toEqual([
      { role: "user", content: "first question" },
      {
        role: "agent",
        content: "Deterministic narrative built from real function outputs.",
      },
    ]);
  });

  it("clears the session thread (and the persisted copy) on Clear", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    await submitQuery("clear me");
    await screen.findByText(/deterministic narrative/i);
    fireEvent.click(
      screen.getByRole("button", { name: /clear session thread/i }),
    );
    expect(screen.queryByTestId("ask-thread-strip")).toBeNull();
    expect(screen.getByText(/what can i help you with/i)).toBeInTheDocument();
    expect(sessionStorage.getItem("showme.ask.thread.v1")).toBe("[]");
  });
});

describe("ASK pane - real LLM ledger (audit A8 M)", () => {
  it("reads the real /api/llm/cost ledger for the cost pill", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    sidecarMock.mockResolvedValueOnce({
      today_usd: 0.42,
      cap_usd: 5,
      remaining_usd: 4.58,
      exhausted: false,
    });
    render(<ASKPane code="ASK" />);
    const pill = await screen.findByLabelText(/LLM spend today/i);
    expect(pill.textContent).toMatch(/\$0\.4200 \/ \$5\.00/);
    expect(sidecarMock).toHaveBeenCalledWith("/api/llm/cost");
    // The hardcoded $1.00 cap must be gone from the pane.
    expect(screen.queryByText(/\$1\.00/)).toBeNull();
  });

  it("falls back to a labelled session cost when the ledger is unavailable", async () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    sidecarMock.mockRejectedValueOnce(new Error("ledger down"));
    render(<ASKPane code="ASK" />);
    const pill = await screen.findByLabelText(/ledger unavailable/i);
    expect(pill.textContent).toMatch(/session \$0\.0000/);
    expect(screen.queryByText(/\$1\.00/)).toBeNull();
  });
});
