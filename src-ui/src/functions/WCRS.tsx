/**
 * WCRS — World currency cross rates.
 *
 * Bloomberg `WCRS<GO>` analogue: matrix of cross rates between G10 +
 * key emerging market currencies. The sidecar's `/api/fn/WCRS` returns
 * either a flat list of pairs or a 2-D matrix; we accept both.
 */
import { useEffect, useMemo, useState } from "react";
import {
  ChangeText,
  DataGrid,
  type DataGridColumn,
  Empty,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Skeleton,
  Tabs,
} from "@/design-system";
import { useFunction } from "@/lib/useFunction";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

interface CrossRate {
  base?: string;
  quote?: string;
  pair?: string;
  rate?: number;
  bid?: number;
  ask?: number;
  change?: number;
  change_pct?: number;
  ts?: string;
}

const BASES = [
  { id: "USD", label: "USD" },
  { id: "EUR", label: "EUR" },
  { id: "GBP", label: "GBP" },
  { id: "JPY", label: "JPY" },
  { id: "TRY", label: "TRY" },
] as const;
type BaseId = (typeof BASES)[number]["id"];
const BASE_IDS = BASES.map((b) => b.id);

const REFRESH_MS = 30_000;

export function WCRSPane({ code }: FunctionPaneProps) {
  const [base, setBase] = usePersistentOption<BaseId>(
    "showme.wcrs-base",
    BASE_IDS,
    "USD",
  );
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  const { state, data, error, refetch } = useFunction<unknown>({
    code,
    params: { base, tick },
  });

  const rows = useMemo(() => {
    const list = normalizeRows(data?.data);
    // Filter the grid to crosses that involve the active base on either side.
    return list.filter((r) => {
      const b = r.base?.toUpperCase();
      const q = r.quote?.toUpperCase();
      return b === base || q === base;
    });
  }, [data, base]);

  const cols = useMemo<DataGridColumn<CrossRate>[]>(
    () => [
      {
        key: "pair",
        header: "Pair",
        width: 100,
        render: (r) => (
          <span style={{ color: "var(--accent)", fontWeight: 600 }}>
            {fmtPair(r)}
          </span>
        ),
      },
      {
        key: "rate",
        header: "Rate",
        numeric: true,
        width: 110,
        render: (r) => fmtRate(r.rate ?? r.bid),
      },
      {
        key: "bid",
        header: "Bid",
        numeric: true,
        width: 100,
        render: (r) => fmtRate(r.bid),
      },
      {
        key: "ask",
        header: "Ask",
        numeric: true,
        width: 100,
        render: (r) => fmtRate(r.ask),
      },
      {
        key: "spread",
        header: "Spread (pips)",
        numeric: true,
        width: 110,
        render: (r) => fmtPips(r),
      },
      {
        key: "change_pct",
        header: "Δ %",
        numeric: true,
        width: 90,
        render: (r) =>
          r.change_pct != null ? (
            <ChangeText value={r.change_pct} digits={2} suffix="%" />
          ) : (
            "—"
          ),
      },
    ],
    [],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="World currency cross rates"
          subtitle={`${rows.length} pair(s) · base ${base} · ${REFRESH_MS / 1000}s refresh`}
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={state} />
              <RefreshButton loading={state === "loading"} onClick={refetch} />
            </FunctionControlGroup>
          }
        />
        <div
          style={{
            padding: "8px 14px",
            borderBottom: "1px solid var(--border-subtle)",
            background: "var(--bg-elev-2)",
          }}
        >
          <Tabs
            variant="segmented"
            items={BASES.map((b) => ({ id: b.id, label: b.label }))}
            active={base}
            onChange={(id) => setBase(id as BaseId)}
          />
        </div>
        <PaneBody>
          {state === "loading" || state === "idle" ? (
            <Skeleton height={300} />
          ) : state === "error" ? (
            <Empty
              title="Function error"
              body={error?.message ?? "—"}
              icon="!"
            />
          ) : rows.length === 0 ? (
            <Empty title="No crosses" body={`No WCRS rows for base ${base}.`} />
          ) : (
            <DataGrid
              columns={cols}
              rows={rows}
              rowKey={(r, i) => fmtPair(r) + i}
              density="compact"
            />
          )}
        </PaneBody>
        <PaneFooter>
          <span>elapsed · {data?.elapsed_ms?.toFixed(0) ?? "—"} ms</span>
          <span>base · {base}</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}

function normalizeRows(payload: unknown): CrossRate[] {
  if (!payload) return [];
  if (Array.isArray(payload)) return payload as CrossRate[];
  if (typeof payload === "object") {
    const o = payload as Record<string, unknown>;
    const items = o.pairs ?? o.rates ?? o.rows ?? o.items ?? null;
    if (Array.isArray(items)) return items as CrossRate[];
    const matrix = o.matrix;
    // Matrix shape: { matrix: { USD: { EUR: 0.93, JPY: 156.20 }, ... } }
    if (matrix && typeof matrix === "object") {
      const out: CrossRate[] = [];
      for (const [base, qs] of Object.entries(matrix as Record<string, unknown>)) {
        if (qs && typeof qs === "object") {
          for (const [quote, rate] of Object.entries(qs as Record<string, unknown>)) {
            if (typeof rate === "number") out.push({ base, quote, rate });
          }
        }
      }
      return out;
    }
  }
  return [];
}

function fmtPair(r: CrossRate): string {
  if (r.pair) return r.pair;
  if (r.base && r.quote) return `${r.base}${r.quote}`;
  return "—";
}

function fmtRate(v: number | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  // FX precision: 2 dp for JPY-quoted, 4 dp otherwise. Quick heuristic
  // by magnitude (>20 → JPY-style).
  const dp = Math.abs(v) > 20 ? 2 : 4;
  return v.toLocaleString(undefined, {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  });
}

function fmtPips(r: CrossRate): string {
  if (r.bid == null || r.ask == null) return "—";
  const spread = r.ask - r.bid;
  const pip = Math.abs(spread * 10000);
  return pip.toFixed(1);
}
