/**
 * Faz 3 — STRA pane regression fixes.
 *
 * Pin destructive-Sil confirmation (B-C1 mirror for strategies). Spies on
 * the strategy-store's remove action — the wire-level contract is unchanged.
 */
import { render, screen, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { STRAPane } from "./STRA";
import { useStrategyStore } from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [{ id: "abc", name: "Existing", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: {
      id: "abc", name: "Existing", description: "", timeframe: "1h",
      indicators: [], entry_rules: [], exit_rules: [],
      entry_logic: "all", exit_logic: "any",
      created_at: "", updated_at: "",
    } as never,
    draftIsNew: false, dirty: false, loading: false, error: null, lastPreview: null,
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

describe("STRA pane fixes", () => {
  // Round 24 CRITICAL 14 — window.confirm replaced with ConfirmDialog so
  // the tests now assert via the in-document dialog body.
  it("sil_confirms — Sil aborts when ConfirmDialog Cancel pressed", () => {
    const removeSpy = vi.fn(async () => true);
    useStrategyStore.setState({ remove: removeSpy });
    render(<STRAPane />);
    fireEvent.click(screen.getByTestId("stra-sil-button"));
    expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(removeSpy).not.toHaveBeenCalled();
  });

  it("sil_confirms_yes — Sil fires remove on ConfirmDialog Confirm", () => {
    const removeSpy = vi.fn(async () => true);
    useStrategyStore.setState({ remove: removeSpy });
    render(<STRAPane />);
    fireEvent.click(screen.getByTestId("stra-sil-button"));
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(removeSpy).toHaveBeenCalledWith("abc");
  });
});
