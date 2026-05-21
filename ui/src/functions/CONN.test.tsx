import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONNPane } from "./CONN";
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
});
