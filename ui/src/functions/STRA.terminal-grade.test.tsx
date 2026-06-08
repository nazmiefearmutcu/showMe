/**
 * STRA — terminal-grade upgrade tests.
 *
 * Covers:
 *  P1 — synthetic-preview disclosure (honest about the data source).
 *  P2 — no nonexistent CSS tokens (--accent-err / --fg-2) left in source.
 *  P3 — aria-labels on indicator-type / operator selects + remove/delete buttons.
 *  P5 — empty / loading states for the sidebar list.
 *
 * These are additive; the existing STRA suites stay green.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { STRAPane } from "./STRA";
import { useStrategyStore } from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

const __dir = dirname(fileURLToPath(import.meta.url));

const BASE_DRAFT = {
  id: "abc", name: "Existing", description: "", timeframe: "1h",
  version: 1, asset_filter: {},
  indicators: [{ alias: "rsi_1", id: "rsi", params: {} }],
  entry_rules: [{ kind: "greater_than", left: "rsi_1", right: "literal:30" }],
  exit_rules: [],
  entry_logic: "all", exit_logic: "any",
  position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
  created_at: "", updated_at: "",
};

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [{ id: "abc", name: "Existing", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: BASE_DRAFT as never,
    draftIsNew: false, dirty: false, loading: false, removing: false,
    saving: false, previewing: false, error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
  useIndicatorStore.setState({
    entries: [
      { id: "rsi", display_name: "RSI", family: "momentum", short_description: "",
        long_description: "", formula: "", parameters: [], confidence: 9,
        confidence_rationale: "", suggested_strategy: {}, references: [] },
    ],
    loading: false, error: null, selectedId: null,
    loadCatalog: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("STRA P1 — synthetic preview disclosure", () => {
  it("shows synthetic disclosure when preview source is synthetic", () => {
    useStrategyStore.setState({
      lastPreview: {
        strategy_id: "abc", symbol: "BTC/USDT", timeframe: "1h",
        bars: 100, events: [], source: "synthetic_random_walk",
      },
    });
    render(<STRAPane />);
    const note = screen.getByTestId("stra-preview-synthetic-note");
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/synthetic/i);
    expect(note.textContent).toMatch(/not real market/i);
  });

  it("does NOT show synthetic disclosure when source is real", () => {
    useStrategyStore.setState({
      lastPreview: {
        strategy_id: "abc", symbol: "BTC/USDT", timeframe: "1h",
        bars: 100, events: [], source: "exchange_ohlcv",
      },
    });
    render(<STRAPane />);
    expect(screen.queryByTestId("stra-preview-synthetic-note")).toBeNull();
  });
});

describe("STRA P3 — accessibility labels", () => {
  it("indicator-type select has an aria-label", () => {
    render(<STRAPane />);
    expect(screen.getByLabelText(/indicator type/i)).toBeInTheDocument();
  });

  it("rule operator select has an aria-label", () => {
    render(<STRAPane />);
    // BASE_DRAFT has one entry rule → its operator select must be labelled.
    expect(screen.getAllByLabelText(/operator/i).length).toBeGreaterThanOrEqual(1);
  });

  it("remove-indicator button has an aria-label", () => {
    render(<STRAPane />);
    expect(screen.getByLabelText(/remove indicator/i)).toBeInTheDocument();
  });

  it("remove-rule button has an aria-label", () => {
    render(<STRAPane />);
    expect(screen.getAllByLabelText(/remove rule/i).length).toBeGreaterThanOrEqual(1);
  });

  it("delete-strategy button has an aria-label", () => {
    render(<STRAPane />);
    expect(screen.getByLabelText(/delete strategy/i)).toBeInTheDocument();
  });

  it("disabled Save button has an explanatory title", () => {
    // not dirty → Save is disabled and must explain why.
    render(<STRAPane />);
    const save = screen.getByTestId("stra-save-button") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("title")).toBeTruthy();
  });
});

describe("STRA P5 — empty / loading sidebar states", () => {
  it("shows an Empty component when list is empty and not loading", () => {
    useStrategyStore.setState({ strategies: [], draft: null, loading: false });
    render(<STRAPane />);
    expect(screen.getByTestId("stra-list-empty")).toBeInTheDocument();
  });

  it("shows a skeleton placeholder while list is loading + empty", () => {
    useStrategyStore.setState({ strategies: [], draft: null, loading: true });
    render(<STRAPane />);
    expect(screen.getByTestId("stra-list-loading")).toBeInTheDocument();
  });
});

describe("STRA P2 — no nonexistent CSS tokens", () => {
  it("STRA.tsx references no nonexistent CSS tokens", () => {
    const src = readFileSync(join(__dir, "STRA.tsx"), "utf8");
    expect(src).not.toMatch(/--accent-err\b/);
    expect(src).not.toMatch(/--fg-2\b/);
    expect(src).not.toMatch(/--border-1\b/);
    expect(src).not.toMatch(/--accent-warn\b/);
  });
});
