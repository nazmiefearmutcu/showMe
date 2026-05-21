import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePortfolioStore } from "./portfolio-store";

vi.mock("./sidecar", () => ({
  sidecarFetch: vi.fn(),
}));

import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  usePortfolioStore.setState({
    groups: [], totals: {}, loading: false, error: null, lastFetchedAt: null,
    selectedCredentialIds: null, includeOrders: false,
  });
  mock.mockReset();
});

describe("portfolio-store", () => {
  it("loadPortfolio populates groups + totals", async () => {
    mock.mockResolvedValueOnce({
      as_of: "2026-05-22T10:00:00Z",
      groups: [{ credential_id: "abc", exchange_id: "binance", account_label: "main",
                 permissions: ["read"], account: { equity: 100, currency: "USDT" },
                 positions: [], orders: [], error: null }],
      totals: { equity_by_currency: { USDT: 100 }, stable_usd_equivalent: 100 },
    });
    await usePortfolioStore.getState().loadPortfolio();
    expect(usePortfolioStore.getState().groups).toHaveLength(1);
    expect(usePortfolioStore.getState().totals.stable_usd_equivalent).toBe(100);
    expect(usePortfolioStore.getState().lastFetchedAt).not.toBeNull();
  });

  it("loadPortfolio passes credential_ids filter", async () => {
    mock.mockResolvedValueOnce({ as_of: "now", groups: [], totals: {} });
    usePortfolioStore.setState({ selectedCredentialIds: ["abc", "def"] });
    await usePortfolioStore.getState().loadPortfolio();
    expect(mock.mock.calls[0][0]).toContain("credential_ids=abc%2Cdef");
  });

  it("setIncludeOrders flips state + triggers reload", async () => {
    mock.mockResolvedValue({ as_of: "now", groups: [], totals: {} });
    await usePortfolioStore.getState().setIncludeOrders(true);
    expect(usePortfolioStore.getState().includeOrders).toBe(true);
    expect(mock.mock.calls[0][0]).toContain("include_orders=true");
  });

  it("loadPortfolio surfaces backend errors", async () => {
    mock.mockRejectedValueOnce(new Error("503 boom"));
    await usePortfolioStore.getState().loadPortfolio();
    expect(usePortfolioStore.getState().error).toContain("503");
    expect(usePortfolioStore.getState().loading).toBe(false);
  });
});
