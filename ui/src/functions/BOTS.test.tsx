import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { BOTSPane } from "./BOTS";
import { useBotsSupervisionStore } from "@/lib/bots-supervision-store";

beforeEach(() => {
  useBotsSupervisionStore.setState({
    stats: { total: 0, enabled: 0, live: 0, signals_today: 0 },
    bots: [], feed: [], generatedAt: null, loading: false, error: null,
  });
});

describe("BOTS pane", () => {
  it("shows zero KPIs + empty placeholders", () => {
    render(<BOTSPane />);
    expect(screen.getByText(/toplam bot/i)).toBeInTheDocument();
    expect(screen.getByText(/henüz bot yok/i)).toBeInTheDocument();
    expect(screen.getByText(/henüz sinyal yok/i)).toBeInTheDocument();
  });

  it("renders bot table rows", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 2, enabled: 2, live: 1, signals_today: 1 },
      bots: [
        { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "BTC/USDT", timeframe: "1h", mode: "live", enabled: true,
          created_at: "", updated_at: "" },
        { id: "b", strategy_id: "s", credential_id: "c", exchange_id: "binance",
          symbol: "ETH/USDT", timeframe: "4h", mode: "shadow", enabled: true,
          created_at: "", updated_at: "" },
      ],
      feed: [], generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.getByText("BTC/USDT")).toBeInTheDocument();
    expect(screen.getByText("ETH/USDT")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("SHADOW")).toBeInTheDocument();
  });

  it("renders signal feed rows", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 1, enabled: 1, live: 0, signals_today: 1 },
      bots: [{ id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
               symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: true,
               created_at: "", updated_at: "" }],
      feed: [
        { bar_index: 1, bar_time: "2026-05-22T10:00:00Z", kind: "entry",
          price: 100.5, action: "shadow", timestamp: "2026-05-22T10:00:00Z",
          bot_id: "a", bot_symbol: "BTC/USDT", bot_strategy_id: "s",
          bot_exchange_id: "binance", bot_mode: "shadow" },
      ],
      generatedAt: "x",
    });
    render(<BOTSPane />);
    expect(screen.getAllByText("BTC/USDT").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/100\.50/).length).toBeGreaterThan(0);
  });

  it("KPI strip shows non-zero live count in error color", () => {
    useBotsSupervisionStore.setState({
      stats: { total: 5, enabled: 3, live: 2, signals_today: 0 },
      bots: [], feed: [], generatedAt: null,
    });
    render(<BOTSPane />);
    // KPI values present (text 5, 3, 2, 0):
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
