import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBotStore } from "./bot-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useBotStore.setState({
    bots: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, error: null,
  });
  mock.mockReset();
});

describe("bot-store", () => {
  it("loadList populates bots", async () => {
    mock.mockResolvedValueOnce({ records: [
      { id: "a", strategy_id: "s", credential_id: "c", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
        created_at: "", updated_at: "" }] });
    await useBotStore.getState().loadList();
    expect(useBotStore.getState().bots).toHaveLength(1);
  });

  it("openNew initializes a blank draft", () => {
    useBotStore.getState().openNew();
    expect(useBotStore.getState().draft).not.toBeNull();
    expect(useBotStore.getState().draftIsNew).toBe(true);
    expect(useBotStore.getState().draft?.mode).toBe("shadow");
  });

  it("setDraftField marks dirty", () => {
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    expect(useBotStore.getState().draft?.symbol).toBe("BTC/USDT");
    expect(useBotStore.getState().dirty).toBe(true);
  });

  it("save POSTs for new", async () => {
    mock.mockResolvedValueOnce({ id: "new", strategy_id: "s", credential_id: "c",
      exchange_id: "binance", symbol: "BTC/USDT", timeframe: "1h", mode: "shadow",
      enabled: false, tick_interval_seconds: 60, signal_log: [], last_processed_event: null,
      created_at: "", updated_at: "" });
    mock.mockResolvedValueOnce({ records: [] });
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    const saved = await useBotStore.getState().save();
    expect(saved?.id).toBe("new");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("enable POSTs to /enable with confirm_account_label", async () => {
    mock.mockResolvedValueOnce({ id: "abc", enabled: true } as unknown);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().enable("abc", "main");
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.confirm_account_label).toBe("main");
  });

  it("disable POSTs to /disable", async () => {
    mock.mockResolvedValueOnce({ id: "abc", enabled: false } as unknown);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().disable("abc");
    expect(mock.mock.calls[0][0]).toContain("/disable");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("remove clears matching draft", async () => {
    useBotStore.setState({ draft: { id: "abc" } as never, draftIsNew: false });
    mock.mockResolvedValueOnce({});
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().remove("abc");
    expect(useBotStore.getState().draft).toBeNull();
  });
});
