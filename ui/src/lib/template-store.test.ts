import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTemplateStore } from "./template-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));
import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

const FIX = [
  { id: "rsi-mean-revert", name: "RSI MR", description: "", uses_indicators: ["rsi"],
    recommended_timeframe: "1h", recommended_symbols: ["BTC/USDT"],
    applicability: "", natural_language_explanation: "NL", math: "M",
    spec_template: {}, family: "momentum" },
];

beforeEach(() => {
  useTemplateStore.setState({ entries: [], selectedId: null, loading: false, error: null });
  mock.mockReset();
});

describe("template-store", () => {
  it("loadCatalog populates", async () => {
    mock.mockResolvedValueOnce(FIX);
    await useTemplateStore.getState().loadCatalog();
    expect(useTemplateStore.getState().entries).toHaveLength(1);
  });

  it("byId returns matching entry", () => {
    useTemplateStore.setState({ entries: FIX });
    expect(useTemplateStore.getState().byId("rsi-mean-revert")?.name).toBe("RSI MR");
    expect(useTemplateStore.getState().byId("missing")).toBeUndefined();
  });

  it("setSelected updates state", () => {
    useTemplateStore.getState().setSelected("rsi-mean-revert");
    expect(useTemplateStore.getState().selectedId).toBe("rsi-mean-revert");
  });

  it("instantiate POSTs with name+symbol", async () => {
    mock.mockResolvedValueOnce({ template_id: "rsi-mean-revert", strategy: { id: "s1" } });
    const r = await useTemplateStore.getState().instantiate("rsi-mean-revert", "My", "ETH/USDT");
    expect(r?.template_id).toBe("rsi-mean-revert");
    const body = JSON.parse(String((mock.mock.calls[0][1] as RequestInit).body));
    expect(body.name).toBe("My");
    expect(body.symbol).toBe("ETH/USDT");
  });

  it("instantiate surfaces errors", async () => {
    mock.mockRejectedValueOnce(new Error("500 boom"));
    const r = await useTemplateStore.getState().instantiate("rsi-mean-revert");
    expect(r).toBeNull();
    expect(useTemplateStore.getState().error).toContain("500");
  });
});
