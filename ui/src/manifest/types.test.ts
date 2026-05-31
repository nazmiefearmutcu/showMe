/**
 * Vitest suite for the manifest contract:
 *   - registry round-trip
 *   - deriveControls element count, ordering, depends_on hiding
 *   - pickRenderer wires chart/table/cards by grammar presence
 *
 * Kept as `.ts` (no JSX literals) so it lives alongside `types.ts`. We
 * inspect the rendered elements via their `type` and `props` fields,
 * which is enough to exercise the contract without mounting.
 */
import { beforeEach, describe, expect, it } from "vitest";

import { SymbolPicker } from "./controls/SymbolPicker";
import { DateRangePicker } from "./controls/DateRangePicker";
import { ProviderModeControl } from "./controls/ProviderModeControl";
import { deriveControls, isVisible, isUnset } from "./derive-controls";
import { pickRenderer } from "./derive-renderers";
import { manifestStore } from "./registry";
import {
  type ChartGrammar,
  type FunctionManifest,
  type InputSpec,
} from "./types";

function makeManifest(overrides: Partial<FunctionManifest> = {}): FunctionManifest {
  return {
    code: "GP",
    name: "General Price",
    category: "charts_tech",
    intent: "Display the OHLCV price history for a single instrument.",
    asset_classes: ["equity", "crypto"],
    inputs: [],
    defaults: {},
    provider_chain: {
      primary: "yfinance",
      fallbacks: ["binance"],
      acceptable_modes: ["live_exchange", "cached_snapshot"],
    },
    caching: { ttl_seconds: 30, scope: "per_input", persist: false },
    output_contract: {
      must_have: ["series"],
      rows: false,
      series: true,
      cards: true,
      warnings: true,
      next_actions: false,
    },
    chart_grammar: null,
    table_schema: null,
    card_schema: null,
    methodology: "n/a",
    formula_dict: {},
    field_dict: {},
    provenance: {
      require_source_list: true,
      require_as_of: true,
      require_latency_ms: true,
    },
    alerting: null,
    semantic_tests: [
      {
        name: "smoke",
        description: "fixture for tests",
        inputs: {},
        assertions: ["truthy"],
      },
    ],
    ...overrides,
  };
}

const SYMBOL_INPUT: InputSpec = {
  name: "symbol",
  label: "Symbol",
  control: "symbol_picker",
  required: true,
  description: "Ticker or pair.",
  depends_on: [],
};
const DATE_RANGE_INPUT: InputSpec = {
  name: "date_range",
  label: "Date Range",
  control: "date_range",
  required: true,
  description: "Window.",
  options: ["1M", "3M", "6M"],
  depends_on: ["symbol"],
};
const MODE_INPUT: InputSpec = {
  name: "provider_mode",
  label: "Provider Mode",
  control: "provider_mode",
  required: false,
  description: "Optional override.",
  options: ["live_exchange", "cached_snapshot"],
  depends_on: [],
};

const CANDLE_GRAMMAR: ChartGrammar = {
  kind: "time_series_candles",
  x_axis: { type: "time", unit: "iso8601", label: "Time" },
  y_axis: [
    { type: "numeric", unit: "quote_ccy", label: "Price" },
    { type: "numeric", unit: "shares", label: "Volume" },
  ],
  panes: [
    { name: "price", series_kind: "candle", height_pct: 75 },
    { name: "volume", series_kind: "histogram", height_pct: 25 },
  ],
  overlay_support: true,
  compare_support: true,
};

beforeEach(() => {
  manifestStore.clear();
});

describe("isUnset / isVisible", () => {
  it("treats undefined/null/empty-string/empty-array as unset", () => {
    expect(isUnset(undefined)).toBe(true);
    expect(isUnset(null)).toBe(true);
    expect(isUnset("")).toBe(true);
    expect(isUnset([])).toBe(true);
    expect(isUnset(false)).toBe(false);
    expect(isUnset(0)).toBe(false);
    expect(isUnset("AAPL")).toBe(false);
    expect(isUnset(["a"])).toBe(false);
  });

  it("is true when no depends_on are present", () => {
    expect(isVisible(SYMBOL_INPUT, {})).toBe(true);
  });

  it("hides children when any parent is unset", () => {
    expect(isVisible(DATE_RANGE_INPUT, {})).toBe(false);
    expect(isVisible(DATE_RANGE_INPUT, { symbol: "" })).toBe(false);
    expect(isVisible(DATE_RANGE_INPUT, { symbol: "AAPL" })).toBe(true);
  });
});

