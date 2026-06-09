/**
 * A12 — CONN ignored the `bots_unknown` flag returned by `dependentBots()`.
 *
 * When both the dedicated and fallback dependents endpoints fail the
 * store returns `bots_unknown: true` so the user can be warned before
 * pressing through a destructive delete. Before the fix the modal still
 * said "0 bot etkilenecek", lying to the user.
 *
 * Also covers the A12 catalog-list improvements:
 *   - Duplicate display_names get an `(exchange-id)` suffix.
 *   - 2-letter initials collisions render a 3-letter id-derived tag.
 *   - Filter buttons with zero matches in the current catalog are hidden.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  CONNPane,
  collidingDisplayNames,
  collidingInitials,
  resolveDeletePlan,
} from "../CONN";
import { useExchangeStore } from "@/lib/exchange-store";

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [
      {
        id: "coinbase",
        display_name: "Coinbase Advanced",
        aliases: [],
        asset_classes: ["spot"],
        regions: ["us"],
        adapter: "ccxt",
        requires: ["api_key", "api_secret"],
        optional: [],
        capabilities: {},
        ccxt_id: "coinbase",
        notes: "",
      },
      {
        id: "coinbasepro",
        display_name: "Coinbase Advanced",
        aliases: [],
        asset_classes: ["spot"],
        regions: ["us"],
        adapter: "ccxt",
        requires: ["api_key", "api_secret"],
        optional: [],
        capabilities: {},
        ccxt_id: "coinbasepro",
        notes: "",
      },
      {
        id: "kraken",
        display_name: "Kraken",
        aliases: [],
        asset_classes: ["spot"],
        regions: ["us", "eu"],
        adapter: "ccxt",
        requires: ["api_key", "api_secret"],
        optional: [],
        capabilities: {},
        ccxt_id: "kraken",
        notes: "",
      },
    ],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

/** Mount CONN, select Coinbase Advanced, and seed one credential. */
function renderWithCredential() {
  useExchangeStore.setState({
    credentials: [{
      id: "abc", exchange_id: "coinbase", account_label: "main",
      permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
    }],
    selectedExchangeId: "coinbase",
  });
  return render(<CONNPane />);
}

describe("delete plan — A12 bots_unknown warning", () => {
  it("resolveDeletePlan: bots_unknown=true → doğrulanamadı copy + force=true", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots").mockResolvedValue({
      credential_id: "abc",
      bot_count: 0,
      bot_ids: [],
      bots_unknown: true,
    });
    const plan = await resolveDeletePlan("abc", "main");
    expect(plan.title).toMatch(/doğrulanamadı/i);
    expect(plan.body).toMatch(/doğrulanamadı/i);
    // Defensive cascade.
    expect(plan.force).toBe(true);
  });

  it("resolveDeletePlan: bots_unknown=false keeps the plain copy + force=false", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots").mockResolvedValue({
      credential_id: "abc",
      bot_count: 0,
      bot_ids: [],
      bots_unknown: false,
    });
    const plan = await resolveDeletePlan("abc", "main");
    expect(plan.title).toBe("Bağlantıyı sil");
    expect(plan.body).not.toMatch(/doğrulanamadı/i);
    expect(plan.force).toBe(false);
  });

  it("Sil → in-app dialog surfaces the 'doğrulanamadı' warning, confirm forces", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots").mockResolvedValue({
      credential_id: "abc",
      bot_count: 0,
      bot_ids: [],
      bots_unknown: true,
    });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    renderWithCredential();
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    await waitFor(() =>
      expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument(),
    );
    // Both the title and body carry the "doğrulanamadı" warning copy.
    expect(screen.getByTestId("confirm-dialog-body-text")).toHaveTextContent(/doğrulanamadı/i);

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: true }));
  });
});

describe("CONN catalog disambiguation — A12", () => {
  it("collidingDisplayNames flags duplicates only", () => {
    const colliding = collidingDisplayNames([
      { display_name: "Coinbase Advanced" } as never,
      { display_name: "Coinbase Advanced" } as never,
      { display_name: "Kraken" } as never,
    ]);
    expect(colliding.has("Coinbase Advanced")).toBe(true);
    expect(colliding.has("Kraken")).toBe(false);
  });

  it("collidingInitials groups by the 2-letter prefix", () => {
    const collide = collidingInitials([
      { id: "coinbase", display_name: "Coinbase Advanced" } as never,
      { id: "coinbasepro", display_name: "Coinbase Pro" } as never,
      { id: "kraken", display_name: "Kraken" } as never,
    ]);
    // Coinbase & Coinbase Pro both yield "CO" — both should be flagged.
    expect(collide.has("coinbase")).toBe(true);
    expect(collide.has("coinbasepro")).toBe(true);
    // Kraken's "KR" is unique.
    expect(collide.has("kraken")).toBe(false);
  });

  it("renders the (exchange-id) suffix for duplicate display_names", () => {
    render(<CONNPane />);
    // Both Coinbase Advanced rows should be tagged with their id.
    expect(screen.getByText(/Coinbase Advanced \(coinbase\)/)).toBeInTheDocument();
    expect(screen.getByText(/Coinbase Advanced \(coinbasepro\)/)).toBeInTheDocument();
    // Kraken doesn't collide → no suffix.
    expect(screen.getByText("Kraken")).toBeInTheDocument();
    expect(screen.queryByText(/Kraken \(kraken\)/)).toBeNull();
  });

  it("hides filter buttons that match zero catalog entries", () => {
    // Catalog above has only `spot` asset class — `fx`, `swap`, `options`,
    // `equity`, `futures`, `margin` should all be hidden.
    render(<CONNPane />);
    expect(screen.getByRole("button", { name: /^spot$/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^fx$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^swap$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^options$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^equity$/i })).toBeNull();
    // `asia` has no rows either.
    expect(screen.queryByRole("button", { name: /^asia$/i })).toBeNull();
    // `us` does (Coinbase + Kraken).
    expect(screen.getByRole("button", { name: /^us$/i })).toBeInTheDocument();
  });
});
