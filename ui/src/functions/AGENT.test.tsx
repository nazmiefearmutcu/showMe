/**
 * AGENT — Symbol Agent pane. Render-level tests for the honesty-first upgrade.
 *
 * The ranking engine is a DETERMINISTIC heuristic. The default mode scores
 * candidates with TRANSPARENT SYNTHETIC `agent_fast_probe` payloads; an opt-in
 * live mode runs real functions. These tests pin the UI behaviour that makes
 * that honest and usable, with the agent client + router mocked so the suite is
 * deterministic and never touches the sidecar.
 *
 * Covers:
 *   - renders with default candidates + a styled, labelled Run button
 *   - Run button: disabled when no candidates; aria-busy while loading
 *   - static methodology disclosure renders before any run (agent-methodology)
 *   - method/methodology surfaced after a (mocked) run
 *   - the "confidence" column is relabelled to honest "signal density" wording
 *   - toggling live mode threads execute_functions:true into runBestSymbolAgent
 *   - a ranked symbol is a button that navigates to DES
 *   - error renders in a role="status" live region
 *   - both DataGrids receive ariaLabel; Skeleton shows while loading
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
import { AGENTPane } from "./AGENT";
import * as agent from "@/lib/agent";
import * as router from "@/lib/router";
import type {
  AgentCandidateResult,
  AgentFunctionEvidence,
  BestSymbolAgentResult,
} from "@/lib/agent";

function makeEvidence(
  overrides: Partial<AgentFunctionEvidence> = {},
): AgentFunctionEvidence {
  return {
    code: "RSI",
    category: "momentum",
    status: "pass",
    reason: "ok",
    score: 1.23,
    confidence: 0.71,
    signal_count: 3,
    fallback: false,
    elapsed_ms: 12,
    signals: [{ path: "rsi.value", value: 71, score: 0.5 }],
    ...overrides,
  };
}

function makeCandidate(
  overrides: Partial<AgentCandidateResult> = {},
): AgentCandidateResult {
  return {
    symbol: "BTCUSDT",
    asset_class: "CRYPTO",
    score: 1.23,
    pass: 4,
    fail: 1,
    fallback: 0,
    signal_functions: 3,
    function_count: 5,
    top_evidence: [makeEvidence()],
    ...overrides,
  };
}

function makeResult(
  overrides: Partial<BestSymbolAgentResult> = {},
): BestSymbolAgentResult {
  const best = overrides.best ?? makeCandidate();
  return {
    best,
    ranked: overrides.ranked ?? [best],
    function_count: 5,
    catalog_count: 42,
    excluded_functions: [],
    candidate_count: 8,
    started_at: "2026-06-08T00:00:00Z",
    completed_at: "2026-06-08T00:00:01Z",
    elapsed_ms: 1234,
    method: "all_function_symbol_agent_v3_fast_probe",
    methodology:
      "Ranks candidate symbols by aggregating scored evidence rows. Nonblocking mode uses transparent agent_fast_probe payloads.",
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(router, "navigate").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AGENT pane — render + Run button", () => {
  it("renders with default candidates and a styled, labelled Run button", () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    const { container } = render(<AGENTPane code="AGENT" />);
    const runBtn = screen.getByRole("button", { name: /sıralamayı çalıştır/i });
    expect(runBtn).toBeInTheDocument();
    // D1: the btn classes are on the BUTTON itself now (was on the wrapper).
    expect(runBtn).toHaveClass("btn", "btn--accent");
    // Default candidates are present in the textarea.
    const ta = container.querySelector(
      "#agent-candidates",
    ) as HTMLTextAreaElement;
    expect(ta).not.toBeNull();
    expect(ta.value).toMatch(/BTCUSDT/);
  });

  it("disables the Run button when there are no candidates", () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    const { container } = render(<AGENTPane code="AGENT" />);
    const ta = container.querySelector(
      "#agent-candidates",
    ) as HTMLTextAreaElement;
    fireEvent.change(ta, { target: { value: "" } });
    expect(
      screen.getByRole("button", { name: /sıralamayı çalıştır/i }),
    ).toBeDisabled();
  });

  it("sets aria-busy on the Run button while loading", async () => {
    let resolve!: (r: BestSymbolAgentResult) => void;
    vi.spyOn(agent, "runBestSymbolAgent").mockReturnValue(
      new Promise<BestSymbolAgentResult>((r) => {
        resolve = r;
      }),
    );
    render(<AGENTPane code="AGENT" />);
    const runBtn = screen.getByRole("button", { name: /sıralamayı çalıştır/i });
    fireEvent.click(runBtn);
    await waitFor(() => expect(runBtn).toHaveAttribute("aria-busy", "true"));
    // Loading skeleton is shown in the results area.
    expect(screen.getByTestId("agent-loading")).toBeInTheDocument();
    resolve(makeResult());
    await waitFor(() => expect(runBtn).toHaveAttribute("aria-busy", "false"));
  });
});

describe("AGENT pane — methodology / method disclosure (H1)", () => {
  it("shows the static deterministic-heuristic disclosure before any run", () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    const disclosure = screen.getByTestId("agent-methodology");
    expect(disclosure).toBeInTheDocument();
    expect(disclosure.textContent ?? "").toMatch(/determ/i);
    // "SENTETİK" uses the Turkish dotted-İ which does not case-fold to ASCII
    // 'i'; match the case-stable "SENTET" stem instead.
    expect(disclosure.textContent ?? "").toMatch(/sentet/i);
    // Honest about NOT being an AI/LLM.
    expect(disclosure.textContent ?? "").toMatch(/yapay zekâ|llm/i);
  });

  it("surfaces the backend method + methodology after a run", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await screen.findByText(/aggregating scored evidence rows/i);
    const disclosure = screen.getByTestId("agent-methodology");
    expect(disclosure.textContent ?? "").toMatch(
      /all_function_symbol_agent_v3_fast_probe/,
    );
  });
});

describe("AGENT pane — honest confidence relabel (H2)", () => {
  it("labels the evidence metric as signal density, not confidence", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await screen.findByText(/sinyal yoğ\./i);
    // The honest label is present and the misleading "conf" header is gone.
    expect(screen.getByText(/sinyal yoğ\./i)).toBeInTheDocument();
    expect(screen.queryByText(/^conf$/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/uncertainty/i)).not.toBeInTheDocument();
  });
});

describe("AGENT pane — live/probe mode toggle (H3)", () => {
  it("passes execute_functions:false by default", async () => {
    const spy = vi
      .spyOn(agent, "runBestSymbolAgent")
      .mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenLastCalledWith(
      expect.objectContaining({ execute_functions: false }),
      expect.anything(),
    );
  });

  it("threads execute_functions:true once the live toggle is enabled", async () => {
    const spy = vi
      .spyOn(agent, "runBestSymbolAgent")
      .mockResolvedValue(
        makeResult({ method: "all_function_symbol_agent_v1_live" }),
      );
    render(<AGENTPane code="AGENT" />);
    const toggle = screen.getByRole("checkbox");
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy).toHaveBeenLastCalledWith(
      expect.objectContaining({ execute_functions: true }),
      expect.anything(),
    );
    // The displayed mode reflects the live method.
    await screen.findByText(/canlı yürütme/i);
  });
});

describe("AGENT pane — actionable rows (U1)", () => {
  it("navigates to DES when a ranked symbol button is clicked", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(
      makeResult({
        best: makeCandidate({ symbol: "SOLUSDT" }),
        ranked: [makeCandidate({ symbol: "SOLUSDT" })],
      }),
    );
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    const symBtn = await screen.findByRole("button", {
      name: /solusdt des'te aç/i,
    });
    fireEvent.click(symBtn);
    expect(router.navigate).toHaveBeenCalledWith("/symbol/SOLUSDT/DES");
  });

  it("launches DES on Enter for keyboard parity", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(
      makeResult({
        best: makeCandidate({ symbol: "ETHUSDT" }),
        ranked: [makeCandidate({ symbol: "ETHUSDT" })],
      }),
    );
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    const symBtn = await screen.findByRole("button", {
      name: /ethusdt des'te aç/i,
    });
    fireEvent.keyDown(symBtn, { key: "Enter" });
    expect(router.navigate).toHaveBeenCalledWith("/symbol/ETHUSDT/DES");
  });
});

describe("AGENT pane — result summary (U2)", () => {
  it("announces the ranked count + best symbol in a status region", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(
      makeResult({
        best: makeCandidate({ symbol: "BTCUSDT" }),
        ranked: [
          makeCandidate({ symbol: "BTCUSDT" }),
          makeCandidate({ symbol: "ETHUSDT" }),
        ],
      }),
    );
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    const summary = await screen.findByText(/2 aday sıralandı/i);
    expect(summary).toHaveTextContent(/en iyi: BTCUSDT/);
    expect(summary).toHaveAttribute("role", "status");
  });
});

describe("AGENT pane — DataGrid a11y (DI2)", () => {
  it("gives both grids an aria-label", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await screen.findByRole("table", { name: /sıralanan adaylar/i });
    expect(
      screen.getByRole("table", { name: /sıralanan adaylar/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("table", {
        name: /en iyi aday için fonksiyon kanıtları/i,
      }),
    ).toBeInTheDocument();
  });

  it("renders score and signal-density as meters (not bare text)", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(makeResult());
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await screen.findByRole("table", { name: /sıralanan adaylar/i });
    // At least one role=meter exists (score meter + density meter).
    expect(screen.getAllByRole("meter").length).toBeGreaterThanOrEqual(1);
  });

  it("clamps out-of-band score meter aria-valuenow to the ±3 band (P1)", async () => {
    // A backend score outside ±SCORE_BAND (e.g. 5.5 / -5.5) must NOT leak into
    // aria-valuenow — the ARIA meter spec requires valuenow ∈ [valuemin,valuemax].
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(
      makeResult({
        best: makeCandidate({ symbol: "BTCUSDT", score: 5.5 }),
        ranked: [
          makeCandidate({ symbol: "BTCUSDT", score: 5.5 }),
          makeCandidate({ symbol: "ETHUSDT", score: -5.5 }),
        ],
      }),
    );
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    await screen.findByRole("table", { name: /sıralanan adaylar/i });

    // Score meters are labelled with a "score" prefix; density meters are not.
    const scoreMeters = screen
      .getAllByRole("meter")
      .filter((m) => /^score /i.test(m.getAttribute("aria-label") ?? ""));
    expect(scoreMeters.length).toBeGreaterThanOrEqual(2);

    const nows = scoreMeters.map((m) => m.getAttribute("aria-valuenow"));
    // The +5.5 row clamps to "3", the -5.5 row clamps to "-3" — never "5.5".
    expect(nows).toContain("3");
    expect(nows).toContain("-3");
    expect(nows).not.toContain("5.5");
    expect(nows).not.toContain("-5.5");

    // Every score meter's valuenow stays within [valuemin, valuemax].
    for (const m of scoreMeters) {
      const now = Number(m.getAttribute("aria-valuenow"));
      const min = Number(m.getAttribute("aria-valuemin"));
      const max = Number(m.getAttribute("aria-valuemax"));
      expect(now).toBeGreaterThanOrEqual(min);
      expect(now).toBeLessThanOrEqual(max);
    }
  });
});

describe("AGENT pane — error region (D2)", () => {
  it("renders the error inside a role=status live region", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockRejectedValue(new Error("boom"));
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    const err = await screen.findByTestId("agent-error");
    expect(err).toHaveAttribute("role", "status");
    expect(err).toHaveAttribute("aria-live", "polite");
    expect(err).toHaveTextContent(/boom/);
  });
});

describe("AGENT pane — data honesty", () => {
  it("renders only real backend ranked rows (no stub fallback)", async () => {
    vi.spyOn(agent, "runBestSymbolAgent").mockResolvedValue(
      makeResult({
        best: makeCandidate({ symbol: "NVDA" }),
        ranked: [makeCandidate({ symbol: "NVDA" })],
      }),
    );
    render(<AGENTPane code="AGENT" />);
    fireEvent.click(screen.getByRole("button", { name: /sıralamayı çalıştır/i }));
    const grid = await screen.findByRole("table", { name: /sıralanan adaylar/i });
    // Exactly one symbol launch affordance for the one mocked row.
    expect(within(grid).getAllByRole("button", { name: /des'te aç/i })).toHaveLength(
      1,
    );
  });
});
