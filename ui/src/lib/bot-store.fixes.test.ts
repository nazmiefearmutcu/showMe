/**
 * Faz 3 — bot-store regression fixes.
 *
 *   B-C3 — save() includes confirm_account_label on shadow→live PUT
 *   B-C4 — concurrent-save guard via `saving` flag
 *   H-2  — remove/enable/disable reset stale error
 *   H-3  — remove() flips loading
 *   H-14 — PUT body strips signal_log + last_processed_event
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBotStore } from "./bot-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useBotStore.setState({
    bots: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, saving: false, error: null,
  });
  mock.mockReset();
});

describe("bot-store fixes", () => {
  // ─── B-C3 ────────────────────────────────────────────────────────────
  it("save_put_threads_confirm_account_label", async () => {
    useBotStore.setState({
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "live", enabled: false,
        signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
      draftIsNew: false, dirty: true,
    });
    mock.mockResolvedValueOnce({ id: "b1", mode: "live" } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().save("main");
    expect(mock).toHaveBeenCalled();
    const putCall = mock.mock.calls[0];
    expect((putCall[1] as RequestInit).method).toBe("PUT");
    const body = JSON.parse(String((putCall[1] as RequestInit).body));
    expect(body.confirm_account_label).toBe("main");
  });

  it("save_put_omits_confirm_account_label_when_undefined", async () => {
    useBotStore.setState({
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false,
        signal_log: [], last_processed_event: null,
        created_at: "", updated_at: "",
      },
      draftIsNew: false, dirty: true,
    });
    mock.mockResolvedValueOnce({ id: "b1" } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().save();
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.confirm_account_label).toBeUndefined();
  });

  // ─── B-C4 ────────────────────────────────────────────────────────────
  it("save_concurrent_guard_single_post", async () => {
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    useBotStore.getState().setDraftField("strategy_id", "s1");
    useBotStore.getState().setDraftField("credential_id", "c1");
    useBotStore.getState().setDraftField("exchange_id", "binance");

    let resolvePost: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolvePost = res; });
    mock.mockReturnValueOnce(pending);

    const first = useBotStore.getState().save();
    const second = useBotStore.getState().save();
    const third = useBotStore.getState().save();

    // Only one POST should have been made — others bail on the saving guard.
    expect(mock).toHaveBeenCalledTimes(1);

    mock.mockResolvedValueOnce({ records: [] });
    resolvePost({
      id: "new", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
      symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
      tick_interval_seconds: 60, signal_log: [], last_processed_event: null,
      created_at: "", updated_at: "",
    });
    await Promise.all([first, second, third]);
    expect(await second).toBeNull();
    expect(await third).toBeNull();
  });

  it("save_saving_flag_lifecycle", async () => {
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    useBotStore.getState().setDraftField("strategy_id", "s1");
    useBotStore.getState().setDraftField("credential_id", "c1");

    let resolvePost: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolvePost = res; });
    mock.mockReturnValueOnce(pending);
    mock.mockResolvedValueOnce({ records: [] });

    const p = useBotStore.getState().save();
    expect(useBotStore.getState().saving).toBe(true);
    resolvePost({
      id: "new", strategy_id: "s1", credential_id: "c1", exchange_id: "",
      symbol: "BTC/USDT", timeframe: "1h", mode: "shadow", enabled: false,
      tick_interval_seconds: 60, signal_log: [], last_processed_event: null,
      created_at: "", updated_at: "",
    });
    await p;
    expect(useBotStore.getState().saving).toBe(false);
  });

  it("save_saving_resets_on_error", async () => {
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    mock.mockRejectedValueOnce(new Error("boom"));
    await useBotStore.getState().save();
    expect(useBotStore.getState().saving).toBe(false);
    expect(useBotStore.getState().error).toBe("boom");
  });

  // ─── H-2 ────────────────────────────────────────────────────────────
  it("remove_resets_error_at_entry", async () => {
    useBotStore.setState({ error: "stale failure" });
    mock.mockResolvedValueOnce({});
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().remove("abc");
    expect(useBotStore.getState().error).toBeNull();
  });

  it("enable_resets_error_at_entry", async () => {
    useBotStore.setState({ error: "stale failure" });
    mock.mockResolvedValueOnce({ id: "abc", enabled: true } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().enable("abc", "main");
    expect(useBotStore.getState().error).toBeNull();
  });

  it("disable_resets_error_at_entry", async () => {
    useBotStore.setState({ error: "stale failure" });
    mock.mockResolvedValueOnce({ id: "abc", enabled: false } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().disable("abc");
    expect(useBotStore.getState().error).toBeNull();
  });

  // ─── H-3 ────────────────────────────────────────────────────────────
  it("remove_flips_loading_flag", async () => {
    let resolveDelete: (v: unknown) => void = () => {};
    const pending = new Promise((res) => { resolveDelete = res; });
    mock.mockReturnValueOnce(pending);
    mock.mockResolvedValueOnce({ records: [] });
    const p = useBotStore.getState().remove("abc");
    expect(useBotStore.getState().loading).toBe(true);
    resolveDelete({});
    await p;
    expect(useBotStore.getState().loading).toBe(false);
  });

  it("remove_resets_loading_on_error", async () => {
    mock.mockRejectedValueOnce(new Error("nope"));
    await useBotStore.getState().remove("abc");
    expect(useBotStore.getState().loading).toBe(false);
    expect(useBotStore.getState().error).toBe("nope");
  });

  // ─── H-14 ────────────────────────────────────────────────────────────
  it("save_put_strips_signal_log_and_last_processed_event", async () => {
    useBotStore.setState({
      draft: {
        id: "b1", strategy_id: "s1", credential_id: "c1", exchange_id: "binance",
        symbol: "BTC/USDT", timeframe: "1h", tick_interval_seconds: 60,
        mode: "shadow", enabled: false,
        signal_log: [{ bar_index: 1, bar_time: "x", kind: "entry",
                       price: 1, action: "shadow" }],
        last_processed_event: { bar_index: 1, bar_time: "x", kind: "entry",
                                price: 1, action: "shadow" },
        created_at: "", updated_at: "",
      },
      draftIsNew: false, dirty: true,
    });
    mock.mockResolvedValueOnce({ id: "b1" } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().save();
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.signal_log).toBeUndefined();
    expect(body.last_processed_event).toBeUndefined();
    // Other fields preserved.
    expect(body.symbol).toBe("BTC/USDT");
    expect(body.strategy_id).toBe("s1");
  });

  it("save_post_also_strips_signal_log_and_last_processed_event", async () => {
    useBotStore.getState().openNew();
    useBotStore.getState().setDraftField("symbol", "BTC/USDT");
    useBotStore.getState().setDraftField("strategy_id", "s1");
    useBotStore.getState().setDraftField("credential_id", "c1");
    mock.mockResolvedValueOnce({ id: "new" } as never);
    mock.mockResolvedValueOnce({ records: [] });
    await useBotStore.getState().save();
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.signal_log).toBeUndefined();
    expect(body.last_processed_event).toBeUndefined();
  });
});
