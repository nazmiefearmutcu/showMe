/**
 * TemplateRenderer — renders the Design Basic-variant layout for a
 * given fn code. The pattern is chosen by the mock template's content
 * shape (kpis + feed → news; kpis + tableRows → table; heatCells →
 * heatmap; formRows → form; kvs → kv grid). Real sidecar data, when
 * available, is layered on top of the mock via `mergeLivePayload` —
 * `feed`, `tableRows`, and `kpis` shapes are filled from the
 * `/api/fn/{code}` response whenever the backend returns recognisable
 * fields. The mock fills the gap when no live payload is present (or
 * when the backend returned an unrelated shape).
 *
 * Fallback chain: bespoke native pane > TemplateRenderer (this file) >
 * FunctionStub. TemplateRenderer never returns null when a mock is
 * registered, so a templated code never falls through to FunctionStub.
 */
import "./templates.css";
import { useMemo } from "react";
import { Pane, PaneBody, PaneHeader, Pill, Skeleton, SkeletonRow } from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  TplCard,
  TplCardHeader,
  TplChip,
  TplChipRow,
  TplFeedItem,
  TplHeatCell,
  TplKpiTile,
  TplKvGrid,
  TplKvRow,
  TplSectionHead,
  TplSparkRow,
  TplTable,
} from "./primitives";
import {
  getMockTemplate,
  type FeedEntry,
  type KpiTile,
  type MockTemplate,
  type TableRow,
  SPARKS_WL,
} from "./mock-data";

export interface TemplateRendererProps {
  code: string;
  symbol?: string;
}

export function TemplateRenderer({ code, symbol }: TemplateRendererProps) {
  const tpl = getMockTemplate(code);
  const liveParams = useMemo(() => (symbol ? { symbol } : {}), [symbol]);
  const { state, data, error } = useFunction<unknown>({
    code,
    symbol,
    params: liveParams,
    enabled: tpl != null,
  });

  // BugHunt 2026-05-24: when the sidecar hasn't returned `ok` yet and the
  // template hasn't explicitly opted in via `allowMockDuringLoad: true`, we
  // render a skeleton placeholder instead of the mock. This prevents the
  // 5-second "live data" illusion where a numeric-pricing template (OMON,
  // OSA, OVME, AIM, …) would show hard-coded strikes/prices next to the
  // user-selected ticker.
  const shouldHideMockBody =
    tpl != null && state !== "ok" && tpl.allowMockDuringLoad !== true;

  const merged = useMemo<MockTemplate | null>(() => {
    if (!tpl) return null;
    if (state !== "ok" || !data?.data) return tpl;
    return mergeLivePayload(tpl, code, data.data);
  }, [tpl, state, data, code]);

  if (!tpl || !merged) return null;

  const liveBadge = renderLiveBadge(state, data, error);

  return (
    <Pane>
      <PaneHeader
        title={symbol ? `${merged.title} · ${symbol}` : merged.title}
        subtitle={merged.sub}
        code={code.toUpperCase()}
        trailing={liveBadge}
      />
      <PaneBody>
        <div className="tpl-pane">
          {shouldHideMockBody ? (
            <TemplateSkeleton tpl={merged} />
          ) : (
            <>
              <Hero tpl={merged} />
              <Body tpl={merged} />
              {merged.narrative && <Narrative text={merged.narrative} />}
            </>
          )}
        </div>
      </PaneBody>
    </Pane>
  );
}

export function hasTemplate(code: string): boolean {
  return getMockTemplate(code) !== null;
}

/* ── Loading skeleton (BugHunt 2026-05-24) ───────────────────────── */

/**
 * Shape-faithful skeleton that mirrors the template's body pattern so the
 * pane doesn't reflow when live data arrives. The skeleton is intentionally
 * featureless (no numbers, no shapes that look like prices) so users can't
 * misread it as a live quote.
 */
