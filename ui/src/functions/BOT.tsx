/**
 * BOT — Bot manager pane (sub-system D).
 *
 * Left: list of bots with status pills. Right: form with strategy
 * picker (from strategy-store), credential picker (from exchange-store),
 * symbol/timeframe/tick inputs, mode toggle, signal log viewer.
 */
import { useEffect, useState } from "react";
import {
  useBotStore, type BotRecord, type SignalEntry,
} from "@/lib/bot-store";
import { useStrategyStore } from "@/lib/strategy-store";
import { useExchangeStore } from "@/lib/exchange-store";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

function StatusPill({ rec }: { rec: { mode: string; enabled: boolean } }) {
  const live = rec.mode === "live";
  const color = !rec.enabled ? "var(--fg-2)"
              : live ? "var(--accent-err)"
              : "var(--accent-warn)";
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, color, border: `1px solid ${color}`,
      padding: "1px 6px", borderRadius: 4,
    }}>
      {rec.enabled ? (live ? "LIVE" : "SHADOW") : "OFF"}
    </span>
  );
}

function SignalLog({ entries }: { entries: SignalEntry[] }) {
  if (entries.length === 0) return <div style={{ color: "var(--fg-2)" }}>(no signals yet)</div>;
  return (
    <table style={{ width: "100%", fontSize: 11 }}>
      <thead>
        <tr style={{ color: "var(--fg-2)" }}>
          <th align="left">Time</th><th>Kind</th><th align="right">Price</th>
          <th>Action</th><th align="left">Detail</th>
        </tr>
      </thead>
      <tbody>
        {entries.slice(-20).reverse().map((e, i) => (
          <tr key={i}>
            <td>{e.bar_time.slice(0, 19)}</td>
            <td style={{ color: e.kind === "entry" ? "var(--accent-ok)" : "var(--accent-warn)" }}>
              {e.kind}
            </td>
            <td align="right">{e.price.toFixed(2)}</td>
            <td>{e.action}</td>
            <td>{e.error || e.order_id || ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BOTPane() {
  const list = useBotStore((s) => s.bots);
  const draft = useBotStore((s) => s.draft);
  const dirty = useBotStore((s) => s.dirty);
  const error = useBotStore((s) => s.error);
  const loadList = useBotStore((s) => s.loadList);
  const openNew = useBotStore((s) => s.openNew);
  const openExisting = useBotStore((s) => s.openExisting);
  const setField = useBotStore((s) => s.setDraftField);
  const save = useBotStore((s) => s.save);
  const remove = useBotStore((s) => s.remove);
  const enable = useBotStore((s) => s.enable);
  const disable = useBotStore((s) => s.disable);

  const strategies = useStrategyStore((s) => s.strategies);
  const loadStrategies = useStrategyStore((s) => s.loadList);
  const credentials = useExchangeStore((s) => s.credentials);
  const loadCredentials = useExchangeStore((s) => s.loadCredentials);

  const [confirmLabel, setConfirmLabel] = useState("");

  useEffect(() => {
    loadList();
    if (strategies.length === 0) loadStrategies();
    if (credentials.length === 0) loadCredentials();
  }, [loadList, loadStrategies, loadCredentials, strategies.length, credentials.length]);

  const credential = credentials.find((c) => c.id === draft?.credential_id);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-1)", padding: 8, overflowY: "auto" }}>
        <button onClick={openNew} style={{ width: "100%", marginBottom: 8 }}>
          + Yeni bot
        </button>
        {list.map((b) => (
          <button key={b.id} onClick={() => openExisting(b.id)}
                  style={{
                    display: "grid", gridTemplateColumns: "1fr auto",
                    gap: 6, alignItems: "center", padding: "6px 8px",
                    width: "100%", textAlign: "left",
                    background: draft?.id === b.id ? "var(--surface-2)" : "transparent",
                    border: "none", borderBottom: "1px solid var(--border-1)",
                    cursor: "pointer",
                  }}>
            <div>
              <div><strong>{b.symbol}</strong></div>
              <div style={{ fontSize: 10, color: "var(--fg-2)" }}>
                {b.exchange_id} · {b.timeframe}
              </div>
            </div>
            <StatusPill rec={b} />
          </button>
        ))}
        {list.length === 0 && (
          <div style={{ color: "var(--fg-2)", fontSize: 11, padding: 8 }}>
            Henüz bot yok.
          </div>
        )}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {!draft && (
          <div style={{ color: "var(--fg-2)" }}>
            Soldan bir bot seç ya da <strong>+ Yeni bot</strong>.
          </div>
        )}
        {draft && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h3 style={{ margin: 0 }}>
              {draft.symbol || "(yeni bot)"} {dirty && <em style={{ color: "var(--accent-warn)" }}>*</em>}
              {draft.id && <span style={{ marginLeft: 8 }}><StatusPill rec={draft as BotRecord} /></span>}
            </h3>
            <label>
              Strateji
              <select value={draft.strategy_id ?? ""}
                      onChange={(e) => setField("strategy_id", e.target.value)}>
                <option value="">— seç —</option>
                {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <label>
              Bağlantı
              <select value={draft.credential_id ?? ""}
                      onChange={(e) => {
                        const c = credentials.find((x) => x.id === e.target.value);
                        setField("credential_id", e.target.value);
                        if (c) setField("exchange_id", c.exchange_id);
                      }}>
                <option value="">— seç —</option>
                {credentials.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.exchange_id}:{c.account_label} ({c.permissions.join("+")})
                  </option>
                ))}
              </select>
            </label>
            <label>
              Symbol
              <input value={draft.symbol ?? ""} onChange={(e) => setField("symbol", e.target.value.toUpperCase())}
                     placeholder="BTC/USDT" />
            </label>
            <label>
              Timeframe
              <select value={draft.timeframe ?? "1h"}
                      onChange={(e) => setField("timeframe", e.target.value as BotRecord["timeframe"])}>
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label>
              Tick interval (saniye)
              <input type="number" min={5} max={3600}
                     value={draft.tick_interval_seconds ?? 60}
                     onChange={(e) => setField("tick_interval_seconds", parseInt(e.target.value) || 60)} />
            </label>

            <fieldset style={{ borderColor: "var(--border-1)", padding: 8 }}>
              <legend>Mod</legend>
              <label>
                <input type="radio" checked={draft.mode === "shadow"}
                       onChange={() => setField("mode", "shadow")} />
                Shadow (sadece signal log)
              </label>
              <br />
              <label style={{ color: "var(--accent-err)" }}>
                <input type="radio" checked={draft.mode === "live"}
                       onChange={() => setField("mode", "live")} />
                Live (gerçek emir)
              </label>
            </fieldset>

            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              <button onClick={() => save()} disabled={!dirty}>Kaydet</button>
              {draft.id && !draft.enabled && (
                <>
                  {draft.mode === "live" && (
                    <input placeholder={`account_label tekrar yaz`}
                           value={confirmLabel}
                           onChange={(e) => setConfirmLabel(e.target.value)}
                           style={{ width: 160 }} />
                  )}
                  <button onClick={() => {
                    if (draft.mode === "live") {
                      enable(draft.id!, confirmLabel);
                    } else {
                      enable(draft.id!);
                    }
                  }} disabled={dirty || (draft.mode === "live" && confirmLabel !== credential?.account_label)}>
                    Etkinleştir
                  </button>
                </>
              )}
              {draft.id && draft.enabled && (
                <button onClick={() => disable(draft.id!)}>Durdur</button>
              )}
              {draft.id && (
                <button onClick={() => remove(draft.id!)}
                        style={{ marginLeft: "auto", color: "var(--accent-err)" }}>
                  Sil
                </button>
              )}
            </div>

            {error && <div style={{ color: "var(--accent-err)" }}>{error}</div>}

            <h4>Signal log ({(draft.signal_log ?? []).length})</h4>
            <SignalLog entries={draft.signal_log ?? []} />
          </div>
        )}
      </div>
    </div>
  );
}

export default BOTPane;
