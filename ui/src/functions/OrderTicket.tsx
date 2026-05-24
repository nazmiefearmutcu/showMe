/**
 * Sub-system C: <OrderTicket> — manual order placement form.
 *
 * Renders inline inside a trade-permitted CredentialGroup. Hosts the
 * form fields + confirmation modal that gates write. Backend POST
 * /api/broker/orders + the adapter-level _require("trade") in
 * CcxtBroker are the two safety layers; this component enforces the
 * UI-level confirmation as a third (defense in depth).
 *
 * QA-2026-05-23 fixes:
 *  - Symbol validation uses `isValidSymbolForExchange()` — accepts spot
 *    (`BTC/USDT`), ccxt-swap (`BTC/USDT:USDT`), Deribit/dYdX perp
 *    (`BTC-PERP`), and Alpaca equity (`AAPL`, `BRK.B`). Previously the
 *    regex was hard-coded to spot, which rejected 60+ exchanges in the
 *    catalog.
 *  - Numeric inputs no longer use `parseFloat(...) || 0` — the silent
 *    NaN→0 coalesce ate user typos. Each field tracks its own raw string
 *    + parsed number + error flag; Continue stays disabled until every
 *    visible numeric field is finite-positive.
 *  - When the modal closes, `clearLastResult()` is fired so the toast in
 *    PORT.tsx doesn't double-fire on the next ticket.
 */
import { useEffect, useState } from "react";
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

// Permissive symbol shapes the broker layer actually accepts.
// Ordered most-specific first so the spot rule doesn't swallow a
// `BTC/USDT:USDT` swap suffix.
const SYMBOL_SHAPE_SWAP = /^[A-Z0-9]+\/[A-Z0-9]+:[A-Z0-9]+$/;   // BTC/USDT:USDT
const SYMBOL_SHAPE_SPOT = /^[A-Z0-9]+\/[A-Z0-9]+$/;             // BTC/USDT
const SYMBOL_SHAPE_PERP = /^[A-Z0-9]+-PERP$/;                   // BTC-PERP
const SYMBOL_SHAPE_EQUITY = /^[A-Z][A-Z0-9.]{0,9}$/;            // AAPL, BRK.B

const EQUITY_EXCHANGE_IDS = new Set(["alpaca"]);
const PERP_EXCHANGE_IDS = new Set(["deribit", "dydx"]);

/**
 * Decide which symbol shape(s) are valid for the selected exchange adapter.
 * `brokerName` is "{exchange_id}:{credential_id}"; the exchange id picks the
 * rule. Unknown exchanges accept the spot OR swap shapes (the dominant ccxt
 * pattern across the catalog).
 */
export function isValidSymbolForExchange(symbol: string, exchangeId: string): boolean {
  const id = exchangeId.toLowerCase();
  if (EQUITY_EXCHANGE_IDS.has(id)) {
    return SYMBOL_SHAPE_EQUITY.test(symbol);
  }
  if (PERP_EXCHANGE_IDS.has(id)) {
    // Deribit/dYdX accept both PERP and ccxt-swap forms in practice.
    return SYMBOL_SHAPE_PERP.test(symbol) || SYMBOL_SHAPE_SWAP.test(symbol);
  }
  // Default: spot or swap. The order matters — try the longer pattern first
  // so the spot rule can't half-match a swap suffix.
  return SYMBOL_SHAPE_SWAP.test(symbol) || SYMBOL_SHAPE_SPOT.test(symbol);
}

function exchangeIdFromBrokerName(brokerName: string): string {
  const idx = brokerName.indexOf(":");
  return idx >= 0 ? brokerName.slice(0, idx) : brokerName;
}

/**
 * Parse a numeric input. Returns `null` if the field is empty (which means
 * "no value") or non-finite. Non-finite is the explicit error case — the
 * caller decides whether `null` is allowed (e.g. limit_price is null on
 * market orders) or disqualifying (quantity must be > 0).
 */