function TemplateSkeleton({ tpl }: { tpl: MockTemplate }) {
  const kpiCount = Math.min(tpl.kpis?.length ?? 4, 6) || 4;
  const tableCount = Math.min(tpl.tableRows?.length ?? 4, 6) || 4;
  const feedCount = Math.min(tpl.feed?.length ?? 4, 5) || 4;
  const colCount = tpl.tableCols?.length ?? 4;

  return (
    <div className="tpl-pattern" aria-busy="true" aria-live="polite">
      {(tpl.chips?.length ?? 0) > 0 && (
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          {Array.from({ length: Math.min(tpl.chips!.length, 6) }).map((_, i) => (
            <Skeleton key={i} width={72} height={22} radius={11} />
          ))}
        </div>
      )}
      {(tpl.kpis?.length ?? 0) > 0 && (
        <div className="tpl-kpi-grid" style={{ marginBottom: 12 }}>
          {Array.from({ length: kpiCount }).map((_, i) => (
            <div
              key={i}
              style={{
                padding: 12,
                display: "flex",
                flexDirection: "column",
                gap: 6,
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)",
              }}
            >
              <Skeleton width={68} height={10} />
              <Skeleton width={92} height={20} />
            </div>
          ))}
        </div>
      )}
      {(tpl.tableRows?.length ?? 0) > 0 && (
        <div
          style={{
            padding: 12,
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            marginBottom: 12,
          }}
        >
          <Skeleton width={120} height={12} />
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {Array.from({ length: tableCount }).map((_, i) => (
              <SkeletonRow key={i} columns={colCount || 4} />
            ))}
          </div>
        </div>
      )}
      {(tpl.feed?.length ?? 0) > 0 && (
        <div
          style={{
            padding: 12,
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            marginBottom: 12,
          }}
        >
          {Array.from({ length: feedCount }).map((_, i) => (
            <div
              key={i}
              style={{ display: "flex", flexDirection: "column", gap: 6, padding: "8px 0" }}
            >
              <Skeleton width="60%" height={12} />
              <Skeleton width="92%" height={10} />
            </div>
          ))}
        </div>
      )}
      {(tpl.formRows?.length ?? 0) > 0 && (
        <div
          style={{
            padding: 12,
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            marginBottom: 12,
          }}
        >
          {Array.from({ length: Math.min(tpl.formRows!.length, 6) }).map((_, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                padding: "6px 0",
              }}
            >
              <Skeleton width={120} height={11} />
              <Skeleton width={84} height={11} />
            </div>
          ))}
        </div>
      )}
      {(tpl.kvs?.length ?? 0) > 0 && (
        <div
          style={{
            padding: 12,
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            marginBottom: 12,
          }}
        >
          {Array.from({ length: Math.min(tpl.kvs!.length, 6) }).map((_, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                padding: "5px 0",
              }}
            >
              <Skeleton width={108} height={10} />
              <Skeleton width={140} height={10} />
            </div>
          ))}
        </div>
      )}
      {(tpl.heatCells?.length ?? 0) > 0 && (
        <div
          className="tpl-heat-grid"
          style={{
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: 12,
            marginBottom: 12,
          }}
        >
          {Array.from({ length: Math.min(tpl.heatCells!.length, 12) }).map((_, i) => (
            <Skeleton key={i} width={56} height={32} />
          ))}
        </div>
      )}
      {!tpl.kpis && !tpl.tableRows && !tpl.feed && !tpl.formRows && !tpl.kvs && !tpl.heatCells && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Skeleton width="50%" height={14} />
          <Skeleton width="86%" height={10} />
          <Skeleton width="74%" height={10} />
        </div>
      )}
    </div>
  );
}

/* ── Hero (KPI grid + optional chips) ───────────────────────────── */

