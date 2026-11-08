/**
 * UI-1: a manifest pane follows the linked symbol.
 *
 * Inputs were seeded once from initialInputs, so when the terminal link moved
 * from AAPL to MSFT the pane kept fetching AAPL under a pane linked to MSFT.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

import { ManifestPane } from "./ManifestPane";
import { manifestStore } from "./registry";
import type { FunctionManifest } from "./types";

vi.mock("@/lib/useFunction", () => ({
  useFunction: vi.fn(),
}));

import { useFunction } from "@/lib/useFunction";

const MANIFEST: FunctionManifest = {
  code: "TST",
  name: "Test Pane",
  category: "misc",
  intent: "Linked-symbol regression manifest.",
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
  ],
  defaults: { symbol: "AAPL" },
  provider_chain: {
    primary: "yfinance_adapter",
    fallbacks: [],
    acceptable_modes: ["delayed_reference"],
  },
  caching: { ttl_seconds: 60, scope: "per_input", persist: true },
  output_contract: {
    must_have: ["symbol"],
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
  semantic_tests: [{ name: "test_smoke", description: "smoke", inputs: {}, assertions: [] }],
};

beforeEach(() => {
  manifestStore.replaceAll([MANIFEST]);
  vi.mocked(useFunction).mockReturnValue({
    state: "ok",
    data: undefined,
    error: undefined,
    refetch: () => {},
  } as unknown as ReturnType<typeof useFunction>);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function lastFetchSymbol(): unknown {
  const calls = vi.mocked(useFunction).mock.calls;
  return (calls[calls.length - 1][0] as { symbol?: unknown }).symbol;
}

describe("ManifestPane linked symbol", () => {
  it("fetches the new symbol after the linked symbol changes", () => {
    const { rerender } = render(<ManifestPane code="TST" initialInputs={{ symbol: "AAPL" }} />);
    expect(lastFetchSymbol()).toBe("AAPL");

    rerender(<ManifestPane code="TST" initialInputs={{ symbol: "MSFT" }} />);

    expect(lastFetchSymbol()).toBe("MSFT");
  });

  it("keeps the current symbol when the link is cleared", () => {
    const { rerender } = render(<ManifestPane code="TST" initialInputs={{ symbol: "AAPL" }} />);
    rerender(<ManifestPane code="TST" initialInputs={undefined} />);
    expect(lastFetchSymbol()).toBe("AAPL");
  });
});
