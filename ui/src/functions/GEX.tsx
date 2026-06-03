/**
 * GEX — Dealer gamma exposure pane (Session 16 BugHunt).
 *
 * Before this pane existed, GEX fell through to the static
 * `Design` export Pro mock which renders thirteen hard-coded
 * strikes around $940 regardless of the selected symbol. The backend
 * has had a real `/api/fn/GEX` route since the engine landed
 * (`backend/showme/engine/functions/derivative/gex.py`), but the UI
 * never consumed it. This pane closes that gap: it calls the function
 * registry with `live_options: true` so the backend pulls live yfinance
 * options chains and runs the Black-Scholes per-strike gamma exposure
 * model. When yfinance is unreachable we degrade to the reference
 * model and surface the warning in the load-state pill.
 *
 * Visual structure mirrors the ProGex bar chart (call bars right of
 * the zero line, put bars left) but every value is token-driven and
 * theme-aware so Papyrus / Matrix / custom presets propagate.
 */
import { useMemo } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Empty,
  Pane,
  PaneBody,
  PaneHeader,
  Pill,
  Skeleton,
  StatCard,
} from "@/design-system";
import { SymbolBar } from "@/shell/SymbolBar";
import { useFunction } from "@/lib/useFunction";
import { defaultSymbolForFunction } from "@/lib/symbols";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

interface GEXSummary {
  net_gex?: number;
  call_gex_total?: number;
  put_gex_total?: number;
  gamma_flip?: number | { strike?: number };
  call_wall?: number | { strike?: number; gex?: number };
  put_wall?: number | { strike?: number; gex?: number };
  n_strikes?: number;
  source_mode?: string;
}

interface GEXRow {
  label?: string;
  strike?: number;
  gex?: number;
  value?: number;
  cumulative_gex?: number;
  call_gex?: number;
  put_gex?: number;
}

interface GEXData {
  status?: "ok" | "empty" | "input_error" | "provider_unavailable";
  reason?: string;
  symbol?: string;
  spot?: number;
  expiries?: string[];
  rows?: GEXRow[];
  curve?: GEXRow[];
  summary?: GEXSummary;
  call_wall?: number | { strike?: number };
  put_wall?: number | { strike?: number };
  methodology?: string;
}

