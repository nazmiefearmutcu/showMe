import { beforeEach, describe, expect, it, vi } from "vitest";
import { useIndicatorStore, confidenceColor } from "./indicator-store";

vi.mock("./sidecar", () => ({ sidecarFetch: vi.fn() }));

import { sidecarFetch } from "./sidecar";
const mock = sidecarFetch as ReturnType<typeof vi.fn>;

const sample = [
  { id: "rsi", display_name: "RSI", family: "momentum", short_description: "OB/OS",
    long_description: "", formula: "", parameters: [], confidence: 9,
    confidence_rationale: "", suggested_strategy: {}, references: [] },
  { id: "ema", display_name: "EMA", family: "trend", short_description: "MA",
    long_description: "", formula: "", parameters: [], confidence: 8,
    confidence_rationale: "", suggested_strategy: {}, references: [] },
];

beforeEach(() => {
  useIndicatorStore.setState({ entries: [], loading: false, error: null, selectedId: null });
  mock.mockReset();
});

describe("indicator-store", () => {
  it("loadCatalog populates entries", async () => {
    mock.mockResolvedValueOnce(sample);
    await useIndicatorStore.getState().loadCatalog();
    expect(useIndicatorStore.getState().entries).toHaveLength(2);
  });

  it("byId returns the entry", () => {
    useIndicatorStore.setState({ entries: sample });
    expect(useIndicatorStore.getState().byId("rsi")?.display_name).toBe("RSI");
    expect(useIndicatorStore.getState().byId("missing")).toBeUndefined();
  });

  it("search filters by query", () => {
    useIndicatorStore.setState({ entries: sample });
    expect(useIndicatorStore.getState().search("rsi").map((e) => e.id)).toEqual(["rsi"]);
    expect(useIndicatorStore.getState().search("").map((e) => e.id)).toEqual(["rsi", "ema"]);
  });

  it("search filters by family", () => {
    useIndicatorStore.setState({ entries: sample });
    expect(useIndicatorStore.getState().search("", "trend").map((e) => e.id)).toEqual(["ema"]);
  });

  it("loadCatalog surfaces backend errors", async () => {
    mock.mockRejectedValueOnce(new Error("503"));
    await useIndicatorStore.getState().loadCatalog();
    expect(useIndicatorStore.getState().error).toContain("503");
  });
});

describe("confidenceColor", () => {
  it("maps 10 to ok", () => { expect(confidenceColor(10)).toContain("ok"); });
  it("maps 7 to soft-ok", () => { expect(confidenceColor(7)).toContain("ok"); });
  it("maps 5 to warn", () => { expect(confidenceColor(5)).toContain("warn"); });
  it("maps 3 to warn-strong", () => { expect(confidenceColor(3)).toContain("warn"); });
  it("maps 1 to err", () => { expect(confidenceColor(1)).toContain("err"); });
});
