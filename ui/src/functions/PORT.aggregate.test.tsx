import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PORTPane } from "./PORT";
import { usePortfolioStore } from "@/lib/portfolio-store";
import { useExchangeStore } from "@/lib/exchange-store";

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  useExchangeStore.setState({
    catalog: [], credentials: [], selectedExchangeId: null,
    catalogLoading: false, credentialsLoading: false, error: null,
  });
});

describe("PORT aggregate header", () => {
  it("shows CTA when zero connected credentials", () => {
    render(<PORTPane code="PORT" />);
    // CTA wraps a <strong>Connect Exchange</strong>, so the regex resolves on
    // both the parent <div> and the <strong> — accept either via getAllByText.
    expect(screen.getAllByText(/connect.*exchange|borsa.*ekle|conn/i).length).toBeGreaterThan(0);
  });

  it("renders aggregate header when groups loaded", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-22T10:00:00Z",
      }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false,
      error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"],
        account: { cash: 100, equity: 100, buying_power: 100, currency: "USDT" },
        positions: [], orders: [], error: null,
      }],
      totals: { equity_by_currency: { USDT: 100 }, stable_usd_equivalent: 100 },
      lastFetchedAt: "2026-05-22T10:00:00Z",
      loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    // SourceFilter chip + CredentialGroup heading both label as "binance:main".
    expect(screen.getAllByText(/binance.*main|main.*binance|binance:main/i).length).toBeGreaterThan(0);
  });

  it("renders error group", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{
        id: "bad", exchange_id: "kraken", account_label: "x",
        permissions: ["read"], created_at: "2026-05-22T10:00:00Z",
      }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false,
      error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "bad", exchange_id: "kraken", account_label: "x",
        permissions: ["read"], account: null, positions: [], orders: [],
        error: "RuntimeError: rate limit",
      }],
      totals: {}, lastFetchedAt: null, loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    expect(screen.getByText(/rate limit/i)).toBeInTheDocument();
  });
});
