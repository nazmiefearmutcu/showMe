import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PORTPane, isStableUsd } from "./PORT";
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

  it("renders Close buttons on positions only when permissions include trade", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{ id: "abc", exchange_id: "binance", account_label: "main",
                      permissions: ["read", "trade"], created_at: "now" }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read", "trade"],
        account: { cash: 1, equity: 1, buying_power: 1, currency: "USDT" },
        positions: [{ symbol: "BTC/USDT", side: "buy", quantity: 0.5,
                      entry_price: 60000, current_price: 61000, unrealized_pnl: 500 }],
        orders: [], error: null,
      }],
      totals: {}, lastFetchedAt: null, loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    expect(screen.getAllByRole("button", { name: /^close$/i }).length).toBeGreaterThan(0);
  });

  it("does NOT render Close buttons for read-only credentials", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{ id: "abc", exchange_id: "binance", account_label: "main",
                      permissions: ["read"], created_at: "now" }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"],
        account: { cash: 1, equity: 1, buying_power: 1, currency: "USDT" },
        positions: [{ symbol: "BTC/USDT", side: "buy", quantity: 0.5,
                      entry_price: 60000, current_price: 61000, unrealized_pnl: 500 }],
        orders: [], error: null,
      }],
      totals: {}, lastFetchedAt: null, loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    expect(screen.queryByRole("button", { name: /^close$/i })).toBeNull();
  });

  // ─── BUG #12 — non-stable currency aggregation warning ─────────────────
  it("renders non-stable currency badge for EUR balances", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{ id: "abc", exchange_id: "kraken", account_label: "eu",
                      permissions: ["read"], created_at: "now" }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
    });
    usePortfolioStore.setState({
      groups: [{
        credential_id: "abc", exchange_id: "kraken", account_label: "eu",
        permissions: ["read"],
        account: { cash: 500, equity: 500, buying_power: 500, currency: "EUR" },
        positions: [], orders: [], error: null,
      }],
      totals: { equity_by_currency: { EUR: 500 }, stable_usd_equivalent: 0 },
      lastFetchedAt: "2026-05-22T10:00:00Z",
      loading: false, error: null,
      selectedCredentialIds: null, includeOrders: false,
    });
    render(<PORTPane code="PORT" />);
    const badge = screen.getByTestId("port-non-stable-badge");
    expect(badge.textContent).toMatch(/EUR/);
    expect(badge.getAttribute("title")).toMatch(/USD'ye eklenmedi/);
  });

  it("does NOT render non-stable badge for USDT (stable)", () => {
    useExchangeStore.setState({
      catalog: [],
      credentials: [{ id: "abc", exchange_id: "binance", account_label: "main",
                      permissions: ["read"], created_at: "now" }],
      selectedExchangeId: null, catalogLoading: false, credentialsLoading: false, error: null,
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
    expect(screen.queryByTestId("port-non-stable-badge")).toBeNull();
  });

  it("isStableUsd recognises the documented allowlist", () => {
    expect(isStableUsd("USD")).toBe(true);
    expect(isStableUsd("usdt")).toBe(true);  // case-insensitive
    expect(isStableUsd("USDC")).toBe(true);
    expect(isStableUsd("DAI")).toBe(true);
    expect(isStableUsd("EUR")).toBe(false);
    expect(isStableUsd("GBP")).toBe(false);
    expect(isStableUsd("TRY")).toBe(false);
    expect(isStableUsd(undefined)).toBe(false);
    expect(isStableUsd(null)).toBe(false);
    expect(isStableUsd("")).toBe(false);
  });
});
