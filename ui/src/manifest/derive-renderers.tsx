/**
 * pickRenderer — turn a FunctionManifest into a `{ chart, table, cards }`
 * triple of React component types appropriate for its grammars.
 *
 * The components themselves are placeholders that render a single
 * `<div data-renderer-kind="…" />` so other agents can swap them later
 * without changing the contract. A `null` slot means the manifest does
 * not advertise that section (e.g. no chart_grammar ⇒ `chart: null`).
 */
import type { JSX } from "react";

import {
  type CardSchema,
  type ChartGrammar,
  type ChartKind,
  type FunctionManifest,
  type TableSchema,
} from "./types";

export type ChartRenderer = (props: { grammar: ChartGrammar }) => JSX.Element;
export type TableRenderer = (props: { schema: TableSchema }) => JSX.Element;
export type CardsRenderer = (props: { schema: CardSchema }) => JSX.Element;

export interface RendererPicker {
  chart: ChartRenderer | null;
  table: TableRenderer | null;
  cards: CardsRenderer | null;
}

// ---------------------------------------------------------------------------
// Placeholder renderer components — keyed by ChartKind / generic for table+card.
// ---------------------------------------------------------------------------

function chartRendererFor(kind: ChartKind): ChartRenderer {
  return function ManifestChart({ grammar }): JSX.Element {
    return (
      <div
        data-renderer-kind={kind}
        data-renderer-category="chart"
        data-overlay-support={grammar.overlay_support ? "1" : "0"}
        data-compare-support={grammar.compare_support ? "1" : "0"}
        data-pane-count={grammar.panes.length}
      />
    );
  };
}

function tableRenderer(): TableRenderer {
  return function ManifestTable({ schema }): JSX.Element {
    return (
      <div
        data-renderer-category="table"
        data-renderer-kind="table"
        data-column-count={schema.columns.length}
        data-sortable={schema.sortable ? "1" : "0"}
        data-filterable={schema.filterable ? "1" : "0"}
      />
    );
  };
}

function cardsRenderer(): CardsRenderer {
  return function ManifestCards({ schema }): JSX.Element {
    return (
      <div
        data-renderer-category="cards"
        data-renderer-kind="cards"
        data-slot-count={schema.slots.length}
      />
    );
  };
}

export function pickRenderer(manifest: FunctionManifest): RendererPicker {
  return {
    chart: manifest.chart_grammar ? chartRendererFor(manifest.chart_grammar.kind) : null,
    table: manifest.table_schema ? tableRenderer() : null,
    cards: manifest.card_schema ? cardsRenderer() : null,
  };
}

export default pickRenderer;
