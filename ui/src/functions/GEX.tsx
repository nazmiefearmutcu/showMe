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
 * model. When yfinance is unreachable the backend degrades to a SYNTHETIC
 * reference model (hardcoded OI, constant IV) and flags it
 * (`summary.synthetic` + a `warning`). This pane surfaces that honestly:
 * a prominent negative badge plus an inline alert banner so a fabricated
 * curve is never presented as real dealer positioning. It also discloses
 * that only the nearest expiry is fetched (`max_expiries=1`).
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
  formatCurrency,
  formatMissing,
  formatPrice,
} from "@/lib/format";
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
  /** True when the backend served the synthetic reference model rather
   * than a real options chain (live chain unavailable). */
  synthetic?: boolean;
  degraded?: boolean;
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
  /** Human-readable degradation note surfaced verbatim when the synthetic
   * reference model is in use. */
  warning?: string;
}

function strikeOf(value: number | { strike?: number } | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (value && typeof value === "object" && typeof value.strike === "number") {
    return value.strike;
  }
  return null;
}

/** GEX dollar magnitudes (net Γ, walls) — compact "$" with 2 sig decimals,
 * shared sentinel for missing. Delegates to the canonical formatter so the
 * pane stops shipping its own rounding contract. */
function gexCurrency(n: number | null | undefined): string {
  return formatCurrency(n, { compact: true, fractionDigits: 2 });
}

/** Strike labels — price-grade precision (keeps sub-dollar precision for
 * cheap underlyings) instead of a bespoke locale call. */
function gexStrike(n: number | null | undefined): string {
  return formatPrice(n);
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

  // Honest source detection. The backend flags the synthetic reference
  // model explicitly (`summary.synthetic`); we also defend against an
  // older payload by treating any `synthetic*` source_mode as degraded.
  const sourceMode = summary?.source_mode ?? "";
  const isSynthetic =
    summary?.synthetic === true ||
    summary?.degraded === true ||
    sourceMode.startsWith("synthetic");
  const isLive = !isSynthetic && sourceMode.includes("live");
  const syntheticNote =
    payload?.warning ??
    "Live options chain unavailable — showing a synthetic reference model, NOT real dealer positioning.";
  const expiriesLabel = (payload?.expiries ?? []).slice(0, 2).join(", ") || formatMissing;
  // Single-expiry disclosure: the backend defaults to the nearest expiry
  // only (max_expiries=1) to avoid slow/timeout-prone deep fetches, which
  // omits most dealer gamma. Say so plainly instead of implying the whole
  // surface is represented.
  const expiryCount = (payload?.expiries ?? []).length;
  const expiryScope =
    expiryCount <= 1 ? "nearest expiry only" : `${expiryCount} expiries`;

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
              ? `${rows.length} strike · spot ${gexStrike(spot)} · ${expiryScope}${expiriesLabel !== formatMissing ? ` (${expiriesLabel})` : ""}`
              : status === "provider_unavailable"
                ? "Options provider unavailable"
                : "Waiting for options chain"
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                {rows.length} k
              </Pill>
              {isSynthetic ? (
                <Pill tone="negative" variant="filled">
                  ⚠ Synthetic model — not live options
                </Pill>
              ) : (
                <Pill tone={isLive ? "positive" : "warn"} variant="soft">
                  {isLive ? "live chain" : "reference"}
                </Pill>
              )}
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
          {isSynthetic && status === "ok" ? (
            <div className="gex-synthetic-note" role="alert">
              <strong className="gex-synthetic-note__title">
                ⚠ Synthetic reference model
              </strong>
              <span className="gex-synthetic-note__body">{syntheticNote}</span>
            </div>
          ) : null}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 12,
            }}
          >
            <StatCard
              label="Net dealer Γ"
              value={
                <span className="terminal-grid-numeric">
                  {gexCurrency(summary?.net_gex)}
                </span>
              }
              caption="per 1% spot move"
              tone={
                (summary?.net_gex ?? 0) >= 0 ? "positive" : "negative"
              }
            />
            <StatCard
              label="Gamma flip"
              value={
                <span className="terminal-grid-numeric">
                  {gexStrike(flipStrike)}
                </span>
              }
              caption={
                flipStrike != null && spot != null
                  ? `${(flipStrike - spot).toFixed(2)} vs spot`
                  : "first sign change"
              }
              tone="neutral"
            />
            <StatCard
              label="Call wall"
              value={
                <span className="terminal-grid-numeric">
                  {gexStrike(callWallStrike)}
                </span>
              }
              caption={gexCurrency(
                typeof payload?.call_wall === "object"
                  ? (payload.call_wall as { gex?: number }).gex
                  : summary?.call_gex_total,
              )}
              tone="positive"
            />
            <StatCard
              label="Put wall"
              value={
                <span className="terminal-grid-numeric">
                  {gexStrike(putWallStrike)}
                </span>
              }
              caption={gexCurrency(
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
                  <div className="gex-chart__axis terminal-grid-numeric">
                    <span>{gexCurrency(-maxAbs)}</span>
                    <span>0</span>
                    <span>{gexCurrency(maxAbs)}</span>
                  </div>
                  <div
                    className="gex-chart__rows terminal-grid-numeric"
                    role="list"
                    aria-label={`Dealer gamma exposure by strike for ${effectiveSymbol ?? "instrument"}, ${rows.length} strikes`}
                  >
                    <span className="gex-chart__zero" aria-hidden />
                    {rows.map((row, index) => {
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
                      const direction = v >= 0 ? "call gamma" : "put gamma";
                      const tags = [
                        isCallWall ? "call wall" : null,
                        isPutWall ? "put wall" : null,
                        isFlip ? "gamma flip" : null,
                        isSpot ? "spot" : null,
                      ].filter(Boolean);
                      const ariaLabel =
                        `Strike ${gexStrike(row.strike)}: ${direction} ${gexCurrency(Math.abs(v))}` +
                        (tags.length ? ` (${tags.join(", ")})` : "");
                      return (
                        <div
                          className={rowCls}
                          role="listitem"
                          aria-label={ariaLabel}
                          key={row.strike ?? index}
                          title={ariaLabel}
                        >
                          {v < 0 ? (
                            <span
                              className="gex-chart__bar gex-chart__bar--put"
                              style={{ width: `${pct}%` }}
                              aria-hidden="true"
                            />
                          ) : (
                            <span className="gex-chart__bar gex-chart__bar--put" aria-hidden="true" />
                          )}
                          {v >= 0 ? (
                            <span
                              className="gex-chart__bar gex-chart__bar--call"
                              style={{ width: `${pct}%` }}
                              aria-hidden="true"
                            />
                          ) : (
                            <span className="gex-chart__bar gex-chart__bar--call" aria-hidden="true" />
                          )}
                          <span className="gex-chart__strike">
                            {gexStrike(row.strike)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="gex-chart__legend">
                    <span>
                      <span className="gex-chart__sw gex-chart__sw--call" aria-hidden="true" /> Call
                      gamma · dealer long
                    </span>
                    <span>
                      <span className="gex-chart__sw gex-chart__sw--put" aria-hidden="true" /> Put
                      gamma · dealer short
                    </span>
                    {spot != null && (
                      <span>
                        <span className="gex-chart__sw gex-chart__sw--spot" aria-hidden="true" /> Spot
                        {gexStrike(spot) !== formatMissing ? ` ${gexStrike(spot)}` : ""}
                      </span>
                    )}
                    {flipStrike != null && (
                      <span>
                        <span className="gex-chart__sw gex-chart__sw--flip" aria-hidden="true" /> Flip
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