function strikeOf(value: number | { strike?: number } | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object" && typeof value.strike === "number") {
    return value.strike;
  }
  return null;
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${n < 0 ? "-" : ""}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${n < 0 ? "-" : ""}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${n < 0 ? "-" : ""}$${(abs / 1e3).toFixed(1)}K`;
  return `${n < 0 ? "-" : ""}$${abs.toFixed(0)}`;
}

function fmtStrike(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function GEXPane({ code, symbol }: FunctionPaneProps) {
  const effectiveSymbol =
    symbol || defaultSymbolForFunction(code, ["EQUITY"]);
  const { state, data, error, refetch } = useFunction<GEXData>({
    code,
    symbol: effectiveSymbol,
    // `live_options` switches the backend from the synthetic 3-strike
    // reference model to the real yfinance options chain + Black-Scholes
    // gamma path. The model fallback still kicks in when yfinance is
    // unreachable so the pane never goes blank.
    params: { live_options: true, max_expiries: 1 },
    enabled: !!effectiveSymbol,
  });

  const payload = data?.data;
  const status = payload?.status ?? (state === "ok" ? "ok" : undefined);
  const rows = useMemo<GEXRow[]>(() => {
    const candidate = payload?.curve ?? payload?.rows ?? [];
    return [...candidate].sort((a, b) => (a.strike ?? 0) - (b.strike ?? 0));
  }, [payload]);
  const summary = payload?.summary;
  const spot = payload?.spot;
  const callWallStrike =
    strikeOf(payload?.call_wall) ?? strikeOf(summary?.call_wall);
  const putWallStrike =
    strikeOf(payload?.put_wall) ?? strikeOf(summary?.put_wall);
  const flipStrike =
    strikeOf(summary?.gamma_flip) ??
    strikeOf((payload as { gamma_flip?: number | { strike?: number } } | undefined)?.gamma_flip ?? undefined);

  const isLive = (summary?.source_mode ?? "").includes("live");
  const expiriesLabel = (payload?.expiries ?? []).slice(0, 2).join(", ") || "—";

  const maxAbs = useMemo(() => {
    let m = 0;
    for (const r of rows) {
      const v = Math.abs(r.gex ?? r.value ?? 0);
      if (v > m) m = v;
    }
    return m || 1;
  }, [rows]);

  return (
    <div className="u-pane-host">
      <SymbolBar code={code} symbol={effectiveSymbol} />
      <Pane>
        <PaneHeader
          code={code}
          title={`Dealer gamma · ${effectiveSymbol ?? "—"}`}
          subtitle={
            status === "ok"
              ? `${rows.length} strike · spot ${fmtStrike(spot)} · exp ${expiriesLabel}`
              : status === "provider_unavailable"
                ? "Options provider unavailable"
                : "Waiting for options chain"
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} k
              </Pill>
              <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                {isLive ? "live chain" : "reference"}
              </Pill>
              <LoadStatePill state={state} />
              <RefreshButton
                loading={state === "loading"}
                onClick={refetch}
                title="Refresh GEX curve"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 14,
            minHeight: 0,
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 12,
            }}
          >
            <StatCard
              label="Net dealer Γ"
              value={fmtCurrency(summary?.net_gex)}
              caption="per 1% spot move"
              tone={
                (summary?.net_gex ?? 0) >= 0 ? "positive" : "negative"
              }
            />
            <StatCard
              label="Gamma flip"
              value={fmtStrike(flipStrike)}
              caption={
                flipStrike != null && spot != null
                  ? `${(flipStrike - spot).toFixed(2)} vs spot`
                  : "first sign change"
              }
              tone="neutral"
            />
            <StatCard
              label="Call wall"
              value={fmtStrike(callWallStrike)}
              caption={fmtCurrency(
                typeof payload?.call_wall === "object"
                  ? (payload.call_wall as { gex?: number }).gex
                  : summary?.call_gex_total,
              )}
              tone="positive"
            />
            <StatCard
              label="Put wall"
              value={fmtStrike(putWallStrike)}
              caption={fmtCurrency(
                typeof payload?.put_wall === "object"
                  ? (payload.put_wall as { gex?: number }).gex
                  : summary?.put_gex_total,
              )}
              tone="negative"
            />
          </div>

          <Card>
            <CardHeader>Dealer gamma by strike</CardHeader>
            <CardBody>
              {state === "loading" ? (
                <Skeleton height={280} />
              ) : rows.length === 0 ? (
                <Empty
                  title="No options chain"
                  body={payload?.reason ?? "Try a liquid equity symbol such as SPY or NVDA."}
                />
              ) : (
                <div className="gex-chart">
                  <div className="gex-chart__axis">
                    <span>{fmtCurrency(-maxAbs)}</span>
                    <span>0</span>
                    <span>{fmtCurrency(maxAbs)}</span>
                  </div>
                  <div className="gex-chart__rows" role="list">
                    <span className="gex-chart__zero" aria-hidden />
                    {rows.map((row) => {
                      const v = row.gex ?? row.value ?? 0;
                      const pct = Math.min(50, Math.abs((v / maxAbs) * 50));
                      const isCallWall =
                        callWallStrike != null && row.strike === callWallStrike;
                      const isPutWall =
                        putWallStrike != null && row.strike === putWallStrike;
                      const isFlip =
                        flipStrike != null && row.strike === flipStrike;
                      const isSpot =
                        spot != null && Math.abs((row.strike ?? 0) - spot) < 0.01;
                      const rowCls =
                        "gex-chart__row" +
                        (isCallWall ? " gex-chart__row--call-wall" : "") +
                        (isPutWall ? " gex-chart__row--put-wall" : "") +
                        (isFlip ? " gex-chart__row--flip" : "") +
                        (isSpot ? " gex-chart__row--spot" : "");
                      return (
                        <div
                          className={rowCls}
                          role="listitem"
                          key={row.strike}
                          title={`strike ${fmtStrike(row.strike)} · gex ${fmtCurrency(v)}`}
                        >
                          {v < 0 ? (
                            <span
                              className="gex-chart__bar gex-chart__bar--put"
                              style={{ width: `${pct}%` }}
                            />
                          ) : (
                            <span className="gex-chart__bar gex-chart__bar--put" />
                          )}
                          {v >= 0 ? (
                            <span
                              className="gex-chart__bar gex-chart__bar--call"
                              style={{ width: `${pct}%` }}
                            />
                          ) : (
                            <span className="gex-chart__bar gex-chart__bar--call" />
                          )}
                          <span className="gex-chart__strike">
                            {fmtStrike(row.strike)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="gex-chart__legend">
                    <span>
                      <span className="gex-chart__sw gex-chart__sw--call" /> Call
                      gamma · dealer long
                    </span>
                    <span>
                      <span className="gex-chart__sw gex-chart__sw--put" /> Put
                      gamma · dealer short
                    </span>
                    {spot != null && (
                      <span>
                        <span className="gex-chart__sw gex-chart__sw--spot" /> Spot
                        {fmtStrike(spot) !== "—" ? ` ${fmtStrike(spot)}` : ""}
                      </span>
                    )}
                    {flipStrike != null && (
                      <span>
                        <span className="gex-chart__sw gex-chart__sw--flip" /> Flip
                      </span>
                    )}
                  </div>
                </div>
              )}
            </CardBody>
          </Card>

          {state === "error" && error ? (
            <Empty title="GEX error" body={error instanceof Error ? error.message : String(error)} />
          ) : null}
        </PaneBody>
      </Pane>
    </div>
  );
}

export default GEXPane;
