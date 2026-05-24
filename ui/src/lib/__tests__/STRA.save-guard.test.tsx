/**
 * Round 24 CRITICAL 2 — STRA save concurrent-guard regression.
 *
 * The strategy editor's "Kaydet" button used to fire two POST /api/strategies
 * calls on a hardware double-click, producing duplicate rows with skewed
 * timestamps. The `if (get().saving) return null` guard in strategy-store.save()
 * is the canonical seal; this test pins that behaviour so a future "let's
 * simplify the store" refactor can't silently remove it.
 *
 * Covers:
 *  - Double save() while one is in flight → ONE POST.
 *  - Double save() for an existing draft → ONE PUT.
 *  - preview() guard prevents concurrent preview compute.
 *  - remove() guard prevents concurrent DELETE.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useStrategyStore } from "@/lib/strategy-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useStrategyStore.setState({
    strategies: [],
    draft: null,
    draftIsNew: false,
    dirty: false,
    loading: false,
    saving: false,
    previewing: false,
    removing: false,
    error: null,
    lastPreview: null,
  });
  mock.mockReset();
});

describe("STRA save-guard — Round 24 CRITICAL 2", () => {
  it("two parallel save() calls fire ONE POST", async () => {
    let resolveSave!: (v: unknown) => void;
    // First save() — slow POST.
    mock.mockReturnValueOnce(new Promise((res) => { resolveSave = res; }));
    // Subsequent loadList() — quick mock.
    mock.mockResolvedValueOnce({ records: [] });

    useStrategyStore.getState().openNew();
    useStrategyStore.getState().setDraftField("name", "RSI v1");

    const p1 = useStrategyStore.getState().save();
    const p2 = useStrategyStore.getState().save();

    // p2 must short-circuit immediately (returns null) without queueing a
    // second POST.
    expect(await p2).toBeNull();

    resolveSave({ id: "s-1", name: "RSI v1", created_at: "x", updated_at: "y" });
    const r1 = await p1;
    expect(r1?.id).toBe("s-1");

    // Should be exactly TWO calls: 1 POST + 1 loadList. NOT 3 (no second POST).
    expect(mock).toHaveBeenCalledTimes(2);
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("two parallel save() calls on EXISTING draft fire ONE PUT", async () => {
    let resolveSave!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolveSave = res; }));
    mock.mockResolvedValueOnce({ records: [] });

    useStrategyStore.setState({
      draft: {
        id: "s-existing", name: "Old", description: "", version: 1,
        asset_filter: {}, timeframe: "1h", indicators: [],
        entry_rules: [], entry_logic: "all", exit_rules: [], exit_logic: "any",
        position: { side: "long", sizing_kind: "fixed_quote", sizing_value: 100 },
        created_at: "x", updated_at: "y",
      } as never,
      draftIsNew: false,
      dirty: true,
    });

    const p1 = useStrategyStore.getState().save();
    const p2 = useStrategyStore.getState().save();
    expect(await p2).toBeNull();

    resolveSave({ id: "s-existing", name: "Old", created_at: "x", updated_at: "z" });
    await p1;

    // 1 PUT + 1 loadList = 2 calls total.
    expect(mock).toHaveBeenCalledTimes(2);
    expect((mock.mock.calls[0][1] as RequestInit).method).toBe("PUT");
  });

  it("saving flag flips back to false after error", async () => {
    mock.mockRejectedValueOnce(new Error("422 Pydantic"));
    useStrategyStore.getState().openNew();
    useStrategyStore.getState().setDraftField("name", "X");

    await useStrategyStore.getState().save();
    expect(useStrategyStore.getState().saving).toBe(false);
    expect(useStrategyStore.getState().error).toMatch(/Pydantic/);
  });

  it("preview() guard prevents concurrent compute", async () => {
    let resolvePreview!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolvePreview = res; }));

    const p1 = useStrategyStore.getState().preview("s-1");
    const p2 = useStrategyStore.getState().preview("s-1");
    expect(await p2).toBeNull();

    resolvePreview({
      strategy_id: "s-1", symbol: "BTC/USDT", timeframe: "1h",
      bars: 100, events: [], source: "test",
    });
    const r1 = await p1;
    expect(r1?.strategy_id).toBe("s-1");
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("previewing flag flips back to false after error", async () => {
    mock.mockRejectedValueOnce(new Error("500"));
    await useStrategyStore.getState().preview("s-1");
    expect(useStrategyStore.getState().previewing).toBe(false);
  });

  it("remove() concurrent-guard prevents double DELETE", async () => {
    // dependents endpoint + slow DELETE.
    let resolveDelete!: (v: unknown) => void;
    mock.mockResolvedValueOnce({ bot_count: 0, bot_ids: [] });
    mock.mockReturnValueOnce(new Promise((res) => { resolveDelete = res; }));
    mock.mockResolvedValueOnce({ records: [] }); // loadList after

    const p1 = useStrategyStore.getState().remove("s-1");
    const p2 = useStrategyStore.getState().remove("s-1");
    // p2 short-circuits because removing=true.
    expect(await p2).toBe(false);

    resolveDelete(undefined);
    expect(await p1).toBe(true);

    // 1 dependents lookup + 1 DELETE + 1 loadList = 3 (NOT 4 — no 2nd DELETE).
    expect(mock).toHaveBeenCalledTimes(3);
  });
});
