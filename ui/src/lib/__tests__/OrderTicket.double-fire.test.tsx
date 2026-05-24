/**
 * Round 24 CRITICAL 1 — OrderTicket double-fire regression.
 *
 * "REAL MONEY 2× emir" — the audit's most severe finding. A hardware
 * double-click on the confirm modal's "Gönder" button used to fire two
 * onClick handlers within ~50ms; the second handler raced React's
 * `disabled={submitting}` re-render and dispatched a duplicate
 * POST /api/broker/orders. On a live broker this means two real positions.
 *
 * This test exercises the store-level guard in `trading-store.confirm()`
 * which is the canonical seal. The button-disable and inline guard are
 * decorative belt-and-suspenders; if the store guard regresses, this
 * test must FAIL.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTradingStore } from "@/lib/trading-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("@/lib/portfolio-store", () => ({
  usePortfolioStore: { getState: () => ({ loadPortfolio: vi.fn() }) },
}));

import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useTradingStore.setState({
    ticket: null, pendingConfirm: null, submitting: false, lastResult: null,
  });
  mock.mockReset();
});

describe("OrderTicket double-fire — REAL MONEY guard", () => {
  it("rapid Promise.all confirm() fires ONE POST /api/broker/orders", async () => {
    // Slow-resolving sidecar so the second confirm() arrives while the
    // first is still in flight — exactly the race a hardware double-click
    // produces. If the guard is missing, this would fire 2 POSTs.
    let resolveFetch!: (v: unknown) => void;
    mock.mockReturnValueOnce(
      new Promise((res) => { resolveFetch = res; }),
    );

    useTradingStore.getState().openTicket("cred-1", "binance:cred-1", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit("main");

    // Fire two confirms back-to-back without awaiting — simulates the
    // double-onClick that React's batching can't catch.
    const p1 = useTradingStore.getState().confirm("main");
    const p2 = useTradingStore.getState().confirm("main");

    // p2 should resolve immediately (early-exit) because submitting=true.
    await p2;
    // p1 still in flight — resolve the underlying fetch now.
    resolveFetch({ broker: "binance:cred-1", order: { id: "o-1", status: "new" } });
    await p1;

    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock.mock.calls[0][0]).toBe("/api/broker/orders");
  });

  it("requestSubmit while submitting is a no-op (no payload overwrite)", () => {
    useTradingStore.setState({ submitting: true });
    useTradingStore.getState().openTicket("cred-1", "binance:cred-1", "main");
    useTradingStore.getState().setTicketField("symbol", "ETH/USDT");
    useTradingStore.getState().setTicketField("quantity", 1);
    useTradingStore.getState().requestSubmit("main");
    // Should NOT have moved the ticket into pendingConfirm because
    // submitting was already true.
    expect(useTradingStore.getState().pendingConfirm).toBeNull();
  });

  it("payload carries a fresh idempotency_key on each requestSubmit", () => {
    useTradingStore.getState().openTicket("cred-1", "binance:cred-1", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);

    useTradingStore.getState().requestSubmit("main");
    const key1 = useTradingStore.getState().pendingConfirm?.payload?.idempotency_key;
    expect(typeof key1).toBe("string");
    expect((key1 as string).length).toBeGreaterThan(8);

    useTradingStore.getState().dismissConfirm();
    useTradingStore.getState().requestSubmit("main");
    const key2 = useTradingStore.getState().pendingConfirm?.payload?.idempotency_key;
    expect(key2).not.toBe(key1);
  });

  it("confirm POST includes Idempotency-Key header AND payload field", async () => {
    mock.mockResolvedValueOnce({ broker: "binance:cred-1", order: { id: "o-1", status: "new" } });
    useTradingStore.getState().openTicket("cred-1", "binance:cred-1", "main");
    useTradingStore.getState().setTicketField("symbol", "BTC/USDT");
    useTradingStore.getState().setTicketField("quantity", 0.01);
    useTradingStore.getState().requestSubmit("main");
    await useTradingStore.getState().confirm("main");

    const [, init] = mock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(headers["Idempotency-Key"]).toMatch(/.+/);
    const body = JSON.parse(String((init as RequestInit).body));
    expect(typeof body.idempotency_key).toBe("string");
    // The header and payload field MUST be the same key — backend may
    // dedupe on either, but they must agree.
    expect(body.idempotency_key).toBe(headers["Idempotency-Key"]);
  });

  it("closePosition carries idempotency_key + cancel path uses header", async () => {
    mock.mockResolvedValueOnce(undefined);
    useTradingStore.getState().closePosition(
      "binance:cred-1", "BTC/USDT", "buy", 0.01, "main",
    );
    const pc = useTradingStore.getState().pendingConfirm;
    expect(typeof pc?.payload?.idempotency_key).toBe("string");

    await useTradingStore.getState().confirm("main");
    const [, init] = mock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBeTruthy();
  });

  it("cancel DELETE carries Idempotency-Key header", async () => {
    mock.mockResolvedValueOnce(undefined);
    useTradingStore.getState().requestCancel("binance:cred-1", "ord-7", "main", "BTC/USDT");
    await useTradingStore.getState().confirm("main");
    const [, init] = mock.mock.calls[0];
    expect((init as RequestInit).method).toBe("DELETE");
    const headers = (init as RequestInit).headers as Record<string, string> | undefined;
    expect(headers?.["Idempotency-Key"]).toBeTruthy();
  });
});
