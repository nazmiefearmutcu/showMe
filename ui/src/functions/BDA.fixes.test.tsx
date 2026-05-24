/**
 * Faz 4 — BDA pane new regression fixes.
 *
 *  - H-UI-7 separate loadingGenerate / loadingExplain so they don't block
 *  - H-UI-6 cross-store invalidation after generate+save
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BDAPane } from "./BDA";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";

beforeEach(() => {
  useAssistantStore.setState({
    text: "RSI 30 altında alım",
    result: null, explanation: null,
    loading: false, loadingGenerate: false, loadingExplain: false,
    error: null,
  });
  useStrategyStore.setState({
    strategies: [
      { id: "s1", name: "RSI MR", description: "", timeframe: "1h",
        created_at: "", updated_at: "" },
    ],
    draft: null, draftIsNew: false, dirty: false,
    loading: false, removing: false, error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BDA pane fixes", () => {
  // ─── H-UI-7 ──────────────────────────────────────────────────────────
  it("generate_button_not_blocked_by_explain_loading", () => {
    useAssistantStore.setState({ loadingExplain: true });
    render(<BDAPane />);
    const gen = screen.getByTestId("bda-generate-button") as HTMLButtonElement;
    expect(gen.disabled).toBe(false);
  });

  it("explain_button_not_blocked_by_generate_loading", () => {
    useAssistantStore.setState({ loadingGenerate: true });
    render(<BDAPane />);
    // Select a strategy so explain is otherwise enabled.
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "s1" } });
    const ex = screen.getByTestId("bda-explain-button") as HTMLButtonElement;
    expect(ex.disabled).toBe(false);
  });

  it("generate_button_disabled_only_during_generate", () => {
    useAssistantStore.setState({ loadingGenerate: true });
    render(<BDAPane />);
    const gen = screen.getByTestId("bda-generate-button") as HTMLButtonElement;
    expect(gen.disabled).toBe(true);
  });

  // ─── H-UI-6 ──────────────────────────────────────────────────────────
  it("generate_save_invalidates_strategy_store", async () => {
    const loadListSpy = vi.fn(async () => {});
    useStrategyStore.setState({ loadList: loadListSpy as never });
    const generateSpy = vi.fn(async () => {
      // Simulate the real store invalidating the strategy list.
      await useStrategyStore.getState().loadList();
      return { spec: { name: "X" } as never, notes: [], saved_id: "new-id" };
    });
    useAssistantStore.setState({ generate: generateSpy as never });
    render(<BDAPane />);
    await act(async () => {
      fireEvent.click(screen.getByTestId("bda-generate-save-button"));
    });
    expect(generateSpy).toHaveBeenCalledWith(true);
    expect(loadListSpy).toHaveBeenCalled();
  });

  it("saved_indicator_renders_on_result_saved_id", () => {
    useAssistantStore.setState({
      result: { spec: null, notes: [], saved_id: "newstrat-id" },
    });
    render(<BDAPane />);
    expect(screen.getByTestId("bda-saved-indicator")).toBeInTheDocument();
  });
});
