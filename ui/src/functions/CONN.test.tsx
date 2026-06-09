import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONNPane, resolveDeletePlan } from "./CONN";
import { useExchangeStore } from "@/lib/exchange-store";

const ORIGINAL_FETCH = global.fetch;

beforeEach(() => {
  useExchangeStore.setState({
    catalog: [
      { id: "binance", display_name: "Binance", aliases: ["binance.com"],
        asset_classes: ["spot", "futures"], regions: ["global"],
        adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [],
        capabilities: { fetch_balance: true }, ccxt_id: "binance", notes: "" },
      { id: "kraken", display_name: "Kraken", aliases: [],
        asset_classes: ["spot"], regions: ["us", "eu"],
        adapter: "ccxt", requires: ["api_key", "api_secret"], optional: [],
        capabilities: { fetch_balance: true }, ccxt_id: "kraken", notes: "" },
      { id: "okx", display_name: "OKX", aliases: [],
        asset_classes: ["spot", "futures"], regions: ["global"],
        adapter: "ccxt", requires: ["api_key", "api_secret", "passphrase"],
        optional: [], capabilities: { fetch_balance: true }, ccxt_id: "okx", notes: "" },
    ],
    credentials: [],
    selectedExchangeId: null,
    catalogLoading: false,
    credentialsLoading: false,
    error: null,
  });
});

