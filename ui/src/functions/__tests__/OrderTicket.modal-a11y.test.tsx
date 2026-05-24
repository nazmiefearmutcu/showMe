/**
 * Round 24 HIGH 6 — OrderTicket confirm modal a11y regression.
 *
 * Audit flagged: no Escape handler, no backdrop click dismiss. The modal
 * was effectively a "click İptal or refresh the app" trap, which on a
 * trading screen is the worst possible UX.
 *
 * This test exercises:
 *  - Esc cancels the modal (when not submitting).
 *  - Backdrop click cancels the modal.
 *  - Clicks inside the modal body do NOT dismiss.
 *  - While `submitting=true` the Esc + backdrop are no-ops so the user
 *    can't half-close mid-POST.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConfirmModal } from "@/functions/OrderTicket";
import { useTradingStore } from "@/lib/trading-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("@/lib/portfolio-store", () => ({
  usePortfolioStore: { getState: () => ({ loadPortfolio: vi.fn() }) },
}));

beforeEach(() => {
  useTradingStore.setState({
    ticket: null,
    pendingConfirm: {
      kind: "submit",
      brokerName: "binance:cred-1",
      accountLabel: "main",
      payload: { broker: "binance:cred-1", symbol: "BTC/USDT", quantity: 0.01 },
    },
    submitting: false,
    lastResult: null,
  });
});
afterEach(() => cleanup());

describe("OrderTicket modal a11y — Round 24 HIGH 6", () => {
  it("Esc key dismisses pendingConfirm (when not submitting)", () => {
    render(<ConfirmModal accountLabel="main" />);
    expect(useTradingStore.getState().pendingConfirm).not.toBeNull();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useTradingStore.getState().pendingConfirm).toBeNull();
  });

  it("Esc key does NOT dismiss while submitting (POST in flight)", () => {
    useTradingStore.setState({ submitting: true });
    render(<ConfirmModal accountLabel="main" />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useTradingStore.getState().pendingConfirm).not.toBeNull();
  });

  it("backdrop click dismisses pendingConfirm", () => {
    render(<ConfirmModal accountLabel="main" />);
    const backdrop = screen.getByTestId("confirm-modal-backdrop");
    fireEvent.click(backdrop);
    expect(useTradingStore.getState().pendingConfirm).toBeNull();
  });

  it("click inside modal body does NOT dismiss", () => {
    render(<ConfirmModal accountLabel="main" />);
    const body = screen.getByTestId("confirm-modal-body");
    fireEvent.click(body);
    expect(useTradingStore.getState().pendingConfirm).not.toBeNull();
  });

  it("backdrop click is no-op while submitting", () => {
    useTradingStore.setState({ submitting: true });
    render(<ConfirmModal accountLabel="main" />);
    const backdrop = screen.getByTestId("confirm-modal-backdrop");
    fireEvent.click(backdrop);
    expect(useTradingStore.getState().pendingConfirm).not.toBeNull();
  });

  it("İptal button is disabled while submitting", () => {
    useTradingStore.setState({ submitting: true });
    render(<ConfirmModal accountLabel="main" />);
    const cancelBtn = screen.getByTestId("confirm-modal-cancel-btn") as HTMLButtonElement;
    expect(cancelBtn.disabled).toBe(true);
  });

  it("typed input is disabled while submitting", () => {
    useTradingStore.setState({ submitting: true });
    render(<ConfirmModal accountLabel="main" />);
    const input = screen.getByTestId("confirm-modal-typed-input") as HTMLInputElement;
    expect(input.disabled).toBe(true);
  });
});