function parseNumericInput(raw: string): { value: number | null; error: boolean } {
  const trimmed = raw.trim();
  if (trimmed === "") return { value: null, error: false };
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return { value: null, error: true };
  return { value: parsed, error: false };
}

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

  // Raw strings + parse errors for the three numeric fields. Stored separate
  // from the ticket so we can keep the user's typo on screen without polluting
  // the payload that goes to the API.
  const [qtyRaw, setQtyRaw] = useState("");
  const [qtyErr, setQtyErr] = useState(false);
  const [limitRaw, setLimitRaw] = useState("");
  const [limitErr, setLimitErr] = useState(false);
  const [stopRaw, setStopRaw] = useState("");
  const [stopErr, setStopErr] = useState(false);
  const [symbolErr, setSymbolErr] = useState(false);

  useEffect(() => {
    // Reset the raw-string mirrors when a new ticket is opened.
    if (!isMyTicket) {
      setQtyRaw(""); setQtyErr(false);
      setLimitRaw(""); setLimitErr(false);
      setStopRaw(""); setStopErr(false);
      setSymbolErr(false);
    }
  }, [isMyTicket]);

  if (!isMyTicket) {
    return (
      <div style={{ padding: "8px 0" }}>
        <button
          onClick={() => open(credentialId, brokerName, accountLabel)}
          data-testid="order-ticket-trade-btn"
        >
          Trade…
        </button>
      </div>
    );
  }

  const t = ticket!;
  const showLimit = t.orderType === "limit" || t.orderType === "stop_limit";
  const showStop = t.orderType === "stop" || t.orderType === "stop_limit";

  const exchangeId = exchangeIdFromBrokerName(brokerName);
  const symbolValid = isValidSymbolForExchange(t.symbol, exchangeId);
  const symbolPlaceholder = EQUITY_EXCHANGE_IDS.has(exchangeId.toLowerCase())
    ? "AAPL"
    : PERP_EXCHANGE_IDS.has(exchangeId.toLowerCase())
      ? "BTC-PERP"
      : "BTC/USDT";
  const symbolHint = EQUITY_EXCHANGE_IDS.has(exchangeId.toLowerCase())
    ? "Beklenen format: TICKER (örn. AAPL, BRK.B)."
    : PERP_EXCHANGE_IDS.has(exchangeId.toLowerCase())
      ? "Beklenen format: BASE-PERP veya BASE/QUOTE:QUOTE."
      : "Beklenen format: BASE/QUOTE veya BASE/QUOTE:QUOTE.";
  const qtyValid = !qtyErr && Number.isFinite(t.quantity) && t.quantity > 0;
  const limitValid = !showLimit || (!limitErr && t.limitPrice != null && t.limitPrice > 0);
  const stopValid = !showStop || (!stopErr && t.stopPrice != null && t.stopPrice > 0);
  const formValid = symbolValid && qtyValid && limitValid && stopValid && !submitting;

  return (
    <div style={{ padding: 8, border: "1px solid var(--border-1)", marginTop: 8 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
        <strong>Yeni emir — {brokerName}</strong>
        <button onClick={close} style={{ marginLeft: "auto" }} aria-label="Kapat">×</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        <label>
          Symbol
          <input
            value={t.symbol}
            onChange={(e) => {
              const v = e.target.value.toUpperCase();
              setField("symbol", v);
              setSymbolErr(v.length > 0 && !isValidSymbolForExchange(v, exchangeId));
            }}
            placeholder={symbolPlaceholder}
            maxLength={24}
            autoComplete="off"
            spellCheck={false}
            data-testid="order-ticket-symbol-input"
            aria-invalid={symbolErr || undefined}
          />
          {symbolErr && (
            <div
              data-testid="order-ticket-symbol-err"
              style={{ color: "var(--accent-err)", fontSize: 11 }}
            >
              {symbolHint}
            </div>
          )}
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
          <input
            type="number"
            step="any"
            min="0"
            inputMode="decimal"
            value={qtyRaw}
            onChange={(e) => {
              const raw = e.target.value;
              setQtyRaw(raw);
              const { value, error } = parseNumericInput(raw);
              setQtyErr(error || (value !== null && value <= 0));
              setField("quantity", value ?? 0);
            }}
            data-testid="order-ticket-quantity-input"
            aria-invalid={qtyErr || undefined}
          />
          {qtyErr && (
            <div
              data-testid="order-ticket-quantity-err"
              style={{ color: "var(--accent-err)", fontSize: 11 }}
            >
              Geçerli pozitif sayı girin.
            </div>
          )}
        </label>
        {showLimit && (
          <label>
            Limit price
            <input
              type="number"
              step="any"
              min="0"
              inputMode="decimal"
              value={limitRaw}
              onChange={(e) => {
                const raw = e.target.value;
                setLimitRaw(raw);
                const { value, error } = parseNumericInput(raw);
                setLimitErr(error || (value !== null && value <= 0));
                setField("limitPrice", value);
              }}
              data-testid="order-ticket-limit-input"
              aria-invalid={limitErr || undefined}
            />
            {limitErr && (
              <div
                data-testid="order-ticket-limit-err"
                style={{ color: "var(--accent-err)", fontSize: 11 }}
              >
                Limit fiyatı pozitif olmalı.
              </div>
            )}
          </label>
        )}
        {showStop && (
          <label>
            Stop price
            <input
              type="number"
              step="any"
              min="0"
              inputMode="decimal"
              value={stopRaw}
              onChange={(e) => {
                const raw = e.target.value;
                setStopRaw(raw);
                const { value, error } = parseNumericInput(raw);
                setStopErr(error || (value !== null && value <= 0));
                setField("stopPrice", value);
              }}
              data-testid="order-ticket-stop-input"
              aria-invalid={stopErr || undefined}
            />
            {stopErr && (
              <div
                data-testid="order-ticket-stop-err"
                style={{ color: "var(--accent-err)", fontSize: 11 }}
              >
                Stop fiyatı pozitif olmalı.
              </div>
            )}
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
        onClick={() => request(accountLabel || t.accountLabel)}
        disabled={!formValid}
        data-testid="order-ticket-continue-btn"
      >
        Continue…
      </button>

      {lastResult && lastResult.kind === "submit" && (
        <div
          data-testid="order-ticket-last-result"
          style={{ marginTop: 6,
                   color: lastResult.ok ? "var(--accent-ok)" : "var(--accent-err)" }}>
          {lastResult.ok
            ? `Emir gönderildi (id ${lastResult.orderId ?? "?"})`
            : `Hata: ${lastResult.error ?? "bilinmiyor"}`}
        </div>
      )}

      {pending && pending.brokerName === brokerName && pending.kind === "submit" && (
        <ConfirmModal accountLabel={accountLabel || t.accountLabel} />
      )}
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
  // Source-of-truth for the expected label is the pendingConfirm itself —
  // the prop is just a hint that may lag behind on rapid state changes.
  const expected = pending.accountLabel || accountLabel;
  const okLabel = expected.length > 0 && typed === expected;

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
          {expected ? (
            <>
              Gerçek hesapta {verb} işlemi yapılacak.
              Devam etmek için bağlantının <strong>account_label</strong>'ını yaz: <code>{expected}</code>
            </>
          ) : (
            <span style={{ color: "var(--accent-err)" }}>
              Aktif hesap seçilmedi (account_label boş). İşlem reddedilecek.
            </span>
          )}
        </div>
        <input value={typed} onChange={(e) => setTyped(e.target.value)}
               placeholder={expected}
               disabled={!expected}
               autoFocus
               data-testid="confirm-modal-typed-input"
               style={{ width: "100%", marginBottom: 8 }} />
        <pre style={{ background: "var(--surface-2)", padding: 8, fontSize: 11,
                      maxHeight: 120, overflow: "auto" }}>
{JSON.stringify(pending.payload, null, 2)}
        </pre>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
          <button onClick={dismiss} data-testid="confirm-modal-cancel-btn">İptal</button>
          <button onClick={() => confirm(typed)}
                  disabled={!okLabel || submitting}
                  data-testid="confirm-modal-confirm-btn"
                  style={{ background: okLabel ? "var(--accent-err)" : undefined,
                           color: okLabel ? "white" : undefined }}>
            {submitting ? "…" : "Gönder"}
          </button>
        </div>
      </div>
    </div>
  );
}

export { ConfirmModal };
export default OrderTicket;