afterEach(() => {
  global.fetch = ORIGINAL_FETCH;
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

/** Mount CONN, select Binance, and seed one credential for delete tests. */
function renderWithCredential() {
  useExchangeStore.setState({
    credentials: [{
      id: "abc", exchange_id: "binance", account_label: "main",
      permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
    }],
    selectedExchangeId: "binance",
  });
  return render(<CONNPane />);
}

describe("CONN pane", () => {
  it("renders the exchange list", () => {
    render(<CONNPane />);
    expect(screen.getByText("Binance")).toBeInTheDocument();
    expect(screen.getByText("Kraken")).toBeInTheDocument();
    expect(screen.getByText("OKX")).toBeInTheDocument();
  });

  it("search filters the list", () => {
    render(<CONNPane />);
    fireEvent.change(screen.getByPlaceholderText(/borsa ara/i), {
      target: { value: "krak" },
    });
    expect(screen.queryByText("Binance")).toBeNull();
    expect(screen.getByText("Kraken")).toBeInTheDocument();
  });

  it("region chip narrows results", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByRole("button", { name: /us$/i }));
    expect(screen.queryByText("Binance")).toBeNull();   // global, not us
    expect(screen.getByText("Kraken")).toBeInTheDocument();
  });

  it("selecting OKX reveals passphrase input", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("OKX"));
    // scope to <input> — secret fields now also expose a show/hide toggle
    // button whose aria-label contains the field name (F1).
    expect(screen.getByLabelText(/api_key/i, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/api_secret/i, { selector: "input" })).toBeInTheDocument();
    expect(screen.getByLabelText(/passphrase/i, { selector: "input" })).toBeInTheDocument();
  });

  it("read-only is the default; trade toggle shows red warning copy", () => {
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    const tradeToggle = screen.getByRole("checkbox", { name: /işlem/i });
    expect(tradeToggle).not.toBeChecked();
    fireEvent.click(tradeToggle);
    expect(screen.getByText(/dikkat/i)).toBeInTheDocument();
  });

  it("submitting a form calls saveCredential", async () => {
    const save = vi.spyOn(useExchangeStore.getState(), "saveCredential")
      .mockResolvedValue(true);
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    fireEvent.change(screen.getByLabelText(/account label/i), { target: { value: "main" } });
    fireEvent.change(screen.getByLabelText(/api_key/i, { selector: "input" }), { target: { value: "k" } });
    fireEvent.change(screen.getByLabelText(/api_secret/i, { selector: "input" }), { target: { value: "s" } });
    fireEvent.click(screen.getByRole("button", { name: /bağlan/i }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    const call = save.mock.calls[0][0];
    expect(call.exchange_id).toBe("binance");
    expect(call.secrets).toEqual({ api_key: "k", api_secret: "s" });
    expect(call.permissions).toEqual(["read"]);
  });

  it("Test button calls testCredential exactly once per click", async () => {
    useExchangeStore.setState({
      catalog: useExchangeStore.getState().catalog,
      credentials: [{
        id: "abc", exchange_id: "binance", account_label: "main",
        permissions: ["read"], created_at: "2026-05-21T10:00:00Z",
      }],
    });
    const testSpy = vi.spyOn(useExchangeStore.getState(), "testCredential")
      .mockResolvedValue({ ok: true });
    render(<CONNPane />);
    fireEvent.click(screen.getByText("Binance"));
    fireEvent.click(screen.getByRole("button", { name: /^test$/i }));
    await waitFor(() => expect(testSpy).toHaveBeenCalledTimes(1));
    expect(testSpy).toHaveBeenCalledWith("abc");
  });

  // ─── resolveDeletePlan unit (C9 force/cascade semantics preserved) ──────
  // P2-1 — resolveDeletePlan now takes the PRE-FETCHED dependents (no second
  // network call); the force/cascade semantics are unchanged.
  it("resolveDeletePlan: bot count >0 → force=true + count copy", () => {
    const plan = resolveDeletePlan("main", {
      credential_id: "abc", bot_count: 3, bot_ids: ["b1", "b2", "b3"],
    });
    expect(plan.title).toMatch(/3 bot/);
    expect(plan.body).toMatch(/3 bota bağlı/);
    expect(plan.force).toBe(true);
  });

  it("resolveDeletePlan: zero dependents → force=false", () => {
    const plan = resolveDeletePlan("main", {
      credential_id: "abc", bot_count: 0, bot_ids: [],
    });
    expect(plan.force).toBe(false);
  });

  it("resolveDeletePlan: null deps (lookup failed) → force=true + doğrulanamadı", () => {
    const plan = resolveDeletePlan("main", null);
    expect(plan.title).toMatch(/doğrulanamadı/i);
    expect(plan.force).toBe(true);
  });

  // ─── F5 — in-app ConfirmDialog drives the delete ───────────────────────
  it("Sil → in-app dialog shows bot count, confirm deletes with force=true", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 3, bot_ids: ["b1", "b2", "b3"] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    renderWithCredential();
    fireEvent.click(screen.getByTestId("conn-sil-abc"));

    // Dialog appears with the bot-count copy (no native confirm).
    await waitFor(() =>
      expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument(),
    );
    expect(screen.getByText(/3 bot etkilenecek/)).toBeInTheDocument();
    expect(screen.getByText(/3 bota bağlı/)).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: true }));
  });

  it("Sil with zero dependents confirms with force=false", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 0, bot_ids: [] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    renderWithCredential();
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    await waitFor(() =>
      expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    await waitFor(() => expect(del).toHaveBeenCalledWith("abc", { force: false }));
  });

  it("cancelling the in-app dialog aborts the delete", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 2, bot_ids: ["b1", "b2"] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    renderWithCredential();
    fireEvent.click(screen.getByTestId("conn-sil-abc"));
    await waitFor(() =>
      expect(screen.getByTestId("confirm-dialog-body")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("confirm-dialog-cancel"));
    await waitFor(() =>
      expect(screen.queryByTestId("confirm-dialog-body")).toBeNull(),
    );
    expect(del).not.toHaveBeenCalled();
  });

  it("switching exchange clears the form (no state leak)", () => {
    render(<CONNPane />);
    // Pick Binance, type into account_label
    fireEvent.click(screen.getByText("Binance"));
    const labelInput1 = screen.getByLabelText(/account label/i) as HTMLInputElement;
    fireEvent.change(labelInput1, { target: { value: "binance-account" } });
    expect(labelInput1.value).toBe("binance-account");

    // Switch to OKX
    fireEvent.click(screen.getByText("OKX"));
    const labelInput2 = screen.getByLabelText(/account label/i) as HTMLInputElement;
    // New form should start empty, not carry over "binance-account"
    expect(labelInput2.value).toBe("");
  });
});
