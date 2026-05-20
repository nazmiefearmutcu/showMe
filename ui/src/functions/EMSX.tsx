/**
 * EMSX — Execution Management trade ticket.
 *
 * Two-column layout: LEFT is the ticket form (side / quantity / type / tif /
 * price / leverage), RIGHT is the preview summary the backend returns. The
 * pane defaults to PREVIEW: `runFunction` is only called with `submit:true`
 * when the user (a) ticks the explicit "I confirm this is a real order"
 * checkbox and (b) presses the separate live-submit button. The header
 * surfaces a red Pill warning whenever live mode is armed so the user can
 * see at a glance that the next click will hit the broker.
 *
 * `runFunction` is invoked imperatively (not `useFunction`) so the pane
 * never auto-fires on mount and never re-fires on prop changes. The default
 * mounted state is "idle" — the user must press Preview to compute even the
 * preview ticket.
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
import { usePersistentOption } from "./function-control-state";
import type { FunctionPaneProps } from "./registry-types";

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

interface EMSXData {
  status?: "preview" | "filled" | "input_required" | "ok" | "empty" | "input_error" | "provider_unavailable";
  broker?: string;
  submit?: boolean;
  symbol?: string;
  asset_class?: string;
  side?: string;
  quantity?: number;
  order_type?: string;
  type?: string;
  time_in_force?: string;
  tif?: string;
  order_id?: string;
  reason?: string;
  next_actions?: string[];
  [key: string]: unknown;
}

export function EMSXPane({ code, symbol }: FunctionPaneProps) {
  const sidecarPort = useAppStore((s) => s.sidecarPort);
  const sidecarReady = sidecarPort != null;

  const [side, setSide] = usePersistentOption<Side>(
    "showme.emsx.side",
    SIDE_IDS,
    "BUY",
  );
  const [orderType, setOrderType] = usePersistentOption<OrderType>(
    "showme.emsx.type",
    TYPE_IDS,
    "MARKET",
  );
  const [tif, setTif] = usePersistentOption<Tif>(
    "showme.emsx.tif",
    TIF_IDS,
    "GTC",
  );

  const [quantity, setQuantity] = useState<string>("");
  const [price, setPrice] = useState<string>("");
  const [leverage, setLeverage] = useState<string>("");

  // Live-mode armament: confirm checkbox must be ticked. Resets when any
  // ticket parameter changes so the user can't toggle armament once and
  // then silently change quantity/side under it.
  const [confirmLive, setConfirmLive] = useState(false);
  useEffect(() => {
    setConfirmLive(false);
  }, [side, orderType, tif, quantity, price, leverage, symbol]);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<FunctionCallResult<EMSXData> | null>(
    null,
  );
  const [lastSubmit, setLastSubmit] = useState<boolean>(false);
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

  const canPreview = !!symbol && qtyNumber != null && !running;
  const canSubmitLive =
    canPreview &&
    confirmLive &&
    (orderType === "MARKET" || priceNumber != null);

  // CRITICAL: only path that calls /api/fn/EMSX. `submit` is a parameter,
  // not state — every call site passes it explicitly. The Submit Live
  // button is the *only* call site that passes `submit: true`, and it
  // gates that on `confirmLive` (also re-checked at call time below).
  const execute = async (submit: boolean) => {
    if (!symbol || qtyNumber == null) return;
    if (submit && !confirmLive) {
      // Belt-and-braces: even if a button slipped past disabled checks
      // somehow, the confirm gate is re-checked at call time. There is no
      // path that fires submit:true without confirmLive===true.
      return;
    }
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
      const res = await runFunction<EMSXData>(code, {
        symbol,
        params,
        signal: controller.signal,
      });
      setResult(res);
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg =
        err instanceof FunctionCallError
          ? `${err.status}: ${err.body}`
          : err instanceof Error
            ? err.message
            : String(err);
      setError(msg);
    } finally {
      if (!controller.signal.aborted) {
        setRunning(false);
      }
    }
  };

  const previewClick = () => {
    void execute(false);
  };

  const submitLiveClick = () => {
    // Defense-in-depth: re-read state at click time. If the checkbox was
    // un-ticked between render and click (e.g. fast keyboard sequence),
    // this short-circuits.
    if (!confirmLive) return;
    void execute(true);
  };

  const payload = result?.data;
  const status = payload?.status ?? result?.status;
  const broker = payload?.broker ?? "paper";
  const assetClass = payload?.asset_class ?? "—";
  const live = lastSubmit && status === "filled";
  const armed = confirmLive;

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
          title="Execution management"
          subtitle={
            symbol
              ? `${symbol} · ${assetClass} · ${live ? "filled" : "preview"}`
              : "ticket"
          }
          trailing={
            <FunctionControlGroup>
              <Pill tone="muted" variant="soft" withDot={false}>
                BROKER · {broker.toString().toUpperCase()}
              </Pill>
              <Pill
                tone={
                  status === "filled"
                    ? "positive"
                    : status === "input_required"
                      ? "warn"
                      : status === "preview"
                        ? "accent"
                        : "muted"
                }
                variant="soft"
                withDot={false}
              >
                {String(status ?? "idle").toUpperCase()}
              </Pill>
              {armed && (
                <Pill tone="negative" variant="filled" withDot>
                  LIVE ARMED
                </Pill>
              )}
              <LoadStatePill state={state} status={status} />
              <RefreshButton
                loading={running}
                onClick={previewClick}
                disabled={!canPreview}
                title="Re-price (preview)"
                label="Re-price"
              />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          {!symbol ? (
            <Empty
              title="Pick a symbol"
              body="EMSX needs a ticker to compose a trade ticket."
              icon="⌖"
            />
          ) : (
            <div style={twoColLayout}>
              <TicketForm
                side={side}
                onSide={setSide}
                orderType={orderType}
                onOrderType={setOrderType}
                tif={tif}
                onTif={setTif}
                quantity={quantity}
                onQuantity={setQuantity}
                price={price}
                onPrice={setPrice}
                leverage={leverage}
                onLeverage={setLeverage}
                confirmLive={confirmLive}
                onConfirmLive={setConfirmLive}
                onPreview={previewClick}
                onSubmitLive={submitLiveClick}
                canPreview={canPreview}
                canSubmitLive={canSubmitLive}
                running={running}
                sidecarReady={sidecarReady}
              />
              <PreviewSummary
                running={running}
                error={error}
                result={result}
                lastSubmit={lastSubmit}
                fallbackSymbol={symbol}
              />
            </div>
          )}
        </PaneBody>
        <PaneFooter>
          <StatusSection label="broker" value={broker} />
          <StatusDivider />
          <StatusSection
            label="status"
            value={String(status ?? state)}
            tone={
              status === "filled"
                ? "positive"
                : status === "input_required"
                  ? "warn"
                  : "neutral"
            }
          />
          <StatusDivider />
          <StatusSection label="asset" value={assetClass} />
          <StatusDivider />
          <StatusSection
            label="elapsed"
            value={`${result?.elapsed_ms?.toFixed(0) ?? "—"} ms`}
          />
          <StatusDivider />
          <StatusSection
            label="mode"
            value={armed ? "live armed" : "preview only"}
            tone={armed ? "negative" : "muted"}
          />
        </PaneFooter>
      </Pane>
    </div>
  );
}

interface TicketFormProps {
  side: Side;
  onSide: (v: Side) => void;
  orderType: OrderType;
  onOrderType: (v: OrderType) => void;
  tif: Tif;
  onTif: (v: Tif) => void;
  quantity: string;
  onQuantity: (v: string) => void;
  price: string;
  onPrice: (v: string) => void;
  leverage: string;
  onLeverage: (v: string) => void;
  confirmLive: boolean;
  onConfirmLive: (v: boolean) => void;
  onPreview: () => void;
  onSubmitLive: () => void;
  canPreview: boolean;
  canSubmitLive: boolean;
  running: boolean;
  sidecarReady: boolean;
}

function TicketForm({
  side,
  onSide,
  orderType,
  onOrderType,
  tif,
  onTif,
  quantity,
  onQuantity,
  price,
  onPrice,
  leverage,
  onLeverage,
  confirmLive,
  onConfirmLive,
  onPreview,
  onSubmitLive,
  canPreview,
  canSubmitLive,
  running,
  sidecarReady,
}: TicketFormProps): ReactNode {
  return (
    <section style={formStyle} aria-label="Trade ticket form">
      <span style={sectionTitleStyle}>Ticket</span>

      <div style={controlsStackStyle}>
        <SegmentedControl
          label="SIDE"
          value={side}
          options={SIDES}
          onChange={onSide}
          disabled={running}
        />
        <SegmentedControl
          label="TYPE"
          value={orderType}
          options={TYPES}
          onChange={onOrderType}
          disabled={running}
        />
        <SegmentedControl
          label="TIF"
          value={tif}
          options={TIFS}
          onChange={onTif}
          disabled={running}
        />
      </div>

      <FieldRow>
        <Field
          label="Quantity"
          value={quantity}
          onChange={(e) => onQuantity(e.target.value)}
          inputMode="decimal"
          placeholder="0"
          disabled={running}
        />
        {orderType === "LIMIT" && (
          <Field
            label="Limit price"
            value={price}
            onChange={(e) => onPrice(e.target.value)}
            inputMode="decimal"
            placeholder="0"
            disabled={running}
          />
        )}
        <Field
          label="Leverage (optional)"
          value={leverage}
          onChange={(e) => onLeverage(e.target.value)}
          inputMode="decimal"
          placeholder="—"
          disabled={running}
        />
      </FieldRow>

      <div style={actionsRowStyle}>
        <button
          type="button"
          className="btn btn--accent"
          onClick={onPreview}
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
            onChange={(e) => onConfirmLive(e.target.checked)}
            disabled={running}
            aria-describedby="emsx-live-warning"
          />
          <span>I confirm this is a real order</span>
        </label>
        <p id="emsx-live-warning" style={liveWarningStyle}>
          Submitting forwards the ticket to the configured broker. The
          confirm checkbox resets if you edit any ticket field.
        </p>
        <button
          type="button"
          className="btn btn--accent"
          style={liveButtonStyle(canSubmitLive)}
          onClick={onSubmitLive}
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
  );
}

function PreviewSummary({
  running,
  error,
  result,
  lastSubmit,
  fallbackSymbol,
}: {
  running: boolean;
  error: string | null;
  result: FunctionCallResult<EMSXData> | null;
  lastSubmit: boolean;
  fallbackSymbol: string;
}): ReactNode {
  if (running) {
    return (
      <section style={summaryStyle} aria-label="Ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Skeleton height={18} />
        <Skeleton height={14} />
        <Skeleton height={14} width="80%" />
        <Skeleton height={14} width="60%" />
      </section>
    );
  }
  if (error) {
    return (
      <section style={summaryStyle} aria-label="Ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Empty title="Function error" body={error} icon="!" />
      </section>
    );
  }
  if (!result) {
    return (
      <section style={summaryStyle} aria-label="Ticket preview">
        <span style={sectionTitleStyle}>Preview</span>
        <Empty
          title="No preview yet"
          body="Set quantity and press Preview to compute a paper-broker ticket."
          icon="•"
        />
      </section>
    );
  }
  const p = result.data;
  const status = p?.status ?? result.status ?? "—";
  const nextActions = Array.isArray(p?.next_actions) ? p.next_actions : [];
  return (
    <section style={summaryStyle} aria-label="Ticket preview">
      <span style={sectionTitleStyle}>
        Preview {lastSubmit ? "· LIVE" : "· paper"}
      </span>
      <div style={summaryRowsStyle}>
        <SummaryRow
          label="Symbol"
          value={String(p?.symbol ?? fallbackSymbol ?? "—")}
        />
        <SummaryRow
          label="Side"
          value={
            <Pill
              tone={
                String(p?.side ?? "").toUpperCase() === "BUY"
                  ? "positive"
                  : "negative"
              }
              variant="soft"
              withDot={false}
            >
              {String(p?.side ?? "—").toUpperCase()}
            </Pill>
          }
        />
        <SummaryRow
          label="Quantity"
          value={
            <span style={numericStyle}>
              {typeof p?.quantity === "number"
                ? p.quantity.toLocaleString(undefined, {
                    maximumFractionDigits: 8,
                  })
                : "—"}
            </span>
          }
        />
        <SummaryRow
          label="Type"
          value={String(p?.order_type ?? p?.type ?? "—").toUpperCase()}
        />
        <SummaryRow
          label="TIF"
          value={String(p?.time_in_force ?? p?.tif ?? "—").toUpperCase()}
        />
        <SummaryRow
          label="Status"
          value={
            <Pill
              tone={
                status === "filled"
                  ? "positive"
                  : status === "input_required"
                    ? "warn"
                    : "accent"
              }
              variant="soft"
              withDot={false}
            >
              {String(status).toUpperCase()}
            </Pill>
          }
        />
        {p?.order_id && (
          <SummaryRow
            label="Order ID"
            value={<span style={numericStyle}>{String(p.order_id)}</span>}
          />
        )}
        {p?.reason && (
          <div style={reasonStyle}>{String(p.reason)}</div>
        )}
        {nextActions.length > 0 && (
          <div style={nextActionsBoxStyle}>
            <span style={sectionTitleStyle}>Next actions</span>
            <ul style={nextActionsListStyle}>
              {nextActions.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function SummaryRow({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}): ReactNode {
  return (
    <div style={summaryRowStyle}>
      <span style={summaryLabelStyle}>{label}</span>
      <span style={summaryValueStyle}>{value}</span>
    </div>
  );
}

const twoColLayout: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "minmax(280px, 1fr) minmax(280px, 1fr)",
  gap: 14,
  alignItems: "start",
};

const formStyle: CSSProperties = {
  display: "grid",
  gap: 12,
  padding: 12,
  background: "var(--surface-2)",
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
};

const summaryStyle: CSSProperties = {
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

const controlsStackStyle: CSSProperties = {
  display: "grid",
  gap: 8,
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

const summaryRowsStyle: CSSProperties = {
  display: "grid",
  gap: 6,
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

const numericStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontVariantNumeric: "tabular-nums",
  color: "var(--text-primary)",
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