describe("deriveControls", () => {
  it("renders one element per non-hidden input in declaration order", () => {
    const m = makeManifest({
      inputs: [SYMBOL_INPUT, DATE_RANGE_INPUT, MODE_INPUT],
    });
    const els = deriveControls(m, { symbol: "AAPL" }, () => {});
    expect(els).toHaveLength(3);
    expect(els[0]!.type).toBe(SymbolPicker);
    expect(els[1]!.type).toBe(DateRangePicker);
    expect(els[2]!.type).toBe(ProviderModeControl);
    // Keys come from `InputSpec.name`.
    expect(els[0]!.key).toBe("symbol");
    expect(els[1]!.key).toBe("date_range");
    expect(els[2]!.key).toBe("provider_mode");
  });

  it("hides depends_on children when parent is unset", () => {
    const m = makeManifest({
      inputs: [SYMBOL_INPUT, DATE_RANGE_INPUT, MODE_INPUT],
    });
    const els = deriveControls(m, {}, () => {});
    expect(els).toHaveLength(2);
    expect(els.map((el) => el.key)).toEqual(["symbol", "provider_mode"]);
  });

  it("passes value + a merging onChange to the child", () => {
    const m = makeManifest({ inputs: [SYMBOL_INPUT] });
    let captured: Record<string, unknown> | null = null;
    const els = deriveControls(m, { symbol: "AAPL", date_range: "6M" }, (next) => {
      captured = next;
    });
    expect(els).toHaveLength(1);
    const props = els[0]!.props as { spec: InputSpec; value: unknown; onChange: (v: unknown) => void };
    expect(props.spec).toBe(SYMBOL_INPUT);
    expect(props.value).toBe("AAPL");
    props.onChange("MSFT");
    expect(captured).toEqual({ symbol: "MSFT", date_range: "6M" });
  });

  it("returns an empty array for a manifest with no inputs", () => {
    expect(deriveControls(makeManifest(), {}, () => {})).toEqual([]);
  });
});

describe("pickRenderer", () => {
  it("returns chart renderer for time_series_candles grammar", () => {
    const m = makeManifest({ chart_grammar: CANDLE_GRAMMAR });
    const picked = pickRenderer(m);
    expect(picked.chart).not.toBeNull();
    expect(picked.table).toBeNull();
    expect(picked.cards).toBeNull();
    // The renderer is a placeholder — invoke it and inspect the rendered
    // element's `type`/`props` to confirm the kind tag is wired through.
    const ChartComp = picked.chart!;
    const rendered = ChartComp({ grammar: CANDLE_GRAMMAR });
    expect(rendered.type).toBe("div");
    expect((rendered.props as Record<string, unknown>)["data-renderer-kind"]).toBe(
      "time_series_candles",
    );
    expect((rendered.props as Record<string, unknown>)["data-pane-count"]).toBe(2);
  });

  it("returns null chart when manifest has no chart_grammar", () => {
    const picked = pickRenderer(makeManifest());
    expect(picked.chart).toBeNull();
  });

  it("returns table + cards renderers when their schemas are present", () => {
    const m = makeManifest({
      table_schema: {
        columns: [
          { key: "t", label: "Time", kind: "datetime", unit: null, format: null, width_hint: null },
        ],
        sortable: true,
        filterable: false,
      },
      card_schema: {
        slots: [
          { key: "last", label: "Last", kind: "big_number", unit: "USD" },
          { key: "chg", label: "Chg %", kind: "trend_pill", unit: "%" },
        ],
      },
    });
    const picked = pickRenderer(m);
    expect(picked.table).not.toBeNull();
    expect(picked.cards).not.toBeNull();
    const tableEl = picked.table!({
      schema: m.table_schema!,
      payload: { rows: [{ t: new Date("2026-01-01"), label: "x" }] },
    });
    expect(tableEl.type).toBe("div");
    expect((tableEl.props as Record<string, unknown>)["data-renderer-kind"]).toBe("table");
    expect((tableEl.props as Record<string, unknown>)["data-column-count"]).toBe(1);
    const cardsEl = picked.cards!({
      schema: m.card_schema!,
      payload: { last: 10, chg: 2.5 },
    });
    expect(cardsEl.type).toBe("div");
    expect((cardsEl.props as Record<string, unknown>)["data-slot-count"]).toBe(2);
  });
});

describe("registry round-trip", () => {
  it("round-trips a manifest through set/get/all/codes/clear", () => {
    expect(manifestStore.all()).toEqual([]);
    expect(manifestStore.codes()).toEqual([]);
    expect(manifestStore.get("GP")).toBeNull();

    const gp = makeManifest({ code: "GP" });
    const dvd = makeManifest({ code: "DVD", name: "Dividends" });
    manifestStore.set(gp.code, gp);
    manifestStore.set(dvd.code, dvd);

    expect(manifestStore.get("GP")).toBe(gp);
    expect(manifestStore.get("DVD")).toBe(dvd);
    expect(manifestStore.codes()).toEqual(["GP", "DVD"]);
    expect(manifestStore.all()).toEqual([gp, dvd]);

    manifestStore.clear();
    expect(manifestStore.all()).toEqual([]);
    expect(manifestStore.get("GP")).toBeNull();
  });

  it("replaceAll swaps the registry atomically", () => {
    manifestStore.set("GP", makeManifest({ code: "GP" }));
    manifestStore.replaceAll([makeManifest({ code: "PORT" })]);
    expect(manifestStore.codes()).toEqual(["PORT"]);
  });

  it("notifies subscribers on every mutation", () => {
    let pings = 0;
    const off = manifestStore.subscribe(() => {
      pings += 1;
    });
    manifestStore.set("GP", makeManifest({ code: "GP" }));
    manifestStore.set("DVD", makeManifest({ code: "DVD" }));
    manifestStore.clear();
    off();
    manifestStore.set("WILL_NOT_FIRE", makeManifest({ code: "WILL_NOT_FIRE" }));
    expect(pings).toBe(3); // 2× set + 1× clear, ignoring the post-unsubscribe set
  });
});
