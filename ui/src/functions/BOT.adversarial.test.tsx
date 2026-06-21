import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("BOT Pane Adversarial / Edge Cases", () => {
  it("enable button disabled if only strategyOrphan is true", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, strategy_id: "ghost-strategy" } as never,
    });
    render(<BOTPane />);
    // The Enable button should be disabled
    const btn = screen.getByRole("button", { name: /etkinleştir/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("enable button disabled if only credentialOrphan is true", () => {
    useBotStore.setState({
      draft: { ...PERSISTED_DRAFT, credential_id: "ghost-credential" } as never,
    });
    render(<BOTPane />);
    // The Enable button should be disabled
    const btn = screen.getByRole("button", { name: /etkinleştir/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});
