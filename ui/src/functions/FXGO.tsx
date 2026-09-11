/**
 * FXGO — FX Trading board (dealing grid).
 *
 * Header: board honesty pill + focused-pair pill + status + refresh.
 * Body: honesty strip (ALWAYS: indicative quotes, never executable) +
 * KPI ribbon (pairs returned, focused mid, focused change, board as-of) +
 * the two-way quote board table (bid/ask/mid/spread/change vs prev close).
 *
 * DATA HONESTY (the FXGO defect): the backend labels the board
 * `data_mode=live_exchange` even when most pairs 404 at the provider and
 * only one row survives. This pane recomputes the honest mode from the
 * payload: provider warnings / a partial board / a provider_unavailable
 * status downgrade the pill to "reference · degraded" and raise a
 * prominent non-executable banner. Bid/ask are a synthetic 1-pip spread
 * around a delayed Yahoo spot — they are NEVER executable venue quotes,
 * so the board carries an indicative-only strip in every state. There is
 * deliberately no order ticket: order routing needs a connected FX
 * broker, which the keyless backend does not provide.
 */
import { useMemo, useState, type CSSProperties } from "react";
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
} from "@/design-system";
import { formatNumberPlain } from "@/lib/format";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface FXGORow {
  pair?: string;
  symbol?: string;
  bid?: number;
  ask?: number;
  mid?: number;
  spread?: number;
  spread_pips?: number;
  change?: number;
  change_pct?: number;
  previous_close?: number;
}

interface FXGOData {
  status?: string;
  reason?: string;
  warning?: string;
  rows?: FXGORow[];
  data_mode?: string;
  as_of?: string;
  methodology?: string;
  next_actions?: string[];
}

/** Board size the backend requests by default (majors + key crosses). */
const EXPECTED_BOARD_PAIRS = 10;

