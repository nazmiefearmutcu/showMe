/**
 * TSOX — Treasury / Bond order ticket (preview-only).
 *
 * The sidecar's TSOX inherits EMSXFunction: when `submit=false` (always,
 * from this pane) it returns a paper preview, never reaches a broker.
 * We expose a basic ticket form and a prominent preview-only disclosure
 * — the user is explicitly never given a "submit to broker" button here.
 * That keeps the pane within the "do not execute trades" guardrail while
 * still demonstrating that the backend round-trip works.
 */
import { useCallback, useMemo, useState, type CSSProperties } from "react";
import {
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
import { runFunction, type FunctionCallResult } from "@/lib/functions";
import {
  FunctionControlGroup,
  LoadStatePill,
} from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type Side = "BUY" | "SELL";
type OrderType = "MARKET" | "LIMIT";
type Tif = "GTC" | "DAY" | "IOC" | "FOK";

interface TSOXPayload {
  status?: string;
  reason?: string;
  broker?: string;
  symbol?: string;
  asset_class?: string;
  side?: string;
  quantity?: number;
  order_type?: string;
  time_in_force?: string;
  tif?: string;
  price?: number;
  next_actions?: string[];
}

const TENOR_PRESETS = [
  { id: "2Y", label: "T 2Y", symbol: "TU=F" },
  { id: "5Y", label: "T 5Y", symbol: "ZF=F" },
  { id: "10Y", label: "T 10Y", symbol: "ZN=F" },
  { id: "30Y", label: "T 30Y", symbol: "ZB=F" },
] as const;

export function TSOXPane({ code, symbol }: FunctionPaneProps) {
  const [ticketSymbol, setTicketSymbol] = useState(symbol || "ZN=F");
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");
  const [tif, setTif] = useState<Tif>("GTC");
  const [quantity, setQuantity] = useState("1");
  const [price, setPrice] = useState("100.0625");
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("idle");
  const [result, setResult] = useState<FunctionCallResult<unknown> | null>(null);
  const [error, setError] = useState<Error | null>(null);

  const payload = useMemo<TSOXPayload>(() => {
    const d = result?.data;
    return d && typeof d === "object" && !Array.isArray(d) ? (d as TSOXPayload) : {};
  }, [result]);

  const preview = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      const qty = Number(quantity);
      const limitPrice = orderType === "LIMIT" ? Number(price) : undefined;
      const params: Record<string, unknown> = {
        side,
        quantity: Number.isFinite(qty) ? qty : 0,
        order_type: orderType,
        tif,
        submit: false,
      };
      if (limitPrice != null && Number.isFinite(limitPrice)) params.price = limitPrice;
      const res = await runFunction(code, {
        symbol: ticketSymbol,
        asset_class: "BOND",
        params,
      });
      setResult(res);
      setState("ok");
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
      setState("error");
    }
  }, [code, side, orderType, tif, quantity, price, ticketSymbol]);

  const inputRequired = payload.status === "input_required";
  const previewOk = payload.status === "preview" || (payload.broker === "paper" && !inputRequired);

  return (
    <div className="u-pane-host">
      <Pane>
        <PaneHeader
          code={code}
          title={`Treasury ticket · ${ticketSymbol}`}
          subtitle={`${side} ${quantity} · ${orderType} ${orderType === "LIMIT" ? price : ""} · TIF ${tif}`}
          trailing={
            <FunctionControlGroup>
              <Pill tone="warn" variant="soft">preview only</Pill>
              <Pill tone="muted" variant="soft" withDot={false}>BOND</Pill>
              <LoadStatePill state={state} />
              <button
                type="button"
                onClick={preview}
                disabled={state === "loading" || !quantity.trim()}
                style={primaryActionStyle}
              >
                {state === "loading" ? "Sending…" : "Preview ticket"}
              </button>
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <div className="u-grid-gap-14">
            <div style={previewBannerStyle}>
              <strong className="u-text-warn">Preview-only — no broker submit</strong>
              <span className="u-text-secondary">
                This pane never calls a live broker. The Preview button always
                sends <code>submit=false</code>, so the sidecar returns a paper
                ticket. To submit a real order you must use the broker-direct
                endpoint, not the showMe TSOX function.
              </span>
            </div>

            <section style={presetRow} aria-label="Tenor presets">
              <span className="u-text-secondary" style={{ fontSize: "var(--font-size-xs)" }}>
                Tenor presets:
              </span>
              {TENOR_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setTicketSymbol(p.symbol)}
                  style={{
                    ...presetBtn,
                    color: ticketSymbol === p.symbol ? "var(--accent)" : "var(--text-secondary)",
                    borderColor: ticketSymbol === p.symbol ? "var(--accent)" : "var(--border-subtle)",
                  }}
                  aria-pressed={ticketSymbol === p.symbol}
                >
                  {p.label}
                </button>
              ))}
            </section>

            <section style={formGrid} aria-label="Ticket fields">
              <Field label="Symbol / CUSIP">
                <input
                  type="text"
                  value={ticketSymbol}
                  onChange={(e) => setTicketSymbol(e.target.value)}
                  style={inputStyle}
                />
              </Field>
              <Field label="Side">
                <div style={segmentedRow}>
                  {(["BUY", "SELL"] as Side[]).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSide(s)}
                      style={{
                        ...segmentBtn,
                        color: side === s ? "var(--accent)" : "var(--text-secondary)",
                        borderColor: side === s ? "var(--accent)" : "var(--border-subtle)",
                      }}
                      aria-pressed={side === s}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Quantity (contracts)">
                <input
                  type="number"
                  min="0"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  style={inputStyle}
                />
              </Field>
              <Field label="Order type">
                <div style={segmentedRow}>
                  {(["LIMIT", "MARKET"] as OrderType[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setOrderType(t)}
                      style={{
                        ...segmentBtn,
                        color: orderType === t ? "var(--accent)" : "var(--text-secondary)",
                        borderColor: orderType === t ? "var(--accent)" : "var(--border-subtle)",
                      }}
                      aria-pressed={orderType === t}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </Field>
              <Field label="Limit price">
                <input
                  type="text"
                  value={price}
                  onChange={(e) => setPrice(e.target.value)}
                  disabled={orderType !== "LIMIT"}
                  style={inputStyle}
                />
              </Field>
              <Field label="TIF">
                <div style={segmentedRow}>
                  {(["GTC", "DAY", "IOC", "FOK"] as Tif[]).map((t) => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTif(t)}
                      style={{
                        ...segmentBtn,
                        color: tif === t ? "var(--accent)" : "var(--text-secondary)",
                        borderColor: tif === t ? "var(--accent)" : "var(--border-subtle)",
                      }}
                      aria-pressed={tif === t}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </Field>
            </section>

            {state === "loading" ? (
              <Skeleton height={120} />
            ) : state === "error" ? (
              <Empty title="Function error" body={error?.message ?? "—"} icon="!" />
            ) : !result ? (
              <Empty
                title="No ticket previewed yet"
                body="Set the ticket fields and press Preview to round-trip through the sidecar."
              />
            ) : inputRequired ? (
              <div style={warningBox}>
                <strong className="u-text-warn">Input required</strong>
                <span className="u-text-secondary">
                  {payload.reason ?? "Trade ticket needs a positive quantity."}
                </span>
              </div>
            ) : (
              <div className="u-grid-gap-14">
                <section style={kpiGrid} aria-label="Ticket KPIs">
                  <StatCard
                    label="Status"
                    value={payload.status ?? "—"}
                    caption={`Broker · ${payload.broker ?? "—"}`}
                    tone={previewOk ? "positive" : "negative"}
                  />
                  <StatCard
                    label="Side · Qty"
                    value={`${payload.side ?? side} ${payload.quantity ?? quantity}`}
                    caption={`${payload.order_type ?? orderType} · ${payload.tif ?? tif}`}
                    tone={payload.side === "SELL" ? "negative" : "positive"}
                  />
                  <StatCard
                    label="Price"
                    value={
                      payload.price != null
                        ? String(payload.price)
                        : orderType === "LIMIT"
                          ? price
                          : "MKT"
                    }
                    caption={payload.asset_class ?? "BOND"}
                    tone="neutral"
                  />
                </section>
                {payload.next_actions?.length ? (
                  <div style={hintBox}>
                    <strong className="u-text-secondary">Next actions</strong>
                    <ul style={hintList}>
                      {payload.next_actions.slice(0, 3).map((a, i) => (
                        <li key={i} className="u-text-mute">{a}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <StatusSection label="provider" value={result?.sources?.join(", ") || "paper_ticket"} />
          <StatusDivider />
          <StatusSection label="broker" value={payload.broker ?? "paper"} />
          <StatusDivider />
          <StatusSection label="submit" value="false" />
          <StatusDivider />
          <StatusSection label="elapsed" value={`${result?.elapsed_ms?.toFixed(0) ?? "—"} ms`} />
          <StatusDivider />
          <StatusSection label="mode" value="preview-only" tone="accent" />
        </PaneFooter>
      </Pane>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={fieldStyle}>
      <span style={fieldLabelStyle}>{label}</span>
      {children}
    </label>
  );
}

const previewBannerStyle: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 50%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  padding: "10px 12px",
  display: "grid",
  gap: 4,
};

const presetRow: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  flexWrap: "wrap",
};

const presetBtn: CSSProperties = {
  background: "transparent",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-pill)",
  padding: "2px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  cursor: "pointer",
};

const formGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 10,
  background: "var(--surface-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: 12,
};

const fieldStyle: CSSProperties = {
  display: "grid",
  gap: 4,
};

const fieldLabelStyle: CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-xs)",
  fontWeight: 600,
  color: "var(--text-secondary)",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
};

const inputStyle: CSSProperties = {
  background: "var(--surface-3)",
  color: "var(--text-primary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "6px 10px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
};

const segmentedRow: CSSProperties = {
  display: "flex",
  gap: 4,
};

const segmentBtn: CSSProperties = {
  flex: 1,
  background: "var(--surface-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "5px 8px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontWeight: 700,
  cursor: "pointer",
};

const kpiGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
  gap: 10,
};

const warningBox: CSSProperties = {
  border: "1px solid color-mix(in srgb, var(--warn) 30%, transparent)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const hintBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  background: "var(--surface-2)",
  borderRadius: "var(--radius-sm)",
  padding: "9px 10px",
  display: "grid",
  gap: 4,
};

const hintList: CSSProperties = {
  margin: 0,
  paddingLeft: 18,
  fontSize: "var(--font-size-xs)",
};

const primaryActionStyle: CSSProperties = {
  background: "var(--accent)",
  color: "var(--accent-on)",
  border: "1px solid var(--accent)",
  borderRadius: "var(--radius-sm)",
  padding: "4px 12px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: "var(--font-size-sm)",
  fontWeight: 700,
  cursor: "pointer",
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};
