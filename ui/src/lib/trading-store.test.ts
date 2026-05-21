import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTradingStore } from "./trading-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("./portfolio-store", () => ({
  usePortfolioStore: { getState: () => ({ loadPortfolio: vi.fn() }) },
}));

import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useTradingStore.setState({
    ticket: null, pendingConfirm: null, submitting: false, lastResult: null,
  });
  mock.mockReset();
});

describe("trading-store", () => {
  it("openTicket initializes ticket fields", () => {
    useTradingStore.getState().openTicket("abc-id", "binance:abc-id");
    const t = useTradingStore.getState().ticket;
    expect(t).not.toBeNull();
    expect(t!.credentialId).toBe("abc-id");
    expect(t!.brokerName).toBe("binance:abc-id");
    expect(t!.side).toBe("buy");
    expect(t!.orderType).toBe("market");
  });

  it("requestSubmit moves ticket into pendingConfirm", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    expect(useTradingStore.getState().pendingConfirm?.kind).toBe("submit");
  });

  it("confirm sends POST to /api/broker/orders", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:abc", order: { id: "o1", status: "new" } });
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    await useTradingStore.getState().confirm("main");
    expect(mock.mock.calls[0][0]).toBe("/api/broker/orders");
    const init = mock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.symbol).toBe("BTC/USDT");
    expect(body.quantity).toBe(0.01);
    expect(body.broker).toBe("binance:abc");
    expect(useTradingStore.getState().lastResult?.ok).toBe(true);
  });

  it("confirm surfaces backend error", async () => {
    mock.mockRejectedValueOnce(new Error("403 permission"));
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit();
    await useTradingStore.getState().confirm("main");
    expect(useTradingStore.getState().lastResult?.ok).toBe(false);
    expect(useTradingStore.getState().lastResult?.error).toContain("403");
  });

  it("cancelOrder sends DELETE", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:abc", ok: true });
    await useTradingStore.getState().cancelOrder("binance:abc", "order-1");
    expect(mock.mock.calls[0][0]).toContain("/api/broker/orders/order-1");
    expect(mock.mock.calls[0][0]).toContain("name=binance");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });

  it("closePosition stages confirmation with opposite-side market order", () => {
    useTradingStore.getState().closePosition("binance:abc", "BTC/USDT", "buy", 0.5);
    const pc = useTradingStore.getState().pendingConfirm;
    expect(pc?.kind).toBe("close");
    expect(pc?.payload.side).toBe("sell");
    expect(pc?.payload.quantity).toBe(0.5);
    expect(pc?.payload.order_type).toBe("market");
  });
});
