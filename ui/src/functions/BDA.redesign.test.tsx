/**
 * BDA — redesign behaviour pins.
 *
 * Runs the pane against the REAL assistant + strategy stores with a mocked
 * sidecar:
 *  - Suggest round-trip: text → POST /api/assistant/strategy-from-text
 *    ({text, save:false}) → spec rendered readably (name/timeframe/
 *    indicators/entry+exit rules/position).
 *  - Suggest + save: saved_id → saved pill + success toast + editor cleared
 *    + strategy list refreshed.
 *  - Explain: strategy selection → POST /api/assistant/explain-strategy
 *    ({strategy_id}) → explanation rendered.
 *  - Disabled states: empty request blocks suggest; unselected strategy
 *    blocks explain.
 *  - Failure: rejection surfaces the inline error AND an error toast.
 *  - Pane chrome + example chips.
 */
import { render, screen, fireEvent, waitFor, act, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BDAPane } from "./BDA";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useToastStore } from "@/lib/toast";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

const STRATEGY_META = {
  id: "kaos-multibot",
  name: "KAOS Multibot",
  description: "",
  timeframe: "15m",
  created_at: "",
  updated_at: "",
};

const SPEC_FIXTURE = {
  id: "c00f97d850234b8092e5dc842543b5d5",
  name: "NL: rsi",
  description: "buy RSI below 30, sell above 70, BTC/USDT 1h",
  version: 1,
  asset_filter: { exchanges: null, symbols: ["BTC/USDT"], asset_classes: null },
  timeframe: "1h",
  indicators: [{ alias: "rsi14", id: "rsi", params: { period: 14 } }],
  entry_rules: [
    { kind: "crosses_below", left: "rsi14", right: "literal:30.0", tolerance: null },
  ],
  entry_logic: "all",
  exit_rules: [
    { kind: "crosses_above", left: "rsi14", right: "literal:70.0", tolerance: null },
  ],
  exit_logic: "any",
  position: {
    side: "long",
    sizing_kind: "fixed_quote",
    sizing_value: 100,
    stop_loss_pct: 2.0,
    take_profit_pct: null,
    entry_order_type: "market",
    limit_price_offset_pct: 0.0,
  },
  created_at: "2026-09-15T22:09:18Z",
  updated_at: "2026-09-15T22:09:18Z",
};

beforeEach(() => {
  useAssistantStore.setState({
    text: "", result: null, explanation: null,
    loading: false, loadingGenerate: false, loadingExplain: false,
    error: null,
  });
  useStrategyStore.setState({
    strategies: [STRATEGY_META],
    draft: null, draftIsNew: false, dirty: false,
    loading: false, removing: false, saving: false, previewing: false,
    error: null, lastPreview: null,
  });
  useToastStore.getState().clear();
  mock.mockReset();
  mock.mockImplementation(async (url: string) => {
    if (url === "/api/strategies") return { records: [STRATEGY_META] };
    return {};
  });
});

afterEach(() => {
  useToastStore.getState().clear();
});

describe("BDA redesign — suggest round-trip", () => {
  it("POSTs the request and renders the returned spec readably", async () => {
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/assistant/strategy-from-text") {
        return {
          spec: SPEC_FIXTURE,
          notes: ["Recognized indicator: rsi (alias=rsi14)"],
          saved_id: null,
        };
      }
      return { records: [STRATEGY_META] };
    });
    render(<BDAPane />);

    fireEvent.change(screen.getByLabelText(/strategy request/i), {
      target: { value: "buy RSI below 30, sell above 70, BTC/USDT 1h" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-generate-button"));
    });

    const call = mock.mock.calls.find(
      ([url]) => url === "/api/assistant/strategy-from-text");
    expect(call).toBeTruthy();
    const init = call![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      text: "buy RSI below 30, sell above 70, BTC/USDT 1h",
      save: false,
    });

    expect(screen.getByTestId("bda-spec-name")).toHaveTextContent("NL: rsi");
    expect(screen.getByTestId("bda-spec-timeframe")).toHaveTextContent("1h");
    expect(screen.getByTestId("bda-spec-indicators")).toHaveTextContent("rsi14");
    expect(screen.getByTestId("bda-spec-indicators")).toHaveTextContent("period=14");
    expect(screen.getByTestId("bda-spec-entries")).toHaveTextContent(/crosses below/);
    expect(screen.getByTestId("bda-spec-entries")).toHaveTextContent("30");
    expect(screen.getByTestId("bda-spec-exits")).toHaveTextContent(/crosses above/);
    expect(screen.getByTestId("bda-spec-exits")).toHaveTextContent("70");
    expect(screen.getByTestId("bda-spec-position")).toHaveTextContent(/long/);
    expect(screen.getByTestId("bda-spec-position")).toHaveTextContent(
      /fixed_quote 100/);
    expect(screen.getByTestId("bda-spec-position")).toHaveTextContent(/SL 2/);
    expect(screen.getByTestId("bda-spec-position")).toHaveTextContent(/entry market/);
  });

  it("renders an honest 'no spec' result when the parser extracts nothing", async () => {
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/assistant/strategy-from-text") {
        return {
          spec: null,
          notes: ["No recognized indicator found. Add one of these indicators…"],
          saved_id: null,
        };
      }
      return { records: [STRATEGY_META] };
    });
    render(<BDAPane />);
    fireEvent.change(screen.getByLabelText(/strategy request/i), {
      target: { value: "divergence breakout" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-generate-button"));
    });
    expect(screen.getByTestId("bda-no-spec")).toBeInTheDocument();
    expect(screen.getByTestId("bda-result")).toHaveTextContent(
      /No recognized indicator/);
  });
});

