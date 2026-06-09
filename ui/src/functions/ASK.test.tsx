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
 *     "kural-tabanlı" label otherwise (never "claude-sonnet-4.6")
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
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ASKPane } from "./ASK";
import * as askLib from "@/lib/ask";
import * as router from "@/lib/router";
import type { AskResponse } from "@/lib/ask";

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
  fireEvent.click(screen.getByRole("button", { name: /sorguyu çalıştır/i }));
}

beforeEach(() => {
  vi.spyOn(router, "navigate").mockImplementation(() => undefined);
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
      screen.getByLabelText(/sorgunuzu yazın/i),
    ).toBe(ta);
  });

  it("disables the submit button when the draft is empty", () => {
    vi.spyOn(askLib, "ask").mockResolvedValue(makeResponse());
    render(<ASKPane code="ASK" />);
    expect(
      screen.getByRole("button", { name: /önce bir sorgu yazın/i }),
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
        screen.getByRole("button", { name: /sorgu çalışıyor/i }),
      ).toHaveAttribute("aria-busy", "true");
    });
    resolve(makeResponse());
    // The draft was cleared on submit, so after resolution the submit button's
    // accessible name reflects the empty-draft disabled reason.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /önce bir sorgu yazın/i }),
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
      screen.getAllByText(/kural-tabanlı plan/i).length,
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
    expect(badge).toHaveTextContent(/plan: kural-tabanlı/i);
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
    expect(disc.textContent ?? "").toMatch(/yapay zekâ/i);
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
      name: /kaynak \[1\] — scan panelini aç/i,
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
      name: /^scan panelini aç/i,
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
        screen.getByRole("button", { name: /sorguyu çalıştır|önce bir sorgu/i }),
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
      screen.getByRole("button", { name: /sorguyu çalıştır|önce bir sorgu/i }),
    ).toHaveAttribute("aria-busy", "false");
    resolve(makeResponse());
  });
});
