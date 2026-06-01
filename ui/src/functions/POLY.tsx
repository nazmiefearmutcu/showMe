/**
 * POLY — Prediction markets (Polymarket-style).
 *
 * Surfaces prediction-market questions on real-world events (elections,
 * policy, crypto milestones) as cards with YES/NO probability-fill bars,
 * reported volume / liquidity, and a close date. Click a card to open the
 * underlying market.
 *
 * The backend (engine/functions/misc/poly.py) is keyring-gated: with no
 * Polymarket / Gamma API credential configured it returns
 * `data_mode='not_configured'` with `rows=[]` and an explicit warning —
 * never synthetic markets. This pane surfaces that mode honestly: a
 * `not configured` / `cached` pill instead of a fake `live` tape, plus the
 * provider warning, and an Empty state that names the missing credential.
 */
import { useMemo, type CSSProperties } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
  StatusDivider,
  StatusSection,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import { useVisibilityTick } from "@/lib/useVisibilityTick";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

// ── Real backend payload shape (engine/functions/misc/poly.py + seed) ────
// One row per market outcome. The seed table_schema declares:
//   market_id, question, outcome, price (0-1), implied_prob (%),
//   liquidity_usd, end_date, source. card_schema: market_count,
//   total_liquidity_usd, top_market, data_mode, as_of.
interface PolyRow {
  market_id?: string | number;
  question?: string;
  outcome?: string;
  price?: number; // on-chain mid in [0, 1]
  implied_prob?: number; // price * 100
  liquidity_usd?: number | null;
  volume_usd?: number | null;
  end_date?: string | null;
  source?: string;
  url?: string | null;
  category?: string | null;
}

interface PolyCard {
  key?: string;
  label?: string;
  value?: number | string | null;
  unit?: string;
}

interface PolyPayload {
  data_mode?: string;
  rows?: PolyRow[];
  cards?: PolyCard[];
  market_count?: number;
  total_liquidity_usd?: number;
  top_market?: string;
  as_of?: string;
  methodology?: string;
  warnings?: string[];
}

// A market groups its outcome rows (YES / NO / candidates) under one
// question so each card renders a single question with stacked odds bars.
interface PolyMarket {
  id: string;
  question: string;
  category?: string | null;
  url?: string | null;
  endDate?: string | null;
  liquidity: number;
  outcomes: { label: string; prob: number }[];
}

const SORTS = [
  { id: "volume", label: "Liquidity" },
  { id: "closes", label: "Closes" },
  { id: "prob", label: "Top odds" },
] as const;
type SortId = (typeof SORTS)[number]["id"];
const SORT_IDS = SORTS.map((s) => s.id);

const VIEWS = [
  { id: "cards", label: "Cards" },
  { id: "table", label: "Table" },
] as const;
type ViewId = (typeof VIEWS)[number]["id"];
const VIEW_IDS = VIEWS.map((v) => v.id);

const REFRESH_MS = 60_000;