describe("BDA redesign — suggest + save", () => {
  it("saved_id renders the pill, raises a success toast and clears the editor", async () => {
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/assistant/strategy-from-text") {
        return { spec: SPEC_FIXTURE, notes: [], saved_id: SPEC_FIXTURE.id };
      }
      if (url === "/api/strategies") return { records: [STRATEGY_META] };
      return {};
    });
    render(<BDAPane />);
    fireEvent.change(screen.getByLabelText(/strategy request/i), {
      target: { value: "buy RSI below 30" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-generate-save-button"));
    });

    const call = mock.mock.calls.find(
      ([url]) => url === "/api/assistant/strategy-from-text");
    expect(call).toBeTruthy();
    expect(JSON.parse(String((call![1] as RequestInit).body)).save).toBe(true);

    await waitFor(() =>
      expect(screen.getByTestId("bda-saved-indicator")).toBeInTheDocument());
    expect(screen.getByTestId("bda-saved-indicator")).toHaveTextContent("c00f97d8");
    expect(useAssistantStore.getState().text).toBe("");
    const toasts = useToastStore.getState().toasts;
    expect(
      toasts.some((t) => t.tone === "success" && /saved/i.test(t.title)),
    ).toBe(true);
    // The strategy list is refreshed so STRA/BOT dropdowns see the new spec.
    expect(mock.mock.calls.some(([url]) => url === "/api/strategies")).toBe(true);
  });
});

describe("BDA redesign — explain strategy", () => {
  it("POSTs the selected id and renders the explanation", async () => {
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/assistant/explain-strategy") {
        return { explanation: "**KAOS Multibot** stratejisi 15m timeframe'inde çalışır." };
      }
      return { records: [STRATEGY_META] };
    });
    render(<BDAPane />);

    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "kaos-multibot" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-explain-button"));
    });

    const call = mock.mock.calls.find(
      ([url]) => url === "/api/assistant/explain-strategy");
    expect(call).toBeTruthy();
    expect(JSON.parse(String((call![1] as RequestInit).body))).toEqual({
      strategy_id: "kaos-multibot",
    });
    expect(screen.getByTestId("bda-explanation")).toHaveTextContent("KAOS Multibot");
    // The engine's **bold** marker is rendered, not shown raw.
    expect(
      within(screen.getByTestId("bda-explanation")).getByText("KAOS Multibot").tagName,
    ).toBe("STRONG");
  });
});

describe("BDA redesign — disabled states", () => {
  it("empty request blocks both suggest actions; typing enables them", () => {
    render(<BDAPane />);
    const gen = screen.getByTestId("bda-generate-button") as HTMLButtonElement;
    const genSave = screen.getByTestId("bda-generate-save-button") as HTMLButtonElement;
    expect(gen.disabled).toBe(true);
    expect(genSave.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/strategy request/i), {
      target: { value: "RSI" },
    });
    expect(gen.disabled).toBe(false);
    expect(genSave.disabled).toBe(false);
  });

  it("explain is disabled until a strategy is selected", () => {
    render(<BDAPane />);
    const ex = screen.getByTestId("bda-explain-button") as HTMLButtonElement;
    expect(ex.disabled).toBe(true);
    fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "kaos-multibot" },
    });
    expect(ex.disabled).toBe(false);
  });
});

describe("BDA redesign — failure honesty", () => {
  it("a rejected request surfaces the inline error and an error toast", async () => {
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/assistant/strategy-from-text") {
        throw new Error("sidecar exploded");
      }
      return { records: [STRATEGY_META] };
    });
    render(<BDAPane />);
    fireEvent.change(screen.getByLabelText(/strategy request/i), {
      target: { value: "buy RSI below 30" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-generate-button"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("bda-error")).toHaveTextContent(/sidecar exploded/));
    expect(
      useToastStore.getState().toasts.some(
        (t) => t.tone === "error" && /failed/i.test(t.title)),
    ).toBe(true);
  });
});

describe("BDA redesign — pane chrome + examples", () => {
  it("renders the pane header code, footer api row and an empty explain state", async () => {
    useStrategyStore.setState({ strategies: [] });
    mock.mockImplementation(async (url: string) => {
      if (url === "/api/strategies") return { records: [] };
      return {};
    });
    render(<BDAPane />);
    expect(screen.getByText("BDA")).toBeInTheDocument();
    expect(screen.getByText("/api/assistant/*")).toBeInTheDocument();
    // Subtitle renders a real arrow, never the literal "\u2192" escape.
    expect(screen.getByText(/strategy-spec helper/i)).toBeInTheDocument();
    expect(screen.queryByText(/u2192/)).toBeNull();
    // No strategies available → honest empty state instead of a dead picker.
    await waitFor(() =>
      expect(screen.getByTestId("bda-explain-empty")).toBeInTheDocument());
  });

  it("example chips fill the request box", () => {
    render(<BDAPane />);
    fireEvent.click(screen.getByTestId("bda-example-0"));
    expect(useAssistantStore.getState().text).toMatch(/RSI below 30/);
  });
});
