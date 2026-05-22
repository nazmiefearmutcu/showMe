import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { OrderTicket } from "./OrderTicket";
import { useTradingStore } from "@/lib/trading-store";

const BASE_PROPS = { credentialId: "abc", brokerName: "binance:abc", accountLabel: "main" };

beforeEach(() => {
  useTradingStore.setState({
    ticket: null, pendingConfirm: null, submitting: false, lastResult: null,
  });
});

describe("OrderTicket", () => {
  it("renders Trade button when no ticket open", () => {
    render(<OrderTicket {...BASE_PROPS} />);
    expect(screen.getByRole("button", { name: /trade/i })).toBeInTheDocument();
  });

  it("opens form when Trade clicked", () => {
    render(<OrderTicket {...BASE_PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: /trade/i }));
    expect(screen.getByLabelText(/symbol/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/quantity/i)).toBeInTheDocument();
  });

  it("limit_price field appears when type=limit", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    render(<OrderTicket {...BASE_PROPS} />);
    fireEvent.change(screen.getByLabelText(/^type$/i), { target: { value: "limit" } });
    expect(screen.getByLabelText(/limit price/i)).toBeInTheDocument();
  });

  it("Continue is disabled until symbol+qty present", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    render(<OrderTicket {...BASE_PROPS} />);
    const btn = screen.getByRole("button", { name: /continue/i }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/symbol/i), { target: { value: "BTC/USDT" } });
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "0.01" } });
    expect(btn.disabled).toBe(false);
  });

  it("Continue stages pendingConfirm", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    render(<OrderTicket {...BASE_PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(useTradingStore.getState().pendingConfirm).not.toBeNull();
    // Modal renders
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("Gönder button enables only with matching account_label", () => {
    useTradingStore.setState({
      pendingConfirm: {
        kind: "submit", brokerName: "binance:abc", accountLabel: "main",
        payload: { broker: "binance:abc", symbol: "BTC/USDT", side: "buy",
                   quantity: 0.01, order_type: "market", time_in_force: "gtc",
                   limit_price: null, stop_price: null, notes: "" },
      },
      ticket: { credentialId: "abc", brokerName: "binance:abc", symbol: "BTC/USDT",
                side: "buy", orderType: "market", quantity: 0.01,
                limitPrice: null, stopPrice: null, tif: "gtc", notes: "" },
    });
    render(<OrderTicket {...BASE_PROPS} />);
    const send = screen.getByRole("button", { name: /gönder/i }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    const input = screen.getByPlaceholderText("main") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "wrong" } });
    expect(send.disabled).toBe(true);
    fireEvent.change(input, { target: { value: "main" } });
    expect(send.disabled).toBe(false);
  });
});