export function POLYPane({ code }: FunctionPaneProps) {
  const [sort, setSort] = usePersistentOption<SortId>(
    "showme.poly-sort",
    SORT_IDS,
    "volume",
  );
  const [view, setView] = usePersistentOption<ViewId>(
    "showme.poly-view",
    VIEW_IDS,
    "cards",
  );
  // Bundle D / PERF-04. Visibility-aware poll.
  const tick = useVisibilityTick(REFRESH_MS);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { status: "open", min_liquidity_usd: 10_000, tick },
  });

  const payload = useMemo<PolyPayload>(
    () =>
      data?.data && typeof data.data === "object" && !Array.isArray(data.data)
        ? (data.data as PolyPayload)
        : {},
    [data?.data],
  );

  const dataMode = payload.data_mode ?? "not_configured";
  const isLive = dataMode === "live";
  const isNotConfigured = dataMode === "not_configured";
  const warningsList = useMemo(() => {
    const fromPayload = Array.isArray(payload.warnings) ? payload.warnings : [];
    const fromEnvelope = Array.isArray(data?.warnings) ? data?.warnings : [];
    return [...fromPayload, ...fromEnvelope].map((w) => String(w));
  }, [payload.warnings, data?.warnings]);

  const rawRows = useMemo<PolyRow[]>(
    () => (Array.isArray(payload.rows) ? payload.rows : []),
    [payload.rows],
  );

  // Group outcome rows into one market per question, then sort.
  const markets = useMemo<PolyMarket[]>(() => {
    const byQuestion = new Map<string, PolyMarket>();
    for (const r of rawRows) {
      const question = r.question ?? "Untitled market";
      const id = String(r.market_id ?? question);
      const key = `${id}::${question}`;
      let m = byQuestion.get(key);
      if (!m) {
        m = {
          id,
          question,
          category: r.category,
          url: r.url,
          endDate: r.end_date,
          liquidity: 0,
          outcomes: [],
        };
        byQuestion.set(key, m);
      }
      const prob =
        typeof r.implied_prob === "number"
          ? r.implied_prob
          : typeof r.price === "number"
            ? r.price * 100
            : 0;
      m.outcomes.push({ label: r.outcome ?? "YES", prob });
      const liq = numeric(r.liquidity_usd ?? r.volume_usd);
      if (liq != null) m.liquidity += liq;
      if (!m.url && r.url) m.url = r.url;
      if (!m.category && r.category) m.category = r.category;
      if (!m.endDate && r.end_date) m.endDate = r.end_date;
    }
    // Ensure each market shows a YES + NO pair (synthesize NO from YES only
    // when the feed gave a single binary outcome — never fabricate a third).
    const list = Array.from(byQuestion.values()).map((m) => {
      if (m.outcomes.length === 1) {
        const yes = m.outcomes[0];
        const noLabel = /no/i.test(yes.label) ? "YES" : "NO";
        return {
          ...m,
          outcomes: [yes, { label: noLabel, prob: Math.max(0, 100 - yes.prob) }],
        };
      }
      return m;
    });

    list.sort((a, b) => {
      if (sort === "closes") {
        const da = a.endDate ? Date.parse(a.endDate) : Infinity;
        const db = b.endDate ? Date.parse(b.endDate) : Infinity;
        return da - db;
      }
      if (sort === "prob") {
        return topProb(b) - topProb(a);
      }
      return b.liquidity - a.liquidity;
    });
    return list;
  }, [rawRows, sort]);

  const totalLiquidity =
    typeof payload.total_liquidity_usd === "number"
      ? payload.total_liquidity_usd
      : markets.reduce((acc, m) => acc + m.liquidity, 0);
  const marketCount =
    typeof payload.market_count === "number"
      ? payload.market_count
      : markets.length;

  const utcStamp = useMemo(() => new Date().toISOString().slice(11, 16), [tick]);

  const cols = useMemo<DataGridColumn<PolyMarket>[]>(
    () => [
      {
        key: "question",
        header: "Market",
        render: (m) => (
          <button
            type="button"
            onClick={() => openMarket(m.url)}
            disabled={!m.url}
            style={{ ...questionLinkStyle, cursor: m.url ? "pointer" : "default" }}
            title={m.url ? "Open market" : undefined}
          >
            {m.question}
          </button>
        ),
      },
      {
        key: "yes",
        header: "YES",
        numeric: true,
        width: 90,
        render: (m) => (
          <ProbCell value={outcomeProb(m, "yes")} tone="var(--positive)" />
        ),
      },
      {
        key: "no",
        header: "NO",
        numeric: true,
        width: 90,
        render: (m) => (
          <ProbCell value={outcomeProb(m, "no")} tone="var(--negative)" />
        ),
      },
      {
        key: "liquidity",
        header: "Liquidity",
        numeric: true,
        width: 104,
        render: (m) => <span style={mutedNumStyle}>{fmtUsd(m.liquidity)}</span>,
      },
      {
        key: "endDate",
        header: "Closes",
        width: 132,
        render: (m) => (
          <span style={mutedNumStyle}>
            {fmtDate(m.endDate)}
            {daysLeft(m.endDate) != null ? (
              <span style={daysTagStyle}>{daysLeft(m.endDate)}d</span>
            ) : null}
          </span>
        ),
      },
      {
        key: "category",
        header: "Topic",
        width: 110,
        render: (m) =>
          m.category ? (
            <Pill tone="muted" variant="soft" withDot={false}>
              {m.category}
            </Pill>
          ) : (
            "—"
          ),
      },
    ],
    [],
  );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Prediction markets"
          subtitle={`${marketCount} markets · sort ${sort} · poll ${REFRESH_MS / 1000}s · ${dataMode}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {markets.length} mkt
              </Pill>
              <Pill tone="accent" variant="soft" withDot={false}>
                {utcStamp} UTC
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live" : dataMode.replace(/_/g, " ")}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div style={tabBarStyle}>
          <Tabs
            variant="segmented"
            items={VIEWS.map((v) => ({ id: v.id, label: v.label }))}
            active={view}
            onChange={(id) => setView(id as ViewId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={320} />
          ) : state === "error" ? (
            <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
          ) : markets.length === 0 ? (
            <Empty
              title={
                isNotConfigured ? "Prediction markets not configured" : "No open markets"
              }
              body={
                isNotConfigured
                  ? "POLY requires a Polymarket / Gamma API credential in the keyring. No synthetic markets are shown."
                  : warningsList[0] ?? "No open prediction markets matched the filter."
              }
              icon="◇"
            />
          ) : (
            <div className="u-grid-gap-14">
              {!isLive ? (
                <section style={noticeStyle}>
                  <strong className="u-text-warn">
                    {dataMode.replace(/_/g, " ")}
                  </strong>
                  <span className="u-text-secondary">
                    {isNotConfigured
                      ? "Polymarket / Gamma credential not configured — values below are a labelled reference snapshot, not a live on-chain tape."
                      : "Provider returned a labelled fallback mode. Treat odds as delayed reference, not live tape."}
                  </span>
                </section>
              ) : null}

              {warningsList.length ? (
                <section style={warningBox}>
                  <strong className="u-text-warn">Provider warnings</strong>
                  <ul style={warningList}>
                    {warningsList.slice(0, 3).map((w, i) => (
                      <li key={i} className="u-text-secondary">
                        {w}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section style={kpiGrid} aria-label="POLY KPI ribbon">
                <StatCard
                  label="Markets"
                  value={String(marketCount)}
                  caption={`AS OF ${payload.as_of ?? `${utcStamp} UTC`}`}
                  tone="neutral"
                />
                <StatCard
                  label="Total liquidity"
                  value={fmtUsd(totalLiquidity)}
                  caption={`${markets.length} questions`}
                  tone="neutral"
                />
                <StatCard
                  label="Top market"
                  value={
                    payload.top_market ?? truncate(markets[0]?.question ?? "—", 22)
                  }
                  caption={
                    markets[0]
                      ? `${outcomeProb(markets[0], "yes").toFixed(0)}% YES · ${fmtUsd(markets[0].liquidity)}`
                      : "—"
                  }
                  tone="positive"
                />
              </section>

              <div style={sortBarStyle}>
                <span style={sortLabelStyle}>Sort</span>
                <Tabs
                  variant="segmented"
                  items={SORTS.map((s) => ({ id: s.id, label: s.label }))}
                  active={sort}
                  onChange={(id) => setSort(id as SortId)}
                />
              </div>

              {view === "cards" ? (
                <div style={cardGridStyle}>
                  {markets.map((m) => (
                    <MarketCard key={`${m.id}-${m.question}`} market={m} />
                  ))}
                </div>
              ) : (
                <DataGrid
                  columns={cols}
                  rows={markets}
                  rowKey={(m) => `${m.id}-${m.question}`}
                  density="compact"
                  onRowDoubleClick={(m) => openMarket(m.url)}
                />
              )}

              {payload.methodology ? (
                <section style={methodPanel}>
                  <div style={metaLabel}>Methodology</div>
                  <p style={methodText}>{payload.methodology}</p>
                </section>
              ) : null}
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection
            label="provider"
            value={data?.sources?.join(", ") || "polymarket"}
          />
          <StatusDivider />
          <StatusSection label="mode" value={dataMode} tone={isLive ? "positive" : "warn"} />
          <StatusDivider />
          <StatusSection label="poll" value={`${REFRESH_MS / 1000}s`} />
          <StatusDivider />
          <StatusSection label="markets" value={markets.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

// ── card ──────────────────────────────────────────────────────────────
function MarketCard({ market }: { market: PolyMarket }) {
  const days = daysLeft(market.endDate);
  const yes = outcomeProb(market, "yes");
  const no = outcomeProb(market, "no");
  return (
    <button
      type="button"
      onClick={() => openMarket(market.url)}
      disabled={!market.url}
      title={market.url ? "Open market" : undefined}
      style={{ ...cardStyle, cursor: market.url ? "pointer" : "default" }}
    >
      <div style={cardTopStyle}>
        <span style={questionStyle}>{market.question}</span>
        {market.category ? (
          <Pill tone="accent" variant="soft" withDot={false}>
            {market.category}
          </Pill>
        ) : null}
      </div>

      <OddsBar label="YES" value={yes} tone="var(--positive)" />
      <OddsBar label="NO" value={no} tone="var(--negative)" />

      <div style={metaRowStyle}>
        <span>Liq {fmtUsd(market.liquidity)}</span>
        <span>
          {fmtDate(market.endDate)}
          {days != null && days >= 0 ? ` · ${days}d` : ""}
        </span>
      </div>
    </button>
  );
}

function OddsBar({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  const intensity = 0.3 + Math.min(value / 100, 1) * 0.55;
  return (
    <div style={oddsRowStyle}>
      <div style={{ ...oddsLabelStyle, color: tone }}>
        <span>{label}</span>
        <span>{pct.toFixed(1)}%</span>
      </div>
      <div style={barTrackStyle} aria-hidden>
        <div
          style={{
            ...barFillStyle,
            width: `${pct}%`,
            background: `color-mix(in srgb, ${tone} ${(intensity * 100).toFixed(0)}%, transparent)`,
          }}
        />
      </div>
    </div>
  );
}

function ProbCell({ value, tone }: { value: number; tone: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <span style={probCellWrap}>
      <span style={probCellTrack} aria-hidden>
        <span
          style={{
            ...barFillStyle,
            width: `${pct}%`,
            background: `color-mix(in srgb, ${tone} 55%, transparent)`,
          }}
        />
      </span>
      <span style={{ ...probCellLabel, color: tone }}>{pct.toFixed(0)}%</span>
    </span>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────
function topProb(m: PolyMarket): number {
  return m.outcomes.reduce((max, o) => Math.max(max, o.prob), 0);
}

function outcomeProb(m: PolyMarket, side: "yes" | "no"): number {
  const wantYes = side === "yes";
  const match = m.outcomes.find((o) =>
    wantYes ? /^y(es)?$/i.test(o.label) : /^n(o)?$/i.test(o.label),
  );
  if (match) return match.prob;
  // Binary fallback: first outcome = YES, complement = NO.
  const first = m.outcomes[0]?.prob ?? 0;
  return wantYes ? first : Math.max(0, 100 - first);
}

function openMarket(url?: string | null): void {
  if (!url) return;
  window.open(url, "_blank", "noopener,noreferrer");
}

function numeric(v: unknown): number | null {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmtUsd(v: number | undefined | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
}

function fmtDate(d: string | undefined | null): string {
  if (!d) return "—";
  const parsed = new Date(d);
  if (Number.isNaN(parsed.getTime())) return String(d).slice(0, 10);
  return parsed.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function daysLeft(d: string | undefined | null): number | null {
  if (!d) return null;
  const parsed = new Date(d);
  if (Number.isNaN(parsed.getTime())) return null;
  return Math.round((parsed.getTime() - Date.now()) / 86_400_000);
}

function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

// ── styles ──────────────────────────────────────────────────────────────
const tabBarStyle: CSSProperties = {
  padding: "8px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const sortBarStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
};

const sortLabelStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
};

const cardGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
  gap: 10,
};

const cardStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 9,
  padding: "11px 13px",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  color: "var(--text-primary)",
  textAlign: "left",
  width: "100%",
  font: "inherit",
  transition: "border-color var(--motion-base), transform var(--motion-base)",
};

const cardTopStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 8,
};

const questionStyle: CSSProperties = {
  fontSize: 12.5,
  fontWeight: 600,
  lineHeight: 1.32,
  color: "var(--text-display)",
};

const oddsRowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 5,
};

const oddsLabelStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  fontVariantNumeric: "tabular-nums",
};

const barTrackStyle: CSSProperties = {
  position: "relative",
  height: 7,
  borderRadius: 999,
  background: "var(--surface-3)",
  overflow: "hidden",
};

const barFillStyle: CSSProperties = {
  position: "absolute",
  top: 0,
  left: 0,
  height: "100%",
  borderRadius: 999,
  transition: "width var(--motion-base)",
};

const metaRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: 10,
  color: "var(--text-mute)",
  letterSpacing: "0.02em",
};

const questionLinkStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  color: "var(--text-secondary)",
  font: "inherit",
  fontWeight: 600,
  padding: 0,
  textAlign: "left",
};

const probCellWrap: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  width: "100%",
};

const probCellTrack: CSSProperties = {
  position: "relative",
  flex: "1 1 auto",
  height: 7,
  background: "var(--surface-3)",
  borderRadius: 999,
  overflow: "hidden",
};

const probCellLabel: CSSProperties = {
  flex: "0 0 auto",
  width: 36,
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  textAlign: "right",
};

const mutedNumStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-secondary)",
  display: "inline-flex",
  alignItems: "baseline",
  gap: 5,
};

const daysTagStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.04em",
};

const noticeStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
  fontSize: 12,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  gap: 4,
};

const warningList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const methodPanel: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--surface-2)",
};

const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  marginBottom: 6,
};

const methodText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.5,
  fontSize: 12,
};
