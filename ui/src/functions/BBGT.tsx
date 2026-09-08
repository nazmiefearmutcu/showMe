/**
 * BBGT — Multi-Asset Trade Ticket.
 *
 * EMSX-style ticket desk bound to an ASSET CLASS selector (equity / ETF /
 * FX / crypto / bond / commodity / derivative), so the same form routes the
 * symbol to the right instrument + broker adapter. Default path is a paper
 * PREVIEW: `runFunction` is only called with `submit:true` when the user
 * ticks the explicit confirm checkbox AND presses the live-submit button
 * (the backend implements broker submission; the confirm box resets on any
 * field edit).
 *
 * Data honesty (survey defect): the ticket payload carries NO market data —
 * boards elsewhere may show reference quotes over degraded feeds, so this
 * pane states plainly that no quote is attached and reference/indicative
 * quotes are NOT executable prices. `broker_available` is surfaced honestly
 * (paper preview without a configured broker cannot submit).
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Empty,
  Field,
  FieldRow,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
  StatusDivider,
  StatusSection,
} from "@/design-system";
import {
  runFunction,
  FunctionCallError,
  type FunctionCallResult,
} from "@/lib/functions";
import { useAppStore } from "@/lib/store";
import {
  FunctionControlGroup,
  LoadStatePill,
  RefreshButton,
  SegmentedControl,
} from "./function-controls";
import { usePersistentOption, usePersistentString } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

const ASSET_CLASSES = [
  { value: "EQUITY", label: "Equity" },
  { value: "ETF", label: "ETF" },
  { value: "FX", label: "FX" },
  { value: "CRYPTO", label: "Crypto" },
  { value: "BOND", label: "Bond" },
  { value: "COMMODITY", label: "Cmdty" },
  { value: "DERIVATIVE", label: "Deriv" },
] as const;
type AssetClass = (typeof ASSET_CLASSES)[number]["value"];
const ASSET_CLASS_IDS = ASSET_CLASSES.map((o) => o.value);

const SYMBOL_PLACEHOLDER: Record<AssetClass, string> = {
  EQUITY: "AAPL",
  ETF: "SPY",
  FX: "EURUSD",
  CRYPTO: "BTCUSDT",
  BOND: "US912810TM00",
  COMMODITY: "CL=F",
  DERIVATIVE: "SPY 260717C600",
};

const SIDES = [
  { value: "BUY", label: "Buy" },
  { value: "SELL", label: "Sell" },
] as const;
type Side = (typeof SIDES)[number]["value"];
const SIDE_IDS = SIDES.map((o) => o.value);

const TYPES = [
  { value: "MARKET", label: "Market" },
  { value: "LIMIT", label: "Limit" },
] as const;
type OrderType = (typeof TYPES)[number]["value"];
const TYPE_IDS = TYPES.map((o) => o.value);

const TIFS = [
  { value: "DAY", label: "DAY" },
  { value: "GTC", label: "GTC" },
  { value: "IOC", label: "IOC" },
  { value: "FOK", label: "FOK" },
] as const;
type Tif = (typeof TIFS)[number]["value"];
const TIF_IDS = TIFS.map((o) => o.value);

interface BBGTData {
  status?: string;
  broker?: string | null;
  submit?: boolean;
  broker_available?: boolean;
  symbol?: string;
  asset_class?: string;
  side?: string;
  quantity?: number;
  order_type?: string;
  time_in_force?: string;
  price?: number | null;
  leverage?: number | null;
  order_id?: string;
  reason?: string;
  next_actions?: string[];
}

export function BBGTPane({ code }: FunctionPaneProps) {
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const sidecarReady = sidecarPort != null;

  const [assetClass, setAssetClass] = usePersistentOption<AssetClass>(
    "showme.bbgt.asset_class",
    ASSET_CLASS_IDS,
    "EQUITY",
  );
  const [side, setSide] = usePersistentOption<Side>("showme.bbgt.side", SIDE_IDS, "BUY");
  const [orderType, setOrderType] = usePersistentOption<OrderType>(
    "showme.bbgt.type",
    TYPE_IDS,
    "MARKET",
  );
  const [tif, setTif] = usePersistentOption<Tif>("showme.bbgt.tif", TIF_IDS, "GTC");

  // Committed (last run) symbol persists; the draft edits freely.
  const [lastSymbol, setLastSymbol] = usePersistentString("showme.bbgt.symbol", "");
  const [symbol, setSymbol] = useState<string>(lastSymbol);
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [leverage, setLeverage] = useState("");

  // Live-mode armament: confirm checkbox must be ticked. Resets when any
  // ticket parameter changes so a stale armament can't ride a new ticket.
  const [confirmLive, setConfirmLive] = useState(false);
  useEffect(() => {
    setConfirmLive(false);
  }, [side, orderType, tif, quantity, price, leverage, symbol, assetClass]);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<FunctionCallResult<BBGTData> | null>(null);
  const [lastSubmit, setLastSubmit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const qtyNumber = useMemo(() => {
    const n = Number(quantity);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [quantity]);
  const priceNumber = useMemo(() => {
    const n = Number(price);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [price]);
  const leverageNumber = useMemo(() => {
    const n = Number(leverage);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [leverage]);

  const trimmedSymbol = symbol.trim();
  const canPreview = !!trimmedSymbol && qtyNumber != null && !running;
  const canSubmitLive =
    canPreview && confirmLive && (orderType === "MARKET" || priceNumber != null);

  async function execute(submit: boolean) {
    if (!trimmedSymbol || qtyNumber == null) return;
    if (submit && !confirmLive) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setLastSubmit(submit);
    try {
      const params: Record<string, unknown> = {
        side,
        quantity: qtyNumber,
        type: orderType,
        tif,
        submit,
      };
      if (orderType === "LIMIT" && priceNumber != null) {
        params.price = priceNumber;
      }
      if (leverageNumber != null) {
        params.leverage = leverageNumber;
      }
      const res = await runFunction<BBGTData>(code, {
        symbol: trimmedSymbol,
        asset_class: assetClass,
        params,
        signal: controller.signal,
      });
      setResult(res);
      setLastSymbol(trimmedSymbol);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof FunctionCallError
          ? `${err.status}: ${err.body}`
          : err instanceof Error
            ? err.message
            : String(err),
      );
    } finally {
      if (!controller.signal.aborted) {
        setRunning(false);
      }
    }
  }

  const payload = result?.data;
  const status = payload?.status ?? result?.status;
  const broker = payload?.broker ?? "—";
  const brokerAvailable = payload?.broker_available === true;
  const live = lastSubmit && status === "filled";
  const state: "idle" | "loading" | "ok" | "error" = running
    ? "loading"
    : error
      ? "error"
      : result
        ? "ok"
        : "idle";

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title="Multi-Asset Trade Ticket"
          subtitle={
            trimmedSymbol
              ? `${trimmedSymbol} · ${assetClass.toLowerCase()} · ${live ? "filled" : "preview"}`
              : "multi-asset ticket"
          }
          trailing={
            <FunctionControlGroup>
              <Pill
                tone={brokerAvailable ? "positive" : "muted"}
                variant="soft"
                withDot={false}
              >
                {brokerAvailable ? `broker · ${broker}` : "paper preview"}
              </Pill>
              {confirmLive ? (
                <Pill tone="negative" variant="filled" withDot>
                  LIVE ARMED
                </Pill>
              ) : null}
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={running}
                onClick={() => void execute(false)}
                disabled={!canPreview}
                title="Re-price (preview)"
                label="Re-price"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div style={twoColLayout}>
            <section style={formCardStyle} aria-label="BBGT ticket form">
              <span style={sectionTitleStyle}>Ticket</span>
              <SegmentedControl
                label="ASSET"
                value={assetClass}
                options={ASSET_CLASSES}
                onChange={setAssetClass}
                disabled={running}
                title="Asset class"
              />
              <SegmentedControl
                label="SIDE"
                value={side}
                options={SIDES}
                onChange={setSide}
                disabled={running}
              />
              <SegmentedControl
                label="TYPE"
                value={orderType}
                options={TYPES}
                onChange={setOrderType}
                disabled={running}
              />
              <SegmentedControl
                label="TIF"
                value={tif}
                options={TIFS}
                onChange={setTif}
                disabled={running}
              />
              <FieldRow>
                <Field
                  label="Symbol"
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  placeholder={SYMBOL_PLACEHOLDER[assetClass]}
                  disabled={running}
                />
                <Field
                  label="Quantity"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  inputMode="decimal"
                  placeholder="0"
                  disabled={running}
                />
                {orderType === "LIMIT" ? (
                  <Field
                    label="Limit price"
                    value={price}
                    onChange={(e) => setPrice(e.target.value)}
                    inputMode="decimal"
                    placeholder="0"
                    disabled={running}
                  />
                ) : null}
                <Field
                  label="Leverage (optional)"
                  value={leverage}
                  onChange={(e) => setLeverage(e.target.value)}
                  inputMode="decimal"
                  placeholder="—"
                  disabled={running}
                />
              </FieldRow>
              <div style={actionsRowStyle}>
                <button
                  type="button"
                  className="btn btn--accent"
                  onClick={() => void execute(false)}
                  disabled={!canPreview || !sidecarReady}
                  title="Compute a paper-broker preview (submit=false)"
                >
                  {running ? "Previewing..." : "Preview"}
                </button>
              </div>
              <div style={liveBoxStyle}>
                <label style={confirmLabelStyle}>
                  <input
                    type="checkbox"
                    checked={confirmLive}
                    onChange={(e) => setConfirmLive(e.target.checked)}
                    disabled={running}
                    aria-describedby="bbgt-live-warning"
                  />
                  <span>I confirm this is a real order</span>
                </label>
                <p id="bbgt-live-warning" style={liveWarningStyle}>
                  Submitting forwards the ticket to the broker configured for
                  the asset class. Without one the backend refuses
                  (provider_unavailable). The confirm box resets on any edit.
                </p>
                <button
                  type="button"
                  className="btn btn--accent"
                  style={liveButtonStyle(canSubmitLive)}
                  onClick={() => void execute(true)}
                  disabled={!canSubmitLive || !sidecarReady}
                  title={
                    confirmLive
                      ? "Submit live order (submit=true)"
                      : "Tick the confirm checkbox to enable live submit"
                  }
                >
                  {running && confirmLive ? "Submitting..." : "Submit live order"}
                </button>
              </div>
            </section>
            <PreviewView
              running={running}
              error={error}
              result={result}
              lastSubmit={lastSubmit}
              fallbackSymbol={trimmedSymbol}
            />
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="broker" value={String(broker)} />
          <StatusDivider />
          <StatusSection
            label="status"
            value={String(status ?? state)}
            tone={status === "filled" ? "positive" : status === "preview" ? "neutral" : "warn"}
          />
          <StatusDivider />
          <StatusSection label="asset" value={payload?.asset_class ?? assetClass} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${result?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={confirmLive ? "live armed" : "preview only"}
            tone={confirmLive ? "negative" : "muted"}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function PreviewView({
  running,
  error,
  result,
  lastSubmit,
  fallbackSymbol,
}: {
  running: boolean;
  error: string | null;
  result: FunctionCallResult<BBGTData> | null;
  lastSubmit: boolean;
  fallbackSymbol: string;
}): ReactNode {
  if (running) {
    return (
      <section style={previewCardStyle} aria-label="BBGT ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Skeleton height={18} />
        <Skeleton height={14} />
        <Skeleton height={14} width="80%" />
      </section>
    );
  }
  if (error) {
    return (
      <section style={previewCardStyle} aria-label="BBGT ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Empty title="Function error" body={error} icon="!" />
      </section>
    );
  }
  if (!result) {
    return (
      <section style={previewCardStyle} aria-label="BBGT ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Empty
          title="No preview yet"
          body="Pick an asset class, set symbol + quantity, then Preview to price a paper ticket."
          icon="•"
        />
      </section>
    );
  }
  const p = result.data;
  const status = p?.status ?? "—";
  const nextActions = Array.isArray(p?.next_actions) ? p.next_actions : [];
  const brokerAvailable = p?.broker_available === true;
  return (
    <section style={previewCardStyle} aria-label="BBGT ticket preview">
      <span style={sectionTitleStyle}>
        Order preview {lastSubmit ? "· LIVE" : "· paper"}
      </span>
      <div style={quoteNoteStyle} role="note" aria-label="BBGT quote honesty">
        No market data is attached to this ticket. Reference or indicative
        quotes shown anywhere in the terminal are NOT executable prices —
        pricing must be confirmed with the venue before submission.
      </div>
      <div style={summaryRowsStyle}>
        <PreviewRow
          label="Symbol"
          value={<span style={monoStrongStyle}>{p?.symbol ?? fallbackSymbol ?? "—"}</span>}
        />
        <PreviewRow
          label="Asset class"
          value={(p?.asset_class ?? "—").toUpperCase()}
        />
        <PreviewRow
          label="Side"
          value={
            <Pill
              tone={String(p?.side ?? "").toUpperCase() === "BUY" ? "positive" : "negative"}
              variant="soft"
              withDot={false}
            >
              {String(p?.side ?? "—").toUpperCase()}
            </Pill>
          }
        />
        <PreviewRow
          label="Quantity"
          value={
            <span style={monoPrimaryStyle}>
              {typeof p?.quantity === "number"
                ? p.quantity.toLocaleString("en-US", { maximumFractionDigits: 8 })
                : "—"}
            </span>
          }
        />
        <PreviewRow label="Type" value={String(p?.order_type ?? "—").toUpperCase()} />
        <PreviewRow label="TIF" value={String(p?.time_in_force ?? "—").toUpperCase()} />
        <PreviewRow
          label="Limit price"
          value={
            <span style={monoPrimaryStyle}>
              {typeof p?.price === "number" && p.price > 0 ? String(p.price) : "—"}
            </span>
          }
        />
        <PreviewRow
          label="Leverage"
          value={
            typeof p?.leverage === "number" && p.leverage > 0 ? String(p.leverage) : "—"
          }
        />
        <PreviewRow
          label="Broker"
          value={
            <Pill
              tone={brokerAvailable ? "positive" : "muted"}
              variant="soft"
              withDot={false}
            >
              {brokerAvailable
                ? `${p?.broker ?? "configured"} · ready`
                : "paper · no broker configured"}
            </Pill>
          }
        />
        <PreviewRow
          label="Status"
          value={
            <Pill
              tone={
                status === "filled"
                  ? "positive"
                  : status === "preview"
                    ? "accent"
                    : "warn"
              }
              variant="soft"
              withDot={false}
            >
              {String(status).toUpperCase()}
            </Pill>
          }
        />
        {p?.order_id ? (
          <PreviewRow
            label="Order ID"
            value={<span style={monoPrimaryStyle}>{String(p.order_id)}</span>}
          />
        ) : null}
      </div>
      {p?.reason ? <div style={reasonStyle}>{p.reason}</div> : null}
      {nextActions.length > 0 ? (
        <div style={nextActionsBoxStyle}>
          <span style={sectionTitleStyle}>Next actions</span>
          <ul style={nextActionsListStyle}>
            {nextActions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

function PreviewRow({ label, value }: { label: string; value: ReactNode }): ReactNode {
  return (
    <div style={summaryRowStyle}>
      <span style={summaryLabelStyle}>{label}</span>
      <span style={summaryValueStyle}>{value}</span>
    </div>
  );
}

/* ── styles ────────────────────────────────────────────────────────── */

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(300px, 1fr) minmax(300px, 1fr)",
  gap: 14,
  alignItems: "start",
};

const formCardStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  padding: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
};

const previewCardStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
};

const sectionTitleStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const actionsRowStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
};

const liveBoxStyle: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: 10,
  border: "1px solid var(--negative)",
  borderRadius: "var(--radius-sm)",
  background: "var(--surface-1)",
};

const confirmLabelStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  color: "var(--text-primary)",
  cursor: "default",
};

const liveWarningStyle: CSSProperties = {
  margin: 0,
  color: "var(--text-mute)",
  fontSize: 10,
  lineHeight: 1.5,
};

function liveButtonStyle(enabled: boolean): CSSProperties {
  return {
    background: enabled ? "var(--negative)" : undefined,
    borderColor: enabled ? "var(--negative)" : undefined,
    color: enabled ? "var(--text-primary)" : undefined,
    opacity: enabled ? 1 : 0.55,
  };
}

const quoteNoteStyle: CSSProperties = {
  border: "1px solid var(--negative, var(--text-mute))",
  borderRadius: 6,
  padding: "8px 10px",
  fontSize: 11,
  lineHeight: 1.6,
  color: "var(--text-primary)",
};

const summaryRowsStyle: CSSProperties = {
  display: "grid",
  gap: 0,
};

const summaryRowStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "110px 1fr",
  alignItems: "center",
  gap: 8,
  padding: "4px 0",
  borderBottom: "1px solid var(--border-subtle)",
};

const summaryLabelStyle: CSSProperties = {
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  fontSize: 10,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
};

const summaryValueStyle: CSSProperties = {
  color: "var(--text-primary)",
  fontSize: 12,
};

const reasonStyle: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 11,
  lineHeight: 1.6,
  paddingTop: 6,
};

const nextActionsBoxStyle: CSSProperties = {
  display: "grid",
  gap: 6,
  paddingTop: 8,
  borderTop: "1px solid var(--border-subtle)",
};

const nextActionsListStyle: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  color: "var(--text-mute)",
  fontSize: 11,
  lineHeight: 1.6,
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
