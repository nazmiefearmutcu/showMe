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
import {
  duplicateAliasIndices,
  isKnownTimeframe,
  TIMEFRAMES,
  validateOperand,
} from "@/lib/validators";

const PRICE_FIELDS = ["close", "open", "high", "low", "volume"];

export function STRAPane() {
  const list = useStrategyStore((s) => s.strategies);
  const draft = useStrategyStore((s) => s.draft);
  const dirty = useStrategyStore((s) => s.dirty);
  const lastPreview = useStrategyStore((s) => s.lastPreview);
  const error = useStrategyStore((s) => s.error);
  const removing = useStrategyStore((s) => s.removing);
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

  // H-UI-4 — alias collision detection.
  const aliasDupIndices = duplicateAliasIndices(
    (draft?.indicators ?? []).map((r) => r.alias),
  );

  // H-UI-3 — unknown timeframe persisted in saved spec.
  const timeframeUnknown = Boolean(draft && !isKnownTimeframe(draft.timeframe));

  // H-UI-10 — dirty switch guard.
  const handleSidebarClick = (id: string) => {
    if (dirty) {
      const ok = window.confirm(
        "Kaydetmediğin değişiklikler kaybolacak. Devam mı?",
      );
      if (!ok) return;
    }
    openExisting(id);
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-1)", padding: 8,
                    overflowY: "auto" }}>
        <button onClick={() => {
          if (dirty) {
            const ok = window.confirm(
              "Kaydetmediğin değişiklikler kaybolacak. Devam mı?",
            );
            if (!ok) return;
          }
          openNew();
        }} style={{ width: "100%", marginBottom: 8 }}>
          + Yeni strateji
        </button>
        {list.map((m) => (
          <button key={m.id} onClick={() => handleSidebarClick(m.id)}
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
                {/* H-UI-3 — surface unknown timeframes. */}
                {timeframeUnknown && draft.timeframe && (
                  <option value={draft.timeframe}
                          data-testid="stra-timeframe-unknown-option">
                    [bilinmeyen] {draft.timeframe}
                  </option>
                )}
                {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            {timeframeUnknown && (
              <div data-testid="stra-field-err-timeframe"
                   style={{ color: "var(--accent-err)", fontSize: 11 }}>
                Bilinmeyen timeframe: "{draft.timeframe}". Listeden seç.
              </div>
            )}

            <h4>Indikatörler</h4>
            <button onClick={() => {
              const id = catalogEntries[0]?.id ?? "rsi";
              const refs: IndicatorRef[] = [...(draft.indicators ?? []),
                { alias: `${id}_${(draft.indicators?.length ?? 0) + 1}`, id, params: {} }];
              setField("indicators", refs);
            }}>+ Indikatör ekle</button>
            {(draft.indicators ?? []).map((r, idx) => {
              const isDup = aliasDupIndices.has(idx);
              return (
                <div key={idx} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                  <input value={r.alias} onChange={(e) => {
                    const refs = [...(draft.indicators ?? [])];
                    refs[idx] = { ...refs[idx], alias: e.target.value };
                    setField("indicators", refs);
                  }}
                    style={{
                      width: 100,
                      border: isDup ? "1px solid var(--accent-err)" : undefined,
                    }}
                    title={isDup ? "Alias başka bir indikatörde de kullanılıyor — benzersiz olmalı." : undefined}
                    data-testid={`stra-indicator-alias-${idx}`}
                    data-dup={isDup ? "1" : undefined}
                    aria-label={`indicator-alias-${idx}`} />
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
              );
            })}
            {aliasDupIndices.size > 0 && (
              <div data-testid="stra-field-err-alias-dup"
                   style={{ color: "var(--accent-err)", fontSize: 11 }}>
                Indikatör alias'ları benzersiz olmalı.
              </div>
            )}

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
              operandOptions={dedupeOperands(operandOptions)}
              testIdPrefix="stra-entry"
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
              operandOptions={dedupeOperands(operandOptions)}
              testIdPrefix="stra-exit"
            />

            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button onClick={() => save()} disabled={!dirty || aliasDupIndices.size > 0 || timeframeUnknown}>
                Kaydet
              </button>
              {(() => {
                const previewDisabled = !draft.id || dirty;
                const previewTitle = previewDisabled
                  ? !draft.id
                    ? "Preview için önce stratejiyi kaydet."
                    : "Kaydedilmemiş değişiklikler var — önce Kaydet."
                  : undefined;
                return (
                  <span title={previewTitle}>
                    <button
                      onClick={() => preview(draft.id!)}
                      disabled={previewDisabled}
                      data-testid="stra-preview-button">
                      Preview
                    </button>
                  </span>
                );
              })()}
              {(!draft.id || dirty) && (
                <span data-testid="stra-preview-hint"
                      style={{ fontSize: 11, color: "var(--fg-2)", alignSelf: "center" }}>
                  {!draft.id ? "(Preview için önce kaydet)" : "(Önce kaydet)"}
                </span>
              )}
              {draft.id && (
                <button
                  data-testid="stra-sil-button"
                  disabled={removing}
                  onClick={() => {
                    // B-C1 — destructive confirm before DELETE; bots referencing
                    // this strategy will be affected.
                    if (!window.confirm("Stratejiyi silmek istediğinden emin misin? Bu stratejiye bağlı bot'lar etkilenebilir.")) {
                      return;
                    }
                    remove(draft.id!);
                  }}
                  style={{ marginLeft: "auto", color: "var(--accent-err)" }}>
                  {removing ? "Siliniyor..." : "Sil"}
                </button>
              )}
            </div>

            {error && (
              <div data-testid="stra-pane-error"
                   style={{ color: "var(--accent-err)" }}>
                {formatPydanticError(error)}
              </div>
            )}

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

/**
 * Avoid duplicate React keys when the user temporarily has duplicate
 * indicator aliases. We display each operand exactly once in the rule
 * dropdowns — the alias-collision UI surfaces the underlying problem.
 */
function dedupeOperands(operands: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const o of operands) {
    if (!seen.has(o)) {
      seen.add(o);
      out.push(o);
    }
  }
  return out;
}

/**
 * Best-effort Pydantic 422 detail formatter (LOW: error message rendering).
 * Falls through to the raw string when the payload isn't JSON.
 */
function formatPydanticError(raw: string): string {
  if (!raw) return raw;
  // Attempt to find a JSON payload inside the message.
  const m = raw.match(/\{[\s\S]*\}$/);
  if (!m) return raw;
  try {
    const body = JSON.parse(m[0]);
    const detail = body?.detail;
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d: { loc?: unknown; msg?: string }) => {
          const loc = Array.isArray(d.loc) ? d.loc.join(".") : String(d.loc ?? "");
          return `${loc}: ${d.msg ?? ""}`.trim();
        })
        .join("; ");
    }
    if (typeof detail === "string") return detail;
  } catch {
    /* fall through */
  }
  return raw;
}