function Hero({ tpl }: { tpl: MockTemplate }) {
  if (!tpl.kpis && !tpl.chips) return null;
  return (
    <div className="tpl-pattern">
      {tpl.chips && tpl.chips.length > 0 && (
        <TplChipRow>
          {tpl.chips.map((c) => (
            <TplChip key={c.id} tone={c.tone} count={c.count}>
              {c.label}
            </TplChip>
          ))}
        </TplChipRow>
      )}
      {tpl.kpis && tpl.kpis.length > 0 && (
        <div className="tpl-kpi-grid">
          {tpl.kpis.map((k) => (
            <TplKpiTile key={k.label} {...k} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Body — pattern picked from mock-template shape ─────────────── */

function Body({ tpl }: { tpl: MockTemplate }) {
  const blocks: React.ReactNode[] = [];

  if (tpl.feed && tpl.feed.length > 0) {
    blocks.push(
      <TplCard key="feed">
        <TplCardHeader title="Feed" sub={`${tpl.feed.length} items`} />
        <div className="tpl-feed">
          {tpl.feed.map((f, i) => (
            <TplFeedItem key={i} {...f} />
          ))}
        </div>
      </TplCard>,
    );
  }

  if (tpl.kvs && tpl.kvs.length > 0) {
    blocks.push(
      <TplCard key="kvs">
        <TplCardHeader title="Spec" />
        <TplKvGrid cols={2}>
          {tpl.kvs.map((kv) => (
            <TplKvRow key={kv.k} label={kv.k} value={kv.v} />
          ))}
        </TplKvGrid>
      </TplCard>,
    );
  }

  if (tpl.tableRows && tpl.tableCols && tpl.tableRows.length > 0) {
    blocks.push(
      <TplCard key="table">
        <TplCardHeader title="Detail" sub={`${tpl.tableRows.length} rows`} />
        <TplTable
          cols={tpl.tableCols}
          rows={tpl.tableRows as unknown as Array<Record<string, React.ReactNode>>}
        />
      </TplCard>,
    );
  }

  if (tpl.heatCells && tpl.heatCells.length > 0) {
    blocks.push(
      <TplCard key="heat">
        <TplCardHeader title="Heatmap" sub={`${tpl.heatCells.length} cells`} />
        <div className="tpl-heat-grid">
          {tpl.heatCells.map((h, i) => (
            <TplHeatCell key={i} {...h} />
          ))}
        </div>
      </TplCard>,
    );
  }

  if (tpl.formRows && tpl.formRows.length > 0) {
    blocks.push(
      <TplCard key="form">
        <TplCardHeader title="Inputs · Outputs" />
        <div className="tpl-form-grid">
          {tpl.formRows.map((f) => (
            <div key={f.label} className="tpl-form-row">
              <span className="tpl-form-row__l">{f.label}</span>
              <span
                className={`tpl-form-row__v${f.tone === "pos" ? " pos" : f.tone === "neg" ? " neg" : ""}`}
              >
                {f.value}
              </span>
            </div>
          ))}
        </div>
      </TplCard>,
    );
  }

  // For codes with no body-data (only kpis/chips), append the canonical
  // watchlist mini-strip so the surface is never empty.
  if (blocks.length === 0) {
    blocks.push(
      <TplCard key="watchlist-mini">
        <TplCardHeader title="Related symbols" sub="watchlist preview" />
        <TplSectionHead label="Top 5" />
        <div>
          {SPARKS_WL.map((row) => (
            <TplSparkRow key={row.symbol} {...row} />
          ))}
        </div>
      </TplCard>,
    );
  }

  return <>{blocks}</>;
}

function Narrative({ text }: { text: string }) {
  return (
    <TplCard>
      <p style={{ margin: 0, color: "var(--text-secondary)", lineHeight: 1.6 }}>
        {text}
      </p>
    </TplCard>
  );
}

/* ── Live-data overlay ──────────────────────────────────────────── */

function renderLiveBadge(
  state: "idle" | "loading" | "ok" | "error" | "refreshing",
  data: { elapsed_ms?: number | null; sources?: string[] | null } | undefined,
  error: Error | undefined,
): React.ReactNode {
  if (state === "loading") {
    return (
      <Pill tone="muted" variant="soft" withDot>
        LOADING
      </Pill>
    );
  }
  if (state === "refreshing") {
    // The hook keeps prior `data` on screen during a refresh; surface a
    // subtle pill so users know we're polling without flashing a skeleton.
    return (
      <Pill tone="muted" variant="soft" withDot>
        REFRESHING
      </Pill>
    );
  }
  if (state === "error") {
    return (
      <span title={error?.message ?? ""} aria-label={error?.message ?? "Backend error"}>
        <Pill tone="warn" variant="soft" withDot={false}>
          DEMO · BACKEND ERROR
        </Pill>
      </span>
    );
  }
  if (state === "ok") {
    const elapsed = data?.elapsed_ms != null ? `${Math.round(data.elapsed_ms)}ms` : "";
    const sources = data?.sources && data.sources.length
      ? data.sources.slice(0, 2).join(",")
      : "live";
    return (
      <Pill tone="positive" variant="soft" withDot>
        LIVE · {sources}
        {elapsed ? ` · ${elapsed}` : ""}
      </Pill>
    );
  }
  return (
    <Pill tone="muted" variant="soft" withDot={false}>
      DEMO
    </Pill>
  );
}

/**
 * mergeLivePayload — overlay real sidecar response on top of the mock
 * template, preserving the mock's title/sub/cols/chips while replacing
 * data arrays whenever the backend returned a recognisable shape.
 *
 * Generic mappings cover most function codes; per-code adapters handle
 * the cases where the backend payload needs a non-trivial transform
 * (e.g. TRDH's exchange rows → Exchange/Status/Open(UTC)/Close(UTC)).
 *
 * Exported so the unit test in templates.live-overlay.test.tsx can
 * assert per-code adapters in isolation.
 */
export function mergeLivePayload(
  tpl: MockTemplate,
  code: string,
  payload: unknown,
): MockTemplate {
  if (!payload || typeof payload !== "object") return tpl;
  const p = payload as Record<string, unknown>;
  const merged: MockTemplate = { ...tpl };
  const handled = { table: false, feed: false, kpis: false };

  // Per-code adapters (run before generic mappings so they win).
  const adapter = PER_CODE_ADAPTERS[code.toUpperCase()];
  if (adapter) {
    const adapted = adapter(p);
    if (adapted.patch) Object.assign(merged, adapted.patch);
    handled.table = !!adapted.handledTable;
    handled.feed = !!adapted.handledFeed;
    handled.kpis = !!adapted.handledKpis;
  }

  // Generic mappings (skip when a per-code adapter already filled the slot).
  if (!handled.table) {
    const liveRows = extractLiveTableRows(p, tpl.tableCols);
    if (liveRows && liveRows.length > 0) {
      merged.tableRows = liveRows.slice(0, 100);
    }
  }
  if (!handled.feed) {
    const liveFeed = extractLiveFeed(p);
    if (liveFeed && liveFeed.length > 0) {
      merged.feed = liveFeed.slice(0, 25);
    }
  }
  if (!handled.kpis) {
    const liveKpis = extractLiveKpis(p);
    if (liveKpis && liveKpis.length > 0) {
      merged.kpis = liveKpis;
    }
  }
  return merged;
}

interface AdapterResult {
  patch: Partial<MockTemplate>;
  handledTable?: boolean;
  handledFeed?: boolean;
  handledKpis?: boolean;
}

type PerCodeAdapter = (payload: Record<string, unknown>) => AdapterResult;

const PER_CODE_ADAPTERS: Record<string, PerCodeAdapter> = {
  TRDH: (p) => {
    const rows = asObjectArray(p.rows);
    if (!rows.length) return { patch: {} };
    // For open exchanges show the countdown to close (state change that
    // actually matters to a trader watching the tape); for closed
    // exchanges show the countdown to next open.
    const tableRows: TableRow[] = rows.map((r) => {
      const isOpen = !!r.is_open_now;
      return {
        Exchange: String(r.exchange ?? r.code ?? "—"),
        Status: isOpen ? "OPEN" : "CLOSED",
        "Next event (UTC)": isOpen
          ? formatUtcTime(r.next_close_utc) ?? "—"
          : formatUtcTime(r.next_open_utc) ?? "—",
        Countdown: formatHoursDelta(isOpen ? r.hours_until_close : r.hours_until_open),
      };
    });
    const openCount = rows.filter((r) => !!r.is_open_now).length;
    return {
      patch: {
        sub: `${rows.length} exchange(s) · ${openCount} open now · live calendar`,
        tableCols: ["Exchange", "Status", "Next event (UTC)", "Countdown"],
        tableRows,
      },
      handledTable: true,
    };
  },
};

function extractLiveTableRows(
  payload: Record<string, unknown>,
  hint: string[] | undefined,
): TableRow[] | null {
  const candidates = [payload.rows, payload.items, payload.data, payload.results];
  for (const c of candidates) {
    if (Array.isArray(c) && c.length && typeof c[0] === "object" && c[0] !== null) {
      // Only treat as table-shape if rows look tabular (have plain string/num values).
      const sample = c[0] as Record<string, unknown>;
      const looksTabular =
        Object.values(sample).some((v) => typeof v === "string" || typeof v === "number");
      if (looksTabular) {
        return c.map((row) => toTableRow(row as Record<string, unknown>, hint));
      }
    }
  }
  return null;
}

function extractLiveFeed(payload: Record<string, unknown>): FeedEntry[] | null {
  const candidates = [
    payload.items,
    payload.articles,
    payload.headlines,
    payload.news,
    payload.feed,
  ];
  for (const c of candidates) {
    if (Array.isArray(c) && c.length && typeof c[0] === "object" && c[0] !== null) {
      const first = c[0] as Record<string, unknown>;
      const isArticle =
        "title" in first || "headline" in first || "summary" in first || "source" in first;
      if (isArticle) {
        return c.map((it) => toFeedEntry(it as Record<string, unknown>));
      }
    }
  }
  return null;
}

function extractLiveKpis(payload: Record<string, unknown>): KpiTile[] | null {
  const candidates = [payload.cards, payload.kpis, payload.stats];
  for (const c of candidates) {
    if (Array.isArray(c) && c.length && typeof c[0] === "object" && c[0] !== null) {
      return c.map((card) => toKpiTile(card as Record<string, unknown>));
    }
  }
  return null;
}

function toTableRow(row: Record<string, unknown>, hint: string[] | undefined): TableRow {
  const out: TableRow = {};
  // Prefer hinted columns when their names match real keys (case-insensitive).
  if (hint) {
    for (const col of hint) {
      const k = findKeyMatching(row, col);
      out[col] = stringifyCell(k != null ? row[k] : "");
    }
    if (Object.values(out).some((v) => v !== "")) return out;
  }
  // Fallback: take string/number scalars only, skip nested objects/arrays.
  for (const [k, v] of Object.entries(row)) {
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean" || v == null) {
      out[k] = stringifyCell(v);
    }
  }
  return out;
}

/**
 * BugHunt 2026-05-24: option-chain shorthand whitelist. Greek symbols
 * (Δ/Γ/Θ/ν/ρ/Λ/Φ) and short Latin keys (`IV`, `OI`, `Vol`, …) used to be
 * normalized to "" or collapse together (`IV` ↔ `Iv`, `Vol` clashing with
 * other 3-letter labels), causing live data to land in the wrong column
 * or to be dropped entirely. Anchoring the matcher in a whitelist keeps
 * each short identifier distinct and makes column matching deterministic.
 *
 * Both the template column name and the live key are mapped through the
 * same set of aliases. Keys are case-insensitive but the mapping is
 * symbol/letter aware (Greek letters preserved).
 */
const COLUMN_ALIASES: Record<string, string> = {
  // Greek letters → stable canonical ids (lowercase ASCII names).
  "Δ": "delta",
  delta: "delta",
  "Γ": "gamma",
  gamma: "gamma",
  "Θ": "theta",
  theta: "theta",
  "ν": "vega",
  vega: "vega",
  "ρ": "rho",
  rho: "rho",
  "Λ": "lambda",
  lambda: "lambda",
  // Short Latin column labels — keep `iv` vs `volume` vs `oi` distinct.
  iv: "iv",
  "implied vol": "iv",
  "impliedvol": "iv",
  oi: "open_interest",
  "open interest": "open_interest",
  "openinterest": "open_interest",
  "openint": "open_interest",
  vol: "volume",
  volume: "volume",
  // Misc shorthand commonly seen on tickets.
  px: "price",
  price: "price",
  qty: "qty",
  size: "size",
};

/**
 * Normalize a column / key name to a stable canonical identifier.
 *
 * Behaviour:
 *  - Greek letter glyphs (Δ, Γ, Θ, ν, ρ, Λ) are mapped to their lowercase
 *    English names (`delta`, `gamma`, …) so a template col named "Δ" and a
 *    backend field named "delta" both collapse to the same key.
 *  - Short Latin shorthand (`IV`, `OI`, `Vol`, `Px`, `Qty`, `Size`) is
 *    mapped through `COLUMN_ALIASES` so `IV` never collides with `Iv`
 *    and `Vol` never overlaps with `Volume` or anything else.
 *  - Everything else is lower-cased and stripped of non-alphanumerics so
 *    "Last close" matches "lastClose" / "LAST_CLOSE".
 */
export function normalizeColumnKey(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  // Whole-glyph match first (Greek letters / unicode glyphs).
  if (COLUMN_ALIASES[trimmed]) return COLUMN_ALIASES[trimmed];
  const lower = trimmed.toLowerCase();
  if (COLUMN_ALIASES[lower]) return COLUMN_ALIASES[lower];
  // Strip whitespace+punctuation but keep Unicode letters so non-ASCII
  // characters survive (Greek letters, accented column names).
  // Use \p{L} + \p{N} when available; fall back to ASCII-only otherwise.
  let collapsed: string;
  try {
    collapsed = lower.replace(/[^\p{L}\p{N}]/gu, "");
  } catch {
    collapsed = lower.replace(/[^a-z0-9]/g, "");
  }
  return COLUMN_ALIASES[collapsed] ?? collapsed;
}

function findKeyMatching(row: Record<string, unknown>, col: string): string | null {
  const normalized = normalizeColumnKey(col);
  if (!normalized) return null;
  for (const k of Object.keys(row)) {
    if (normalizeColumnKey(k) === normalized) return k;
  }
  return null;
}

function stringifyCell(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function toFeedEntry(item: Record<string, unknown>): FeedEntry {
  const time =
    pickString(item, ["time", "published_at", "publishedAt", "published", "date", "datetime", "ts"]) ??
    "";
  const source = pickString(item, ["source", "provider", "feed", "publisher"]) ?? "—";
  const title = pickString(item, ["title", "headline", "name"]) ?? "(untitled)";
  const summary = pickString(item, ["summary", "description", "snippet", "body"]);
  const tags = Array.isArray(item.tags)
    ? item.tags.filter((t) => typeof t === "string").map((t) => String(t))
    : undefined;
  const impactRaw = item.impact ?? item.importance_score ?? item.score;
  const impact =
    typeof impactRaw === "number" && Number.isFinite(impactRaw) ? Math.round(impactRaw) : undefined;
  const sentimentRaw = String(item.sentiment ?? item.tone ?? "").toLowerCase();
  const tone: FeedEntry["tone"] = sentimentRaw.startsWith("pos")
    ? "pos"
    : sentimentRaw.startsWith("neg")
      ? "neg"
      : sentimentRaw.startsWith("warn")
        ? "warn"
        : "neutral";
  return {
    source,
    time: formatFeedTime(time),
    title,
    summary,
    tags,
    impact,
    tone,
  };
}

function toKpiTile(card: Record<string, unknown>): KpiTile {
  const label = pickString(card, ["label", "name", "title"]) ?? "—";
  const valueRaw = card.value ?? card.amount ?? card.count;
  const value =
    typeof valueRaw === "number"
      ? Number.isInteger(valueRaw)
        ? String(valueRaw)
        : valueRaw.toFixed(2)
      : valueRaw != null
        ? String(valueRaw)
        : "—";
  const toneRaw = String(card.tone ?? "").toLowerCase();
  const tone: KpiTile["tone"] = toneRaw === "pos" || toneRaw === "neg" || toneRaw === "warn"
    ? (toneRaw as KpiTile["tone"])
    : "neutral";
  const sub = pickString(card, ["sub", "caption", "subtitle"]);
  return { label, value, tone, sub };
}

function pickString(
  obj: Record<string, unknown>,
  keys: readonly string[],
): string | undefined {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v.length) return v;
    if (typeof v === "number" && Number.isFinite(v)) return String(v);
  }
  return undefined;
}

function asObjectArray(v: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(v)) return [];
  return v.filter((r) => r != null && typeof r === "object") as Array<Record<string, unknown>>;
}

function formatUtcTime(iso: unknown): string | null {
  if (typeof iso !== "string" || iso.length < 10) return null;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toISOString().slice(11, 16);
  } catch {
    return null;
  }
}

function formatHoursDelta(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (n <= 0) return "now";
  if (n < 1) return `${Math.round(n * 60)}m`;
  if (n < 48) return `${n.toFixed(1)}h`;
  return `${Math.round(n / 24)}d`;
}

function formatFeedTime(value: string): string {
  if (!value) return "";
  // Try ISO -> short relative or HH:MM
  try {
    const d = new Date(value);
    if (!Number.isNaN(d.getTime())) {
      return d.toISOString().slice(11, 16) + "Z";
    }
  } catch {
    // fall through
  }
  return value.slice(0, 16);
}
