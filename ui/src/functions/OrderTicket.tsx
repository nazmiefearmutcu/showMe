/**
 * Sub-system C: <OrderTicket> — manual order placement form.
 *
 * Renders inline inside a trade-permitted CredentialGroup. Hosts the
 * form fields + confirmation modal that gates write. Backend POST
 * /api/broker/orders + the adapter-level _require("trade") in
 * CcxtBroker are the two safety layers; this component enforces the
 * UI-level confirmation as a third (defense in depth).
 */
import { useState } from "react";
import {
  useTradingStore,
  type OrderType,
  type OrderSide,
  type TimeInForce,
} from "@/lib/trading-store";

interface Props {
  credentialId: string;
  brokerName: string;        // "{exchange_id}:{credential_id}"
  accountLabel: string;
}

const ORDER_TYPES: OrderType[] = ["market", "limit", "stop", "stop_limit"];
const TIFS: TimeInForce[] = ["day", "gtc", "ioc", "fok"];

export function OrderTicket({ credentialId, brokerName, accountLabel }: Props) {
  const ticket = useTradingStore((s) => s.ticket);
  const pending = useTradingStore((s) => s.pendingConfirm);
  const submitting = useTradingStore((s) => s.submitting);
  const lastResult = useTradingStore((s) => s.lastResult);
  const isMyTicket = ticket?.credentialId === credentialId;

  const open = useTradingStore((s) => s.openTicket);
  const close = useTradingStore((s) => s.closeTicket);
  const setField = useTradingStore((s) => s.setTicketField);
  const request = useTradingStore((s) => s.requestSubmit);

  if (!isMyTicket) {
    return (
      <div style={{ padding: "8px 0" }}>
        <button onClick={() => open(credentialId, brokerName, accountLabel)}>
          Trade…
        </button>
      </div>
    );
  }

  const t = ticket!;
  const showLimit = t.orderType === "limit" || t.orderType === "stop_limit";
  const showStop = t.orderType === "stop" || t.orderType === "stop_limit";

  return (
    <div style={{ padding: 8, border: "1px solid var(--border-1)", marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <strong>Yeni emir — {brokerName}</strong>
        <button onClick={close} style={{ marginLeft: "auto" }} aria-label="Kapat">×</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        <label>
          Symbol
          <input value={t.symbol}
                 onChange={(e) => setField("symbol", e.target.value.toUpperCase())}
                 placeholder="BTC/USDT" />
        </label>
        <label>
          Side
          <select value={t.side} onChange={(e) => setField("side", e.target.value as OrderSide)}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label>
          Type
          <select value={t.orderType}
                  onChange={(e) => setField("orderType", e.target.value as OrderType)}>
            {ORDER_TYPES.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label>
          Quantity
          <input type="number" step="any" value={t.quantity || ""}
                 onChange={(e) => setField("quantity", parseFloat(e.target.value) || 0)} />
        </label>
        {showLimit && (
          <label>
            Limit price
            <input type="number" step="any" value={t.limitPrice ?? ""}
                   onChange={(e) => setField("limitPrice", e.target.value === "" ? null : parseFloat(e.target.value))} />
          </label>
        )}
        {showStop && (
          <label>
            Stop price
            <input type="number" step="any" value={t.stopPrice ?? ""}
                   onChange={(e) => setField("stopPrice", e.target.value === "" ? null : parseFloat(e.target.value))} />
          </label>
        )}
        <label>
          TIF
          <select value={t.tif} onChange={(e) => setField("tif", e.target.value as TimeInForce)}>
            {TIFS.map((v) => <option key={v} value={v}>{v.toUpperCase()}</option>)}
          </select>
        </label>
        <label>
          Notes
          <input value={t.notes} onChange={(e) => setField("notes", e.target.value)} maxLength={64} />
        </label>
      </div>

      <button
        style={{ marginTop: 8 }}
        onClick={() => request(accountLabel)}
        disabled={!t.symbol || !t.quantity || submitting}
      >
        Continue…
      </button>

      {lastResult && (
        <div style={{ marginTop: 6,
                      color: lastResult.ok ? "var(--accent-ok)" : "var(--accent-err)" }}>
          {lastResult.ok
            ? `Emir gönderildi (id ${lastResult.orderId ?? "?"})`
            : `Hata: ${lastResult.error ?? "bilinmiyor"}`}
        </div>
      )}

      {pending && pending.brokerName === brokerName && <ConfirmModal accountLabel={accountLabel} />}
    </div>
  );
}

function ConfirmModal({ accountLabel }: { accountLabel: string }) {
  const pending = useTradingStore((s) => s.pendingConfirm);
  const submitting = useTradingStore((s) => s.submitting);
  const confirm = useTradingStore((s) => s.confirm);
  const dismiss = useTradingStore((s) => s.dismissConfirm);
  const [typed, setTyped] = useState("");
  if (!pending) return null;

  const verb = pending.kind === "close" ? "kapatma" :
               pending.kind === "cancel" ? "iptal" : "emir";
  const okLabel = typed === accountLabel;

  return (
    <div role="dialog" aria-modal="true"
         style={{
           position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
           display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
         }}>
      <div style={{
        background: "var(--surface-1)", padding: 16, minWidth: 360,
        border: "1px solid var(--border-1)",
      }}>
        <h3 style={{ marginTop: 0 }}>Onay gerekli — {verb}</h3>
        <div style={{ marginBottom: 8, fontSize: 12, color: "var(--fg-2)" }}>
          Gerçek hesapta {verb} işlemi yapılacak.
          Devam etmek için bağlantının <strong>account_label</strong>'ını yaz: <code>{accountLabel}</code>
        </div>
        <input value={typed} onChange={(e) => setTyped(e.target.value)}
               placeholder={accountLabel} autoFocus
               style={{ width: "100%", marginBottom: 8 }} />
        <pre style={{ background: "var(--surface-2)", padding: 8, fontSize: 11,
                      maxHeight: 120, overflow: "auto" }}>
{JSON.stringify(pending.payload, null, 2)}
        </pre>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
          <button onClick={dismiss}>İptal</button>
          <button onClick={() => confirm(typed)}
                  disabled={!okLabel || submitting}
                  style={{ background: okLabel ? "var(--accent-err)" : undefined,
                           color: okLabel ? "white" : undefined }}>
            {submitting ? "…" : "Gönder"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default OrderTicket;