function RulesEditor({
  rules, onChange, operandOptions, testIdPrefix,
}: {
  rules: Rule[];
  onChange: (rs: Rule[]) => void;
  operandOptions: string[];
  testIdPrefix?: string;
}) {
  return (
    <div>
      <button onClick={() => onChange([...rules, { kind: "greater_than", left: "close", right: "literal:0" }])}>
        + Kural ekle
      </button>
      {rules.map((r, idx) => {
        const rightError = validateOperand(r.right, operandOptions);
        return (
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
            }} placeholder="literal:30 ya da alias"
                   aria-label={`rule-${idx}-right`}
                   title={rightError ?? undefined}
                   data-testid={testIdPrefix ? `${testIdPrefix}-rule-${idx}-right` : undefined}
                   style={{
                     flex: 1,
                     border: rightError ? "1px solid var(--accent-err)" : undefined,
                   }} />
            <button onClick={() => onChange(rules.filter((_, i) => i !== idx))}>×</button>
          </div>
        );
      })}
      {rules.some((r) => validateOperand(r.right, operandOptions)) && (
        <div data-testid={testIdPrefix ? `${testIdPrefix}-operand-hint` : undefined}
             style={{ color: "var(--accent-err)", fontSize: 11, marginTop: 4 }}>
          Sayılar için "literal:" öneki kullan (ör. literal:30).
        </div>
      )}
    </div>
  );
}

export default STRAPane;
