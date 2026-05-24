/**
 * Round 24 CRITICAL 4 — TMPL instantiate concurrent-guard regression.
 *
 * The template "Oluştur" button used to fire two POST /api/templates/{id}/instantiate
 * calls on a double-click, persisting two duplicate strategies that then
 * appeared as duplicate dropdown entries in BOT + STRA panes.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTemplateStore } from "@/lib/template-store";

vi.mock("@/lib/sidecar", () => ({ sidecarFetch: vi.fn() }));
vi.mock("@/lib/strategy-store", () => ({
  useStrategyStore: { getState: () => ({ loadList: vi.fn() }) },
}));

import { sidecarFetch } from "@/lib/sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useTemplateStore.setState({
    entries: [],
    selectedId: null,
    loading: false,
    instantiating: false,
    error: null,
  });
  mock.mockReset();
});

describe("TMPL instantiate-guard — Round 24 CRITICAL 4", () => {
  it("two parallel instantiate() calls fire ONE POST", async () => {
    let resolvePost!: (v: unknown) => void;
    mock.mockReturnValueOnce(new Promise((res) => { resolvePost = res; }));

    const p1 = useTemplateStore.getState().instantiate("rsi-mean-revert", "My RSI", "BTC/USDT");
    const p2 = useTemplateStore.getState().instantiate("rsi-mean-revert", "My RSI", "BTC/USDT");
    expect(await p2).toBeNull();

    resolvePost({
      template_id: "rsi-mean-revert",
      strategy: { id: "s-1", name: "My RSI", created_at: "x", updated_at: "x" },
    });
    const r1 = await p1;
    expect(r1?.strategy?.id).toBe("s-1");
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("instantiating flag flips back to false after error", async () => {
    mock.mockRejectedValueOnce(new Error("422 template_not_found"));
    const r = await useTemplateStore.getState().instantiate("bogus", "X");
    expect(r).toBeNull();
    expect(useTemplateStore.getState().instantiating).toBe(false);
    expect(useTemplateStore.getState().error).toMatch(/template_not_found/);
  });

  it("after success the guard releases (next instantiate works)", async () => {
    mock.mockResolvedValueOnce({
      template_id: "t-1",
      strategy: { id: "s-1", name: "A", created_at: "x", updated_at: "x" },
    });
    await useTemplateStore.getState().instantiate("t-1", "A");
    expect(useTemplateStore.getState().instantiating).toBe(false);

    mock.mockResolvedValueOnce({
      template_id: "t-1",
      strategy: { id: "s-2", name: "B", created_at: "x", updated_at: "x" },
    });
    const r = await useTemplateStore.getState().instantiate("t-1", "B");
    expect(r?.strategy?.id).toBe("s-2");
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it("payload includes name + symbol overrides", async () => {
    mock.mockResolvedValueOnce({
      template_id: "t-1",
      strategy: { id: "s-1", name: "Custom", created_at: "x", updated_at: "x" },
    });
    await useTemplateStore.getState().instantiate("t-1", "Custom", "ETH/USDT");
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.name).toBe("Custom");
    expect(body.symbol).toBe("ETH/USDT");
  });
});
