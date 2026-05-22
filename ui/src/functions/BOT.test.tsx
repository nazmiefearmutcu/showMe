import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { BOTPane } from "./BOT";
import { useBotStore } from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";

beforeEach(() => {
  useBotStore.setState({
    bots: [], draft: null, draftIsNew: false, dirty: false, loading: false, error: null,
  });
  useStrategyStore.setState({
    strategies: [{ id: "s1", name: "RSI-rev", description: "", timeframe: "1h",
                   created_at: "", updated_at: "" }],
    draft: null, draftIsNew: false, dirty: false, loading: false, error: null, lastPreview: null,
  });
  useExchangeStore.setState({
    catalog: [],
    credentials: [{ id: "c1", exchange_id: "binance", account_label: "main",
                    permissions: ["read"], created_at: "" }],
    selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
  });
});

describe("BOT pane", () => {
  it("shows empty-state copy when no draft", () => {
    render(<BOTPane />);
    expect(screen.getAllByText(/yeni bot/i).length).toBeGreaterThan(0);
  });

  it("Yeni bot opens a blank draft", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ yeni bot$/i })[0]);
    expect(useBotStore.getState().draft).not.toBeNull();
    expect(screen.getByLabelText(/strateji/i)).toBeInTheDocument();
  });

  it("renders strategy and credential dropdowns", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ yeni bot$/i })[0]);
    expect(screen.getByText("RSI-rev")).toBeInTheDocument();
    expect(screen.getByText(/binance:main/)).toBeInTheDocument();
  });

  it("setting symbol marks dirty", () => {
    render(<BOTPane />);
    fireEvent.click(screen.getAllByRole("button", { name: /^\+ yeni bot$/i })[0]);
    fireEvent.change(screen.getByLabelText(/symbol/i), { target: { value: "btc/usdt" } });
    expect(useBotStore.getState().dirty).toBe(true);
    // Symbol coerces to upper:
    expect(useBotStore.getState().draft?.symbol).toBe("BTC/USDT");
  });

  it("renders status pill in list", () => {
    useBotStore.setState({
      bots: [{ id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
               symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
               created_at: "", updated_at: "" }],
    });
    render(<BOTPane />);
    expect(screen.getByText("OFF")).toBeInTheDocument();
  });

  it("live mode requires account_label match before enable", () => {
    useBotStore.setState({
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "live", enabled: false, signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
    });
    render(<BOTPane />);
    const enableBtn = screen.getByRole("button", { name: /etkinleştir/i }) as HTMLButtonElement;
    expect(enableBtn.disabled).toBe(true);
    const input = screen.getByPlaceholderText(/account_label/i);
    fireEvent.change(input, { target: { value: "main" } });
    expect(enableBtn.disabled).toBe(false);
  });
});