export function FXGOPane({ code, symbol }: FunctionPaneProps) {
  // The board is a grid of pairs — never narrow the fetch to one symbol,
  // otherwise a navigated-in symbol would collapse the board to one row.
  const { state, data, error, refetch } = useFunction<FXGOData>({ code });
  const [focusedPair, setFocusedPair] = useState<string | null>(null);

  const payload = data?.data;
  const rows: FXGORow[] = useMemo(() => payload?.rows ?? [], [payload]);
  const status = payload?.status ?? "—";
  const providerWarnings = data?.warnings ?? [];

  const focusFromSymbol = normalizePair(symbol);
  const focused =
    focusedPair ??
    (focusFromSymbol && rows.some((r) => r.pair === focusFromSymbol)
      ? focusFromSymbol
      : rows[0]?.pair ?? null);
  const focusedRow = rows.find((r) => r.pair === focused) ?? null;

  // ── honesty recomputation ────────────────────────────────────────────
  // The backend overstates health: a board missing most of its pairs (or
  // carrying provider error warnings) still says `live_exchange`. Treat
  // any provider warning, explicit warning field, or partial board as
  // degraded → reference quotes.
  const partialBoard = rows.length > 0 && rows.length < EXPECTED_BOARD_PAIRS;
  const degraded =
    status === "provider_unavailable" ||
    partialBoard ||
    payload?.warning != null ||
    providerWarnings.some((w) => /error|unavailable|404|rate/i.test(w));
  const modeLabel =
    status === "provider_unavailable"
      ? "reference · unavailable"
      : degraded
        ? "reference · degraded"
        : (payload?.data_mode ?? "—");

  const asOf = formatAsOf(payload?.as_of);

  const COLS: DataGridColumn<FXGORow>[] = useMemo(
    () => [
      {
        key: "pair",
        header: "Pair",
        width: 110,
        render: (r) => (
          <span style={monoStrongStyle}>{r.pair ?? r.symbol ?? "—"}</span>
        ),
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        width: 116,
        render: (r) => <span style={monoMutedStyle}>{fmtFx(r.bid)}</span>,
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        width: 116,
        render: (r) => <span style={monoMutedStyle}>{fmtFx(r.ask)}</span>,
      },
      {
        key: "mid",
        header: "Mid",
        numeric: true,
        width: 116,
        render: (r) => <span style={monoStrongStyle}>{fmtFx(r.mid)}</span>,
      },
      {
        key: "spread_pips",
        header: "Spread (pips)",
        numeric: true,
        width: 122,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtNum(r.spread_pips, 2)}</span>
        ),
      },
      {
        key: "change_pct",
        header: "Chg %",
        numeric: true,
        width: 104,
        render: (r) => (
          <span
            style={{
              ...monoPrimaryStyle,
              color: changeColor(r.change_pct),
            }}
          >
            {fmtSigned(r.change_pct, 2)}%
          </span>
        ),
      },
      {
        key: "previous_close",
        header: "Prev close",
        numeric: true,
        width: 122,
        render: (r) => (
          <span style={monoMutedStyle}>{fmtFx(r.previous_close)}</span>
        ),
      },
    ],
    [],
  );

  const body =
    state === "loading" || state === "idle" ? (
      <div className="u-grid-gap-8">
        <Skeleton height={56} />
        <Skeleton height={20} />
        <Skeleton height={20} />
        <Skeleton height={20} width="80%" />
      </div>
    ) : state === "error" ? (
      <Empty
        title="Function error"
        body={error?.message ?? "—"}
        icon="!"
        action={
          <button onClick={refetch} className="btn">
            Retry
          </button>
        }
      />
    ) : status === "provider_unavailable" || rows.length === 0 ? (
      <div className="u-grid-gap-14">
        <div role="alert" style={honestyBannerStyle} aria-label="Non-executable quotes">
          Reference quotes only — NOT executable. No order ticket.
        </div>
        <Empty
          title="FX spot board unavailable"
          body={
            payload?.reason ??
            payload?.warning ??
            "The keyless FX provider returned no quotes (likely rate-limited). Nothing is fabricated while it is down."
          }
          icon="∅"
          action={
            <button onClick={refetch} className="btn">
              Retry
            </button>
          }
        />
      </div>
    ) : (
      <div className="u-grid-gap-14">
        <div
          role="status"
          style={degraded ? degradedBannerStyle : indicativeStripStyle}
          aria-label="Quote mode notice"
        >
          {degraded
            ? `DEGRADED BOARD — ${rows.length} of ${EXPECTED_BOARD_PAIRS} pairs returned. Quotes are REFERENCE/INDICATIVE (delayed provider spot + synthetic spread), NOT executable.`
            : "Indicative quotes only — synthetic spread around a delayed provider spot. NOT an executable venue; no order routing."}
          {providerWarnings.length > 0
            ? ` Provider: ${providerWarnings[0].slice(0, 160)}`
            : ""}
        </div>
        <section style={kpiGridStyle} aria-label="FXGO KPI ribbon">
          <StatCard
            label="Pairs on board"
            value={`${rows.length}/${EXPECTED_BOARD_PAIRS}`}
            caption={degraded ? "DEGRADED COVERAGE" : "FULL BOARD"}
            tone={degraded ? "negative" : "neutral"}
          />
          <StatCard
            label={focusedRow?.pair ?? "Focused pair"}
            value={fmtFx(focusedRow?.mid)}
            caption={`BID ${fmtFx(focusedRow?.bid)} · ASK ${fmtFx(focusedRow?.ask)}`}
            tone="neutral"
          />
          <StatCard
            label="Focused change"
            value={`${fmtSigned(focusedRow?.change_pct, 2)}%`}
            caption={`PREV CLOSE ${fmtFx(focusedRow?.previous_close)}`}
            tone={
              (focusedRow?.change_pct ?? 0) >= 0 ? "positive" : "negative"
            }
          />
          <StatCard
            label="Board as-of"
            value={asOf}
            caption={modeLabel.toUpperCase()}
            tone={degraded ? "negative" : "neutral"}
          />
        </section>
        <DataGrid
          columns={COLS}
          rows={rows}
          rowKey={(r, i) => `${r.pair ?? r.symbol ?? "pair"}-${i}`}
          density="compact"
          ariaLabel="FXGO dealing board"
          onRowClick={(r) => setFocusedPair(r.pair ?? r.symbol ?? null)}
        />
      </div>
    );

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="FX Trading Board"
          subtitle={`${rows.length} pairs · indicative two-way quotes · ${asOf}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="warn" variant="soft" withDot={false}>
                indicative · not executable
              </Pill>
              <Pill
                tone={degraded ? "negative" : "positive"}
                variant="soft"
                aria-label="Board data mode"
              >
                {modeLabel}
              </Pill>
              {focused ? (
                <Pill tone="muted" variant="soft" withDot={false}>
                  focus {focused}
                </Pill>
              ) : null}
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh dealing board"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>{body}</PaneBody>
        <PaneFooter>
          <StatusSection
            label="sources"
            value={data?.sources?.join(", ") || "—"}
          />
          <StatusDivider />
          <StatusSection label="mode" value={modeLabel} tone="accent" />
          <StatusDivider />
          <StatusSection label="pairs" value={rows.length} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${data?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection label="as-of" value={asOf} />
        </PaneFooter>
      </Pane>
    </div>
  );
}

/* ── helpers ───────────────────────────────────────────────────────── */

/** Mirror of the backend pair normalizer: 6 alpha letters or nothing. */
function normalizePair(raw: string | undefined): string | null {
  if (!raw) return null;
  const value = raw.toUpperCase().replace(/[/\s=X-]/g, "");
  if (value.length >= 6 && /^[A-Z]{6}$/.test(value.slice(0, 6))) {
    return value.slice(0, 6);
  }
  return null;
}

function formatAsOf(iso: string | undefined): string {
  if (!iso) return "—";
  const cut = iso.slice(0, 16).replace("T", " ");
  return cut || "—";
}

function fmtFx(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.abs(v) >= 100 ? v.toFixed(3) : v.toFixed(5);
}

function fmtNum(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return formatNumberPlain(v, digits);
}

function fmtSigned(v: number | null | undefined, digits: number): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
}

function changeColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-mute)";
  if (v > 0) return "var(--positive)";
  if (v < 0) return "var(--negative)";
  return "var(--text-primary)";
}

/* ── styles ────────────────────────────────────────────────────────── */

const kpiGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
};

const indicativeStripStyle: CSSProperties = {
  border: "1px solid var(--border, var(--text-mute))",
  color: "var(--text-secondary)",
  fontSize: "var(--font-size-sm)",
  padding: "6px 8px",
  fontFamily: "JetBrains Mono, monospace",
};

const degradedBannerStyle: CSSProperties = {
  ...indicativeStripStyle,
  border: "1px solid var(--negative, var(--text-mute))",
  color: "var(--negative, var(--text-secondary))",
  fontWeight: 600,
};

const honestyBannerStyle: CSSProperties = {
  ...indicativeStripStyle,
  border: "1px solid var(--negative, var(--text-mute))",
  color: "var(--negative, var(--text-secondary))",
  fontWeight: 600,
};

const monoStrongStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
  fontWeight: 600,
};

const monoPrimaryStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
};

const monoMutedStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-mute)",
};
