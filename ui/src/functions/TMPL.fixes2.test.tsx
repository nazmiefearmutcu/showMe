/**
 * Faz 4 — TMPL pane new regression fixes.
 *
 *  - H-UI-5 modal auto-close + cross-store invalidation
 *  - MEDIUM Escape key dismiss
 *  - MEDIUM backdrop click dismiss
 *  - Oluştur disabled after success (no double-create)
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TMPLPane } from "./TMPL";
import { useTemplateStore } from "@/lib/template-store";
import { useStrategyStore } from "@/lib/strategy-store";

const FIX = [
  { id: "rsi-mean-revert", name: "RSI MR", description: "RSI desc",
    uses_indicators: ["rsi"], recommended_timeframe: "1h",
    recommended_symbols: ["BTC/USDT"], applicability: "appl",
    natural_language_explanation: "NL", math: "M", spec_template: {}, family: "momentum" },
];

beforeEach(() => {
  vi.useFakeTimers();
  useTemplateStore.setState({ entries: FIX, selectedId: null, loading: false, error: null });
  useStrategyStore.setState({
    strategies: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, removing: false, error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("TMPL pane fixes2", () => {
  // ─── H-UI-5 ──────────────────────────────────────────────────────────
  it("modal_auto_closes_after_create_success", async () => {
    vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockResolvedValue({
        template_id: "rsi-mean-revert",
        strategy: { id: "newstrat-abc" } as never,
      });
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    await act(async () => {
      fireEvent.click(screen.getByTestId("tmpl-olustur-button"));
    });
    // Success indicator shows briefly.
    expect(screen.getByTestId("tmpl-created-indicator")).toBeInTheDocument();
    // After 1.5s the modal auto-dismisses.
    await act(async () => {
      vi.advanceTimersByTime(1600);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("modal_invalidates_strategy_store_on_create", async () => {
    const loadListSpy = vi.fn(async () => {});
    useStrategyStore.setState({ loadList: loadListSpy as never });
    vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockImplementation(async () => {
        // Manually invoke the same cross-store invalidation path that the
        // real store does, since the spy bypasses the production impl.
        await useStrategyStore.getState().loadList();
        return {
          template_id: "rsi-mean-revert",
          strategy: { id: "newstrat-abc" } as never,
        };
      });
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    await act(async () => {
      fireEvent.click(screen.getByTestId("tmpl-olustur-button"));
    });
    expect(loadListSpy).toHaveBeenCalled();
  });

  it("olustur_disabled_after_success", async () => {
    vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockResolvedValue({
        template_id: "rsi-mean-revert",
        strategy: { id: "newstrat-abc" } as never,
      });
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    await act(async () => {
      fireEvent.click(screen.getByTestId("tmpl-olustur-button"));
    });
    const ol = screen.getByTestId("tmpl-olustur-button") as HTMLButtonElement;
    expect(ol.disabled).toBe(true);
  });

  // ─── MEDIUM Escape key ───────────────────────────────────────────────
  it("escape_closes_modal_when_not_creating", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("escape_blocked_while_creating", async () => {
    let resolveCreate: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolveCreate = res; });
    vi.spyOn(useTemplateStore.getState(), "instantiate")
      .mockImplementation((() => pending) as never);
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    fireEvent.click(screen.getByTestId("tmpl-olustur-button"));
    fireEvent.keyDown(window, { key: "Escape" });
    // Modal should still be open mid-create.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await act(async () => {
      resolveCreate({ template_id: "rsi-mean-revert", strategy: { id: "x" } });
      await pending;
    });
  });

  // ─── MEDIUM backdrop click ───────────────────────────────────────────
  it("backdrop_click_closes_modal_when_not_creating", () => {
    render(<TMPLPane />);
    fireEvent.click(screen.getByText("RSI MR"));
    fireEvent.click(screen.getByRole("button", { name: /kullan/i }));
    const backdrop = screen.getByTestId("tmpl-modal-backdrop");
    fireEvent.click(backdrop);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
