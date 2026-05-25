/**
 * ManifestPane smoke tests — verify the integration pane renders a header,
 * a controls row, dispatches a fetch, and surfaces data mode + sources +
 * warnings + next actions.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { ManifestPane } from "./ManifestPane";
import { manifestStore } from "./registry";
import type { FunctionManifest } from "./types";

// Mock useFunction so tests don't need a sidecar.
vi.mock("@/lib/useFunction", () => ({
  useFunction: vi.fn(),
}));

import { useFunction } from "@/lib/useFunction";

const TEST_MANIFEST: FunctionManifest = {
  code: "TST",
  name: "Test Pane",
  category: "misc",
  intent: "A test manifest used by ManifestPane smoke tests.",
  asset_classes: ["equity"],
  inputs: [
    {
      name: "symbol",
      label: "Symbol",
      control: "symbol_picker",
      required: true,
      description: "Test ticker",
      depends_on: [],
    },
    {
      name: "horizon",
      label: "Horizon",
      control: "horizon",
      required: false,
      description: "Forward horizon",
      unit: "days",
      depends_on: [],
    },
  ],
  defaults: { symbol: "AAPL", horizon: 30 },
  provider_chain: {
    primary: "yfinance_adapter",
    fallbacks: ["cached_snapshot"],
    acceptable_modes: ["delayed_reference", "cached_snapshot"],
  },
  caching: { ttl_seconds: 60, scope: "per_input", persist: true },
  output_contract: {
    must_have: ["symbol", "as_of"],
    rows: true,
    series: false,
    cards: true,
    warnings: true,
    next_actions: true,
  },
  chart_grammar: null,
  table_schema: null,
  card_schema: null,
  methodology: "Test methodology paragraph.",
  formula_dict: {},
  field_dict: {},
  provenance: { require_source_list: true, require_as_of: true, require_latency_ms: false },
  alerting: null,
  semantic_tests: [
    { name: "test_smoke", description: "smoke", inputs: {}, assertions: [] },
  ],
};

beforeEach(() => {
  manifestStore.replaceAll([TEST_MANIFEST]);
  vi.mocked(useFunction).mockReturnValue({
    state: "ok",
    data: {
      data: {
        symbol: "AAPL",
        as_of: new Date().toISOString(),
        data_mode: "delayed_reference",
        sources: ["yfinance_adapter"],
        latency_ms: 142,
        warnings: ["FRED key missing — degraded"],
        next_actions: ["Open GP", "Open FA"],
      },
    } as unknown as ReturnType<typeof useFunction>["data"],
    error: undefined,
    refetch: () => {},
  });
});

afterEach(() => {
  manifestStore.clear();
  cleanup();
  vi.clearAllMocks();
});

describe("ManifestPane", () => {
  it("renders title + intent + controls", () => {
    render(<ManifestPane code="TST" />);
    expect(screen.getByText("TST")).toBeTruthy();
    expect(screen.getByText("Test Pane")).toBeTruthy();
    expect(screen.getByText(/A test manifest/)).toBeTruthy();
    const controls = screen.getByTestId("manifest-pane-controls");
    expect(controls.children.length).toBeGreaterThanOrEqual(2);
  });

  it("renders the data mode pill", () => {
    render(<ManifestPane code="TST" />);
    const pill = screen.getByTestId("manifest-pane-mode-pill");
    expect(pill.textContent).toMatch(/DELAYED/);
  });

  it("renders sources strip with latency", () => {
    render(<ManifestPane code="TST" />);
    const strip = screen.getByTestId("manifest-pane-sources");
    expect(strip.textContent).toMatch(/yfinance_adapter/);
    expect(strip.textContent).toMatch(/142 ms/);
  });

  it("renders warnings strip", () => {
    render(<ManifestPane code="TST" />);
    const warnings = screen.getByTestId("manifest-pane-warnings");
    expect(warnings.textContent).toMatch(/FRED key missing/);
  });

  it("renders next-actions chips", () => {
    render(<ManifestPane code="TST" />);
    const actions = screen.getByTestId("manifest-pane-next-actions");
    expect(actions.textContent).toMatch(/Open GP/);
    expect(actions.textContent).toMatch(/Open FA/);
  });

  it("calls customRenderer with manifest + payload when provided", () => {
    const seen: { manifest?: { code: string }; payload?: { symbol?: unknown } } = {};
    const custom = (args: { manifest: { code: string }; payload?: { symbol?: unknown } }) => {
      seen.manifest = args.manifest;
      seen.payload = args.payload;
      return <div data-testid="custom-renderer-output">CUSTOM</div>;
    };
    render(<ManifestPane code="TST" customRenderer={custom as never} />);
    expect(screen.getByTestId("custom-renderer-output").textContent).toBe("CUSTOM");
    expect(seen.manifest?.code).toBe("TST");
    expect(seen.payload?.symbol).toBe("AAPL");
  });

  it("renders loading state when manifest not in registry", () => {
    manifestStore.clear();
    render(<ManifestPane code="DOES_NOT_EXIST" />);
    expect(screen.getByTestId("manifest-pane-loading")).toBeTruthy();
  });

  it("renders error state when fetch fails", () => {
    vi.mocked(useFunction).mockReturnValue({
      state: "error",
      data: undefined,
      error: new Error("network down"),
      refetch: () => {},
    });
    render(<ManifestPane code="TST" />);
    const err = screen.getByTestId("manifest-pane-error");
    expect(err.textContent).toMatch(/network down/);
  });
});
