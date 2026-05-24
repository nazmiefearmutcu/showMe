/**
 * Faz 4 — BOT pane new regression fixes (C-UI-1..C-UI-5 + H-UI-* batch).
 *
 * Focus areas:
 *  - Orphan strategy/credential dropdown surfacing (C-UI-1)
 *  - Symbol whitespace/format validation (C-UI-2)
 *  - Tick interval clamp + no silent reset (C-UI-3)
 *  - originalMode re-capture after save (C-UI-4)
 *  - Etkinleştir loading guard + confirmLabel reset (H-UI-1, H-UI-2)
 *  - Unknown timeframe coerce guard (H-UI-3)
 *  - Dirty-draft switch warning (H-UI-10)
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTPane } from "./BOT";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";

const PERSISTED_DRAFT = {
  id: "b1",
  strategy_id: "s1",
  credential_id: "c1",
  exchange_id: "binance",
  symbol: "BTC/USDT",
  timeframe: "1h",
  tick_interval_seconds: 60,
  mode: "shadow",
  enabled: false,
  signal_log: [],
  last_processed_event: null,
  created_at: "",
  updated_at: "",
};

beforeEach(() => {
  useBotStore.setState({
    bots: [
      { id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
        created_at: "", updated_at: "" },
      { id: "b2", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "ETH/USDT", timeframe: "1h", mode: "shadow", enabled: false,
        created_at: "", updated_at: "" },
    ],
    draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, toggling: false, error: null,
    loadList: vi.fn(async () => {}),
  });
  useStrategyStore.setState({
    strategies: [{ id: "s1", name: "RSI-rev", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: null, draftIsNew: false, dirty: false, loading: false, removing: false,
    error: null, lastPreview: null,
    loadList: vi.fn(async () => {}),
  });
  useExchangeStore.setState({
    catalog: [],
    credentials: [{ id: "c1", exchange_id: "binance", account_label: "main",
                    permissions: ["read", "trade"], created_at: "" }],
    selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    loadCredentials: vi.fn(async () => {}),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BOT pane fixes2", () => {
  // ─── C-UI-1 ──────────────────────────────────────────────────────────
  it("orphan_strategy_surfaces — silinmiş strategy id dropdown'da görünür", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, strategy_id: "ghost-id" } as never,
    });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-strategy-orphan-option")).toBeInTheDocument();
    expect(screen.getByTestId("bot-field-err-strategy-orphan")).toBeInTheDocument();
    // Save must be disabled even though the field is "non-empty".
    const kaydet = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(kaydet.disabled).toBe(true);
  });

  it("orphan_credential_surfaces", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, credential_id: "ghost-c" } as never,
    });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-credential-orphan-option")).toBeInTheDocument();
    expect(screen.getByTestId("bot-field-err-credential-orphan")).toBeInTheDocument();
  });

  // ─── C-UI-2 ──────────────────────────────────────────────────────────
  it("symbol_validation_rejects_whitespace_only", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, symbol: "   " } as never,
    });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-field-err-symbol")).toBeInTheDocument();
  });

  it("symbol_validation_rejects_bad_format", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ yeni bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/strateji/i), { target: { value: "s1" } });
    fireEvent.change(screen.getByLabelText(/bağlantı/i), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText(/^symbol$/i), { target: { value: "BTC-USDT" } });
    expect(screen.getByTestId("bot-field-err-symbol").textContent).toMatch(/BASE\/QUOTE/);
    const kaydet = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(kaydet.disabled).toBe(true);
  });

  it("symbol_normalize_uppercases_on_input", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ yeni bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/^symbol$/i), { target: { value: "btc/usdt" } });
    expect(useBotStore.getState().draft?.symbol).toBe("BTC/USDT");
  });

  // ─── C-UI-3 ──────────────────────────────────────────────────────────
  it("tick_interval_input_keeps_raw_until_blur", () => {
    useBotStore.setState({ draft: { ...PERSISTED_DRAFT } as never });
    render(<BOTPane />);
    const input = screen.getByLabelText(/tick interval/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "" } });
    // State should NOT silent-reset to 60 mid-edit.
    expect(input.value).toBe("");
    expect(useBotStore.getState().draft?.tick_interval_seconds).toBe(60);
    // On blur the value commits with clamp.
    fireEvent.blur(input);
    expect(useBotStore.getState().draft?.tick_interval_seconds).toBe(60);
  });

  it("tick_interval_blur_clamps_negatives", () => {
    useBotStore.setState({ draft: { ...PERSISTED_DRAFT } as never });
    render(<BOTPane />);
    const input = screen.getByLabelText(/tick interval/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "-5" } });
    fireEvent.blur(input);
    expect(useBotStore.getState().draft?.tick_interval_seconds).toBe(5);
  });

  it("tick_interval_blur_clamps_above_max", () => {
    useBotStore.setState({ draft: { ...PERSISTED_DRAFT } as never });
    render(<BOTPane />);
    const input = screen.getByLabelText(/tick interval/i) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "99999" } });
    fireEvent.blur(input);
    expect(useBotStore.getState().draft?.tick_interval_seconds).toBe(3600);
  });

  // ─── C-UI-4 ──────────────────────────────────────────────────────────
  it("original_mode_recaptures_after_save_success", async () => {
    const savedRec = { ...PERSISTED_DRAFT, mode: "live" } as never;
    const saveSpy = vi.fn(async () => {
      // Simulate the save's commit (dirty=false, persisted mode=live).
      useBotStore.setState({ draft: savedRec, dirty: false });
      return savedRec;
    });
    useBotStore.setState({
      save: saveSpy as never,
      draft: { ...PERSISTED_DRAFT } as never,
    });
    render(<BOTPane />);
    // Flip to live + type confirmLabel.
    const liveRadio = screen.getAllByRole("radio").find(
      (r) => !(r as HTMLInputElement).checked,
    )!;
    fireEvent.click(liveRadio);
    const confirmInput = screen.getByTestId("bot-save-confirm-label") as HTMLInputElement;
    fireEvent.change(confirmInput, { target: { value: "main" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^kaydet$/i }));
    });
    // After the save settled the persisted mode is live and dirty=false.
    // The pane should NOT keep flagging a shadow→live transition for the
    // *current* draft — no confirm input should be on screen.
    expect(screen.queryByTestId("bot-save-confirm-label")).toBeNull();
  });

  // ─── H-UI-1 ──────────────────────────────────────────────────────────
  it("confirmLabel_clears_after_successful_live_save", async () => {
    const savedRec = { ...PERSISTED_DRAFT, mode: "live" } as never;
    const saveSpy = vi.fn(async () => {
      useBotStore.setState({ draft: savedRec, dirty: false });
      return savedRec;
    });
    useBotStore.setState({
      save: saveSpy as never,
      draft: { ...PERSISTED_DRAFT } as never,
    });
    render(<BOTPane />);
    const liveRadio = screen.getAllByRole("radio").find(
      (r) => !(r as HTMLInputElement).checked,
    )!;
    fireEvent.click(liveRadio);
    const confirmInput = screen.getByTestId("bot-save-confirm-label") as HTMLInputElement;
    fireEvent.change(confirmInput, { target: { value: "main" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^kaydet$/i }));
    });
    // After save, Etkinleştir bar's confirm input (live mode) should be
    // empty — no pre-filled stale label.
    const labelInput = screen.queryByPlaceholderText(/account_label tekrar yaz/i) as HTMLInputElement | null;
    if (labelInput) {
      expect(labelInput.value).toBe("");
    }
  });

  // ─── H-UI-2 ──────────────────────────────────────────────────────────
  it("etkinlestir_disabled_while_toggling", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT } as never,
      toggling: true,
    });
    render(<BOTPane />);
    const btn = screen.getByRole("button", { name: /etkinleştir|^\.\.\.$/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("durdur_disabled_while_toggling", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, enabled: true } as never,
      toggling: true,
    });
    render(<BOTPane />);
    const btn = screen.getByRole("button", { name: /durdur|^\.\.\.$/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  // ─── H-UI-3 ──────────────────────────────────────────────────────────
  it("unknown_timeframe_surfaces_as_option", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, timeframe: "30m" } as never,
    });
    render(<BOTPane />);
    expect(screen.getByTestId("bot-timeframe-unknown-option")).toBeInTheDocument();
    expect(screen.getByTestId("bot-field-err-timeframe")).toBeInTheDocument();
    const kaydet = screen.getByRole("button", { name: /^kaydet$/i }) as HTMLButtonElement;
    expect(kaydet.disabled).toBe(true);
  });

  // ─── H-UI-10 ─────────────────────────────────────────────────────────
  // Round 24 — window.confirm replaced with the non-blocking ConfirmDialog
  // component. The dialog renders into the same document; we assert by
  // finding the dialog body + clicking Cancel/Confirm.
  it("dirty_switch_prompts_confirm", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT } as never,
      dirty: true,
    });
    const openSpy = vi.fn(async () => {});
    useBotStore.setState({ openExisting: openSpy as never });
    render(<BOTPane />);
    // Find the second bot's row and click it.
    const allButtons = screen.getAllByRole("button");
    const ethRow = allButtons.find((b) => b.textContent?.includes("ETH/USDT"));
    expect(ethRow).toBeDefined();
    fireEvent.click(ethRow!);
    // ConfirmDialog should be open.
    expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument();
    // Click Cancel — openExisting must NOT have fired.
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(openSpy).not.toHaveBeenCalled();
  });

  it("dirty_switch_proceeds_when_confirmed", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT } as never,
      dirty: true,
    });
    const openSpy = vi.fn(async () => {});
    useBotStore.setState({ openExisting: openSpy as never });
    render(<BOTPane />);
    const allButtons = screen.getAllByRole("button");
    const ethRow = allButtons.find((b) => b.textContent?.includes("ETH/USDT"));
    fireEvent.click(ethRow!);
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(openSpy).toHaveBeenCalledWith("b2");
  });
});
