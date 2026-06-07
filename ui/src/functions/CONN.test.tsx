import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONNPane, handleCredentialDelete } from "./CONN";
import { useExchangeStore } from "@/lib/exchange-store";
// confirmAction is imported at module init by CONN; stub it so the spec can
// drive the user's accept/decline branch deterministically.
vi.mock("@/lib/confirm", () => ({
  confirmAction: vi.fn(async () => true),
}));
import { confirmAction } from "@/lib/confirm";

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
    expect(screen.getByLabelText(/api_key/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/api_secret/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/passphrase/i)).toBeInTheDocument();
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
    fireEvent.change(screen.getByLabelText(/api_key/i), { target: { value: "k" } });
    fireEvent.change(screen.getByLabelText(/api_secret/i), { target: { value: "s" } });
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

  // ─── C9 (FIX_CONTRACT) — delete confirm with bot count ────────────────
  it("test_credential_delete_shows_dependent_bot_warning", async () => {
    const dependents = vi
      .spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 3, bot_ids: ["b1", "b2", "b3"] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    const ok = await handleCredentialDelete("abc", "main");

    expect(dependents).toHaveBeenCalledWith("abc");
    expect(confirmAction).toHaveBeenCalledTimes(1);
    const args = (confirmAction as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(args.title).toMatch(/3 bot/);
    expect(args.body).toMatch(/3 bota bağlı/);
    expect(args.destructive).toBe(true);
    // User accepted → cascade-disable via force=true.
    expect(del).toHaveBeenCalledWith("abc", { force: true });
    expect(ok).toBe(true);
  });

  it("delete with zero dependents does NOT force=true", async () => {
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 0, bot_ids: [] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    await handleCredentialDelete("abc", "main");

    expect(del).toHaveBeenCalledWith("abc", { force: false });
  });

  it("declining the confirm aborts the delete", async () => {
    (confirmAction as ReturnType<typeof vi.fn>).mockResolvedValueOnce(false);
    vi.spyOn(useExchangeStore.getState(), "dependentBots")
      .mockResolvedValue({ credential_id: "abc", bot_count: 2, bot_ids: [] });
    const del = vi
      .spyOn(useExchangeStore.getState(), "deleteCredential")
      .mockResolvedValue(true);

    const ok = await handleCredentialDelete("abc", "main");

    expect(ok).toBe(false);
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
