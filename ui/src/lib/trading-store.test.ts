import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTradingStore, normalizeSide } from "./trading-store";

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
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit("main");
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
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit("main");
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

  // ─── QA-2026-05-23 — accountLabel guard tightening ───────────────────────

  it("confirm REJECTS submit when accountLabel is empty (no bypass)", async () => {
    useTradingStore.getState().openTicket("abc", "binance:abc");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit(""); // empty label — the bypass
    await useTradingStore.getState().confirm(""); // typing matches but guard fires
    expect(mock).not.toHaveBeenCalled();
    const r = useTradingStore.getState().lastResult;
    expect(r?.ok).toBe(false);
    expect(r?.error).toContain("missing_account_label");
    expect(r?.kind).toBe("submit");
  });

  it("confirm REJECTS close when accountLabel is empty", async () => {
    useTradingStore.getState().closePosition(
      "binance:abc", "BTC/USDT", "buy", 0.5, /* accountLabel */ "",
    );
    await useTradingStore.getState().confirm("");
    expect(mock).not.toHaveBeenCalled();
    expect(useTradingStore.getState().lastResult?.ok).toBe(false);
    expect(useTradingStore.getState().lastResult?.error).toContain("missing_account_label");
  });

  it("confirm REJECTS when typed label does not match", async () => {
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit("main");
    await useTradingStore.getState().confirm("wrong");
    expect(mock).not.toHaveBeenCalled();
    expect(useTradingStore.getState().lastResult?.error).toBe("account_label mismatch");
  });

  // ─── QA-2026-05-23 — cancelOrder via confirm modal ───────────────────────

  it("requestCancel stages a cancel-kind pendingConfirm (no immediate DELETE)", () => {
    useTradingStore.getState().requestCancel("binance:abc", "order-1", "main", "BTC/USDT");
    expect(mock).not.toHaveBeenCalled();
    const pc = useTradingStore.getState().pendingConfirm;
    expect(pc?.kind).toBe("cancel");
    expect(pc?.orderId).toBe("order-1");
    expect(pc?.accountLabel).toBe("main");
    expect(pc?.symbol).toBe("BTC/USDT");
  });

  it("confirm on cancel-kind sends DELETE only after label re-type passes", async () => {
    mock.mockResolvedValueOnce({ ok: true });
    useTradingStore.getState().requestCancel("binance:abc", "order-1", "main");
    await useTradingStore.getState().confirm("main");
    expect(mock.mock.calls[0][0]).toContain("/api/broker/orders/order-1");
    expect(mock.mock.calls[0][0]).toContain("name=binance");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
    const r = useTradingStore.getState().lastResult;
    expect(r?.ok).toBe(true);
    expect(r?.kind).toBe("cancel");
    expect(r?.orderId).toBe("order-1");
  });

  it("cancel confirm surfaces backend error with kind=cancel", async () => {
    mock.mockRejectedValueOnce(new Error("404 not found"));
    useTradingStore.getState().requestCancel("binance:abc", "order-1", "main");
    await useTradingStore.getState().confirm("main");
    const r = useTradingStore.getState().lastResult;
    expect(r?.ok).toBe(false);
    expect(r?.kind).toBe("cancel");
    expect(r?.error).toContain("404");
  });

  // ─── QA-2026-05-23 — normalizeSide helper ────────────────────────────────

  it("normalizeSide maps long/short → buy/sell", () => {
    expect(normalizeSide("buy")).toBe("buy");
    expect(normalizeSide("sell")).toBe("sell");
    expect(normalizeSide("long")).toBe("buy");
    expect(normalizeSide("short")).toBe("sell");
    expect(normalizeSide("BUY")).toBe("buy");
    expect(normalizeSide("LONG")).toBe("buy");
  });

  it("normalizeSide warns + defaults to buy on unknown input", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(normalizeSide("garbage")).toBe("buy");
    expect(normalizeSide(undefined)).toBe("buy");
    expect(normalizeSide(null)).toBe("buy");
    expect(normalizeSide("")).toBe("buy");
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  // ─── QA-2026-05-23 — close result wires symbol + kind for toast ──────────

  it("closePosition → confirm threads symbol + kind into lastResult on success", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:abc", order: { id: "ord99", status: "new" } });
    useTradingStore.getState().closePosition("binance:abc", "BTC/USDT", "buy", 0.5, "main");
    await useTradingStore.getState().confirm("main");
    const r = useTradingStore.getState().lastResult;
    expect(r?.ok).toBe(true);
    expect(r?.kind).toBe("close");
    expect(r?.symbol).toBe("BTC/USDT");
  });

  it("openTicket persists accountLabel on the ticket so requestSubmit fallback works", () => {
    useTradingStore.getState().openTicket("abc", "binance:abc", "main");
    expect(useTradingStore.getState().ticket?.accountLabel).toBe("main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 1);
    // requestSubmit() with no arg falls back to the ticket's accountLabel.
    useTradingStore.getState().requestSubmit();
    expect(useTradingStore.getState().pendingConfirm?.accountLabel).toBe("main");
  });
});
