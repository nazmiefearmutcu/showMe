import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStrategyStore } from "./strategy-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [], draft: null, draftIsNew: false, dirty: false,
    loading: false, error: null, lastPreview: null,
  });
  mock.mockReset();
});

describe("strategy-store", () => {
  it("loadList populates strategies", async () => {
    mock.mockResolvedValueOnce({ records: [
      { id: "a", name: "X", description: "", timeframe: "1h",
        created_at: "", updated_at: "" }] });
    await useStrategyStore.getState().loadList();
    expect(useStrategyStore.getState().strategies).toHaveLength(1);
  });

  it("openNew initializes a blank draft", () => {
    useStrategyStore.getState().openNew();
    expect(useStrategyStore.getState().draft).not.toBeNull();
    expect(useStrategyStore.getState().draftIsNew).toBe(true);
  });

  it("setDraftField marks dirty", () => {
    useStrategyStore.getState().openNew();
    useStrategyStore.getState().setDraftField("name", "RSI-revert");
    expect(useStrategyStore.getState().draft?.name).toBe("RSI-revert");
    expect(useStrategyStore.getState().dirty).toBe(true);
  });

  it("save POSTs for new draft", async () => {
    mock.mockResolvedValueOnce({ id: "new", name: "X", created_at: "now", updated_at: "now" });
    mock.mockResolvedValueOnce({ records: [] });
    useStrategyStore.getState().openNew();
    useStrategyStore.getState().setDraftField("name", "X");
    const saved = await useStrategyStore.getState().save();
    expect(saved?.id).toBe("new");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("save PUTs for existing draft", async () => {
    useStrategyStore.setState({
      draft: { id: "abc", name: "Old" } as never, draftIsNew: false, dirty: true,
    });
    mock.mockResolvedValueOnce({ id: "abc", name: "Old", created_at: "x", updated_at: "y" });
    mock.mockResolvedValueOnce({ records: [] });
    const saved = await useStrategyStore.getState().save();
    expect(saved?.id).toBe("abc");
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });

  it("preview returns events", async () => {
    mock.mockResolvedValueOnce({
      strategy_id: "abc", symbol: "BTC/USDT", timeframe: "1h", bars: 200,
      events: [{ bar_index: 5, bar_time: "t", kind: "entry", price: 100, details: {} }],
      source: "synthetic_random_walk",
    });
    const r = await useStrategyStore.getState().preview("abc");
    expect(r?.events.length).toBe(1);
    expect(useStrategyStore.getState().lastPreview?.events[0].kind).toBe("entry");
  });

  it("remove clears the draft when matching id", async () => {
    useStrategyStore.setState({
      draft: { id: "abc" } as never, draftIsNew: false,
    });
    mock.mockResolvedValueOnce({});
    mock.mockResolvedValueOnce({ records: [] });
    await useStrategyStore.getState().remove("abc");
    expect(useStrategyStore.getState().draft).toBeNull();
  });
});
