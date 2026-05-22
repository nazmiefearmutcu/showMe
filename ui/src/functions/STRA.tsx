/**
 * STRA — Strategy editor. Sub-system E user surface.
 *
 * Left: list of saved strategies + New. Right: form with indicators,
 * entry/exit rules, timeframe, position sizing + Save + Preview.
 */
import { useEffect } from "react";
import {
  useStrategyStore,
  type IndicatorRef, type Rule, type StrategySpec,
} from "@/lib/strategy-store";
import { useIndicatorStore } from "@/lib/indicator-store";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
const PRICE_FIELDS = ["close", "open", "high", "low", "volume"];

export function STRAPane() {
  const list = useStrategyStore((s) => s.strategies);
  const draft = useStrategyStore((s) => s.draft);
  const dirty = useStrategyStore((s) => s.dirty);
  const lastPreview = useStrategyStore((s) => s.lastPreview);
  const error = useStrategyStore((s) => s.error);
  const loadList = useStrategyStore((s) => s.loadList);
  const openNew = useStrategyStore((s) => s.openNew);
  const openExisting = useStrategyStore((s) => s.openExisting);
  const setField = useStrategyStore((s) => s.setDraftField);
  const save = useStrategyStore((s) => s.save);
  const remove = useStrategyStore((s) => s.remove);
  const preview = useStrategyStore((s) => s.preview);

  const catalogEntries = useIndicatorStore((s) => s.entries);
  const loadCatalog = useIndicatorStore((s) => s.loadCatalog);

  useEffect(() => { loadList(); if (catalogEntries.length === 0) loadCatalog(); },
            [loadList, loadCatalog, catalogEntries.length]);

  const operandOptions = (draft?.indicators ?? []).map((r) => r.alias)
    .concat(PRICE_FIELDS);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-1)", padding: 8,
                    overflowY: "auto" }}>
        <button onClick={openNew} style={{ width: "100%", marginBottom: 8 }}>
          + Yeni strateji
        </button>
        {list.map((m) => (
          <button key={m.id} onClick={() => openExisting(m.id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "6px 8px", borderBottom: "1px solid var(--border-1)",
                    background: draft?.id === m.id ? "var(--surface-2)" : "transparent",
                    border: "none", cursor: "pointer",
                  }}>
            <div><strong>{m.name || "(unnamed)"}</strong></div>
            <div style={{ fontSize: 10, color: "var(--fg-2)" }}>{m.timeframe}</div>
          </button>
        ))}
        {list.length === 0 && (
          <div style={{ color: "var(--fg-2)", fontSize: 11, padding: 8 }}>
            Henüz strateji yok.
          </div>
        )}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {!draft && (
          <div style={{ color: "var(--fg-2)" }}>
            Soldan bir strateji seç ya da <strong>+ Yeni strateji</strong>.
          </div>
        )}
        {draft && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h3 style={{ margin: 0 }}>
              {draft.name || "(yeni strateji)"} {dirty && <em style={{ color: "var(--accent-warn)" }}>*</em>}
            </h3>
            <label>
              Ad
              <input value={draft.name ?? ""} onChange={(e) => setField("name", e.target.value)} />
            </label>
            <label>
              Açıklama
              <input value={draft.description ?? ""} onChange={(e) => setField("description", e.target.value)} />
            </label>
            <label>
              Timeframe
              <select value={draft.timeframe ?? "1h"}
                      onChange={(e) => setField("timeframe", e.target.value as StrategySpec["timeframe"])}>
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>

            <h4>Indikatörler</h4>
            <button onClick={() => {
              const id = catalogEntries[0]?.id ?? "rsi";
              const refs: IndicatorRef[] = [...(draft.indicators ?? []),
                { alias: `${id}_${(draft.indicators?.length ?? 0) + 1}`, id, params: {} }];
              setField("indicators", refs);
            }}>+ Indikatör ekle</button>
            {(draft.indicators ?? []).map((r, idx) => (
              <div key={idx} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input value={r.alias} onChange={(e) => {
                  const refs = [...(draft.indicators ?? [])];
                  refs[idx] = { ...refs[idx], alias: e.target.value };
                  setField("indicators", refs);
                }} style={{ width: 100 }} aria-label={`indicator-alias-${idx}`} />
                <select value={r.id} onChange={(e) => {
                  const refs = [...(draft.indicators ?? [])];
                  refs[idx] = { ...refs[idx], id: e.target.value };
                  setField("indicators", refs);
                }}>
                  {catalogEntries.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
                </select>
                <button onClick={() => {
                  const refs = (draft.indicators ?? []).filter((_, i) => i !== idx);
                  setField("indicators", refs);
                }}>×</button>
              </div>
            ))}

            <h4>Entry kuralları (logic:{" "}
              <select value={draft.entry_logic ?? "all"}
                      onChange={(e) => setField("entry_logic", e.target.value as "all" | "any")}>
                <option value="all">tümü</option>
                <option value="any">herhangi</option>
              </select>)
            </h4>
            <RulesEditor
              rules={draft.entry_rules ?? []}
              onChange={(v) => setField("entry_rules", v)}
              operandOptions={operandOptions}
            />

            <h4>Exit kuralları (logic:{" "}
              <select value={draft.exit_logic ?? "any"}
                      onChange={(e) => setField("exit_logic", e.target.value as "all" | "any")}>
                <option value="all">tümü</option>
                <option value="any">herhangi</option>
              </select>)
            </h4>
            <RulesEditor
              rules={draft.exit_rules ?? []}
              onChange={(v) => setField("exit_rules", v)}
              operandOptions={operandOptions}
            />

            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={() => save()} disabled={!dirty}>Kaydet</button>
              <button onClick={() => preview(draft.id!)} disabled={!draft.id || dirty}>
                Preview
              </button>
              {draft.id && (
                <button onClick={() => remove(draft.id!)} style={{ marginLeft: "auto",
                                                                    color: "var(--accent-err)" }}>
                  Sil
                </button>
              )}
            </div>

            {error && <div style={{ color: "var(--accent-err)" }}>{error}</div>}

            {lastPreview && (
              <div style={{ marginTop: 8 }}>
                <h4>Preview ({lastPreview.bars} bar · {lastPreview.source})</h4>
                <ul style={{ fontSize: 12 }}>
                  {lastPreview.events.slice(0, 30).map((e, i) => (
                    <li key={i}>
                      [{e.bar_index}] {e.bar_time} <strong>{e.kind}</strong> @ {e.price.toFixed(2)}
                    </li>
                  ))}
                  {lastPreview.events.length === 0 && <li>(no events)</li>}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function RulesEditor({
  rules, onChange, operandOptions,
}: {
  rules: Rule[];
  onChange: (rs: Rule[]) => void;
  operandOptions: string[];
}) {
  return (
    <div>
      <button onClick={() => onChange([...rules, { kind: "greater_than", left: "close", right: "literal:0" }])}>
        + Kural ekle
      </button>
      {rules.map((r, idx) => (
        <div key={idx} style={{ display: "flex", gap: 4, alignItems: "center", marginTop: 4 }}>
          <select value={r.left} onChange={(e) => {
            const next = [...rules]; next[idx] = { ...next[idx], left: e.target.value };
            onChange(next);
          }} aria-label={`rule-${idx}-left`}>
            {operandOptions.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <select value={r.kind} onChange={(e) => {
            const next = [...rules]; next[idx] = { ...next[idx], kind: e.target.value as Rule["kind"] };
            onChange(next);
          }}>
            {["crosses_above", "crosses_below", "greater_than", "less_than", "equals_approximately"].map((k) =>
              <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}
          </select>
          <input value={r.right} onChange={(e) => {
            const next = [...rules]; next[idx] = { ...next[idx], right: e.target.value };
            onChange(next);
          }} placeholder="literal:30 ya da alias" aria-label={`rule-${idx}-right`}
               style={{ flex: 1 }} />
          <button onClick={() => onChange(rules.filter((_, i) => i !== idx))}>×</button>
        </div>
      ))}
    </div>
  );
}

export default STRAPane;
