/**
 * Faz 3 — BOT pane regression fixes (B-C1, B-C2, B-C3, B-C4, H-1).
 *
 * These tests pin user-facing safety behavior at the pane layer. They spy on
 * the bot-store action surface (already covered at the wire layer by
 * bot-store.fixes.test.ts) so we can assert what the pane forwards, without
 * having to model the mount-time loadList side-effect.
 *
 *   - Delete destructive confirm
 *   - Save client-side validation gate (strategy/credential/symbol)
 *   - shadow → live save threads confirm_account_label
 *   - Rapid double-click on Save → single store.save() invocation
 *   - Credential deselect clears stale exchange_id
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOTPane } from "./BOT";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";

beforeEach(() => {
  // No-op the mount-time loaders so the test never touches the network.
  useBotStore.setState({
    bots: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, error: null,
    loadList: vi.fn(async () => {}),
  });
  useStrategyStore.setState({
    strategies: [{ id: "s1", name: "RSI-rev", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: null, draftIsNew: false, dirty: false, loading: false, error: null, lastPreview: null,
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

describe("BOT pane fixes", () => {
  // ─── B-C1 ────────────────────────────────────────────────────────────
  it("delete_confirms — Delete aborts when ConfirmDialog cancel pressed", () => {
    const removeSpy = vi.fn(async () => true);
    useBotStore.setState({
      remove: removeSpy,
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
    });
    render(<BOTPane />);
    fireEvent.click(screen.getByTestId("bot-delete-button"));
    expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    expect(removeSpy).not.toHaveBeenCalled();
  });

  it("delete_confirms_yes — Delete fires remove on ConfirmDialog confirm", () => {
    const removeSpy = vi.fn(async () => true);
    useBotStore.setState({
      remove: removeSpy,
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
    });
    render(<BOTPane />);
    fireEvent.click(screen.getByTestId("bot-delete-button"));
    expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(removeSpy).toHaveBeenCalledWith("b1");
  });

  // ─── B-C2 ────────────────────────────────────────────────────────────
  it("save_disabled_when_empty — Save disabled while strategy/credential/symbol blank", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ new bot$/i })[0]);
    const saveButton = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
  });

  it("save_disabled_until_all_fields_filled — fill 2/3 still disabled", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ new bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/strategy/i), { target: { value: "s1" } });
    fireEvent.change(screen.getByLabelText(/^symbol$/i), { target: { value: "btc/usdt" } });
    const saveButton = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
    expect(screen.queryByTestId("bot-field-err-credential")).toBeInTheDocument();
  });

  it("save_enabled_when_all_fields_filled", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ new bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/strategy/i), { target: { value: "s1" } });
    fireEvent.change(screen.getByLabelText(/connection/i), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText(/^symbol$/i), { target: { value: "btc/usdt" } });
    const saveButton = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(false);
  });

  it("save_shows_inline_errors_for_each_empty_field", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ new bot$/i })[0]);
    expect(screen.getByTestId("bot-field-err-strategy")).toBeInTheDocument();
    expect(screen.getByTestId("bot-field-err-credential")).toBeInTheDocument();
    expect(screen.getByTestId("bot-field-err-symbol")).toBeInTheDocument();
  });

  // ─── B-C3 ────────────────────────────────────────────────────────────
  it("save_shadow_to_live_includes_confirm_account_label", async () => {
    const saveSpy = vi.fn(async () => null);
    useBotStore.setState({
      save: saveSpy,
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
      draftIsNew: false, dirty: false,
    });
    render(<BOTPane />);
    // Flip mode → live via the radio.
    const liveRadios = screen.getAllByRole("radio");
    const liveRadio = liveRadios.find((r) => !(r as HTMLInputElement).checked)!;
    fireEvent.click(liveRadio);
    // Live-confirm input appears.
    const confirmInput = screen.getByTestId("bot-save-confirm-label") as HTMLInputElement;
    fireEvent.change(confirmInput, { target: { value: "main" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    });
    // Pane passes the confirm label through to the store action.
    expect(saveSpy).toHaveBeenCalledWith("main");
  });

  it("save_shadow_to_live_blocks_when_label_blank", () => {
    const saveSpy = vi.fn(async () => null);
    useBotStore.setState({
      save: saveSpy,
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
      draftIsNew: false, dirty: false,
    });
    render(<BOTPane />);
    const liveRadios = screen.getAllByRole("radio");
    const liveRadio = liveRadios.find((r) => !(r as HTMLInputElement).checked)!;
    fireEvent.click(liveRadio);
    // Inline error + disabled Save.
    expect(screen.getByTestId("bot-field-err-confirm-label")).toBeInTheDocument();
    const saveButton = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
    expect(saveSpy).not.toHaveBeenCalled();
  });

  // ─── B-C4 ────────────────────────────────────────────────────────────
  it("concurrent_save_single_invocation — rapid double-click fires once", async () => {
    // Use a long-running save so the saving flag stays true through the
    // second click; the button must be disabled mid-flight.
    let resolveSave: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolveSave = res; });
    const saveSpy = vi.fn(() => {
      useBotStore.setState({ saving: true });
      return pending;
    });
    useBotStore.setState({ save: saveSpy as never });

    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ new bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/strategy/i), { target: { value: "s1" } });
    fireEvent.change(screen.getByLabelText(/connection/i), { target: { value: "c1" } });
    fireEvent.change(screen.getByLabelText(/^symbol$/i), { target: { value: "BTC/USDT" } });

    const saveButton = screen.getByRole("button", { name: /^save$/i }) as HTMLButtonElement;
    fireEvent.click(saveButton);
    // After first click, the saving flag should disable the button.
    expect(saveButton.disabled).toBe(true);
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    expect(saveSpy).toHaveBeenCalledTimes(1);

    // Unwind.
    await act(async () => {
      resolveSave(null);
      useBotStore.setState({ saving: false });
      await pending;
    });
  });

  // ─── H-1 ────────────────────────────────────────────────────────────
  it("credential_deselect_clears_exchange_id", () => {
    useBotStore.setState({
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
    });
    render(<BOTPane />);
    fireEvent.change(screen.getByLabelText(/connection/i), { target: { value: "" } });
    expect(useBotStore.getState().draft?.credential_id).toBe("");
    expect(useBotStore.getState().draft?.exchange_id).toBe("");
  });
});
