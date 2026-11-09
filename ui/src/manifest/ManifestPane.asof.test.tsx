/**
 * UI-13: the as-of pill must show the calendar date in the same zone as
 * its clock time. Before the fix a non-today snapshot printed the UTC date
 * (toISOString) next to a local time, so a UTC+3 user at 00:30 local on
 * 2026-11-07 saw "2026-11-06 · 00:30:00". The expected date below is built
 * from local getters, the same zone the time is rendered in.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

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
  intent: "As-of formatting test manifest.",
  asset_classes: ["equity"],
  inputs: [],
  defaults: {},
  provider_chain: {
    primary: "yfinance_adapter",
    fallbacks: [],
    acceptable_modes: ["delayed_reference"],
  },
  caching: { ttl_seconds: 60, scope: "per_input", persist: true },
  output_contract: {
    must_have: ["as_of"],
    rows: false,
    series: false,
    cards: false,
    warnings: false,
    next_actions: false,
  },
  chart_grammar: null,
  table_schema: null,
  card_schema: null,
  methodology: "Test.",
  formula_dict: {},
  field_dict: {},
  provenance: { require_source_list: false, require_as_of: true, require_latency_ms: false },
  alerting: null,
  semantic_tests: [],
};

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function mockAsOf(iso: string) {
  vi.mocked(useFunction).mockReturnValue({
    state: "ok",
    data: { data: { as_of: iso, data_mode: "delayed_reference" } } as unknown as ReturnType<
      typeof useFunction
    >["data"],
    error: undefined,
    refetch: () => {},
  });
}

beforeEach(() => {
  manifestStore.replaceAll([MANIFEST]);
});

afterEach(() => {
  manifestStore.clear();
  cleanup();
  vi.clearAllMocks();
});

describe("ManifestPane as-of pill (UI-13)", () => {
  it("prints the local calendar date that matches the local clock time", () => {
    // Local 00:30 on 2026-11-07: in UTC+ zones this is still 2026-11-06 in UTC.
    const local = new Date(2026, 10, 7, 0, 30, 0);
    mockAsOf(local.toISOString());
    render(<ManifestPane code="TST" />);
    const pill = screen.getByTestId("manifest-pane-as-of");
    const expectedDate = `${local.getFullYear()}-${pad(local.getMonth() + 1)}-${pad(local.getDate())}`;
    expect(pill.textContent).toContain(`${expectedDate} · `);
  });
});
