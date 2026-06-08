/**
 * STRA — Strategy editor. Sub-system E user surface.
 *
 * Left: list of saved strategies + New. Right: form with indicators,
 * entry/exit rules, timeframe, position sizing + Save + Preview.
 */
import { useEffect, useState, type CSSProperties } from "react";
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
import { ConfirmDialog, Empty, Skeleton } from "@/design-system";

const PRICE_FIELDS = ["close", "open", "high", "low", "volume"];

/** P4 DISPLAY — shared bordered-panel style for the Entry / Exit rule groups. */
const RULE_GROUP_STYLE: CSSProperties = {
  border: "1px solid var(--border-card)",
  borderRadius: "var(--radius-md)",
  background: "var(--surface-2)",
  padding: 8,
};

/** Round 24 — typed shape for the pending-confirm intent. */
type PendingConfirm =
  | { kind: "dirty-switch"; target: string | "new" }
  | { kind: "delete"; id: string };

export function STRAPane() {
  const list = useStrategyStore((s) => s.strategies);
  const draft = useStrategyStore((s) => s.draft);
  const dirty = useStrategyStore((s) => s.dirty);
  const lastPreview = useStrategyStore((s) => s.lastPreview);
  const error = useStrategyStore((s) => s.error);
  const removing = useStrategyStore((s) => s.removing);
  // P5 — drive the sidebar empty / loading states off the real `loading` flag.
  const loading = useStrategyStore((s) => s.loading);
  // Round 24 CRITICAL — Save guard. `saving` short-circuits double-click.
  const saving = useStrategyStore((s) => s.saving);
  // Round 24 HIGH — Preview guard.
  const previewing = useStrategyStore((s) => s.previewing);
  const loadList = useStrategyStore((s) => s.loadList);
  const openNew = useStrategyStore((s) => s.openNew);
  const openExisting = useStrategyStore((s) => s.openExisting);
  const setField = useStrategyStore((s) => s.setDraftField);
  const save = useStrategyStore((s) => s.save);
  const remove = useStrategyStore((s) => s.remove);
  const preview = useStrategyStore((s) => s.preview);

  // Round 24 CRITICAL 14 — replace window.confirm with ConfirmDialog so
  // delete + dirty-switch are non-blocking, Esc/backdrop-aware, and the
  // 2nd rapid click can't queue another modal. `pendingConfirm` carries
  // the intent so the user only sees one modal at a time.
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm | null>(null);

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

  // H-UI-10 — dirty switch guard. Round 24 — non-blocking ConfirmDialog
  // replaces window.confirm so the user can Esc out and tabbing still works.
  const handleSidebarClick = (id: string) => {
    if (dirty) {
      setPendingConfirm({ kind: "dirty-switch", target: id });
      return;
    }
    openExisting(id);
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-card)", padding: 8,
                    overflowY: "auto" }}>
        <button onClick={() => {
          if (dirty) {
            setPendingConfirm({ kind: "dirty-switch", target: "new" });
            return;
          }
          openNew();
        }} style={{ width: "100%", marginBottom: 8 }}>
          + Yeni strateji
        </button>
        {list.map((m) => (
          <button key={m.id} onClick={() => handleSidebarClick(m.id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "6px 8px",
                    background: draft?.id === m.id ? "var(--surface-2)" : "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--border-row)",
                    cursor: "pointer",
                  }}>
            <div><strong>{m.name || "(unnamed)"}</strong></div>
            <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>{m.timeframe}</div>
          </button>
        ))}
        {/* P5 — loading placeholder while the list is in flight + still empty. */}
        {loading && list.length === 0 && (
          <div data-testid="stra-list-loading"
               style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8 }}>
            <Skeleton height={28} />
            <Skeleton height={28} />
            <Skeleton height={28} />
          </div>
        )}
        {/* P5 — clear empty-state + CTA when there are genuinely no strategies. */}
        {!loading && list.length === 0 && (
          <div data-testid="stra-list-empty">
            <Empty
              title="Henüz strateji yok"
              body="Yukarıdaki + Yeni strateji ile ilk stratejini oluştur."
            />
          </div>
        )}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {!draft && (
          <div style={{ color: "var(--text-secondary)" }}>
            Soldan bir strateji seç ya da <strong>+ Yeni strateji</strong>.
          </div>
        )}
        {draft && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <h3 style={{ margin: 0 }}>
              {draft.name || "(yeni strateji)"} {dirty && <em style={{ color: "var(--warn)" }}>*</em>}
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
                   style={{ color: "var(--negative)", fontSize: 11 }}>
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
                      border: isDup ? "1px solid var(--negative)" : undefined,
                    }}
                    title={isDup ? "Alias başka bir indikatörde de kullanılıyor — benzersiz olmalı." : undefined}
                    data-testid={`stra-indicator-alias-${idx}`}
                    data-dup={isDup ? "1" : undefined}
                    aria-label={`indicator-alias-${idx}`} />
                  <select value={r.id} onChange={(e) => {
                    const refs = [...(draft.indicators ?? [])];
                    refs[idx] = { ...refs[idx], id: e.target.value };
                    setField("indicators", refs);
                  }} aria-label={`Indicator type ${r.alias || idx}`}>
                    {catalogEntries.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
                  </select>
                  <button
                    aria-label={`Remove indicator ${r.alias || idx}`}
                    onClick={() => {
                      const refs = (draft.indicators ?? []).filter((_, i) => i !== idx);
                      setField("indicators", refs);
                    }}>×</button>
                </div>
              );
            })}
            {aliasDupIndices.size > 0 && (
              <div data-testid="stra-field-err-alias-dup"
                   style={{ color: "var(--negative)", fontSize: 11 }}>
                Indikatör alias'ları benzersiz olmalı.
              </div>
            )}

            {/* P4 DISPLAY — group Entry rules in a bordered panel so it is
                clear which rules + which logic selector belong together. */}
            <section data-testid="stra-entry-group" style={RULE_GROUP_STYLE}>
              <h4 style={{ margin: "0 0 6px" }}>Entry kuralları (logic:{" "}
                <select value={draft.entry_logic ?? "all"}
                        aria-label="Entry logic"
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
            </section>

            {/* P4 DISPLAY — Exit rules in their own bordered panel. */}
            <section data-testid="stra-exit-group" style={RULE_GROUP_STYLE}>
              <h4 style={{ margin: "0 0 6px" }}>Exit kuralları (logic:{" "}
                <select value={draft.exit_logic ?? "any"}
                        aria-label="Exit logic"
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
            </section>

            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button
                data-testid="stra-save-button"
                onClick={() => {
                  // Round 24 CRITICAL 2 — local short-circuit; store-level
                  // `if (get().saving) return null` is the canonical seal.
                  if (saving) return;
                  void save();
                }}
                disabled={
                  saving || !dirty || aliasDupIndices.size > 0 || timeframeUnknown
                }
                // P3 A11Y — explain WHY Save is disabled (duplicate aliases /
                // invalid timeframe / no unsaved changes / save in flight).
                title={
                  saving
                    ? "Kaydediliyor…"
                    : aliasDupIndices.size > 0
                      ? "Indikatör alias'ları benzersiz olmalı."
                      : timeframeUnknown
                        ? "Geçersiz timeframe — listeden seç."
                        : !dirty
                          ? "Kaydedilecek değişiklik yok."
                          : undefined
                }>
                {saving ? "Kaydediliyor..." : "Kaydet"}
              </button>
              {(() => {
                // Round 24 HIGH 13 — disable Preview while one is in flight.
                const previewDisabled = !draft.id || dirty || previewing;
                const previewTitle = previewDisabled
                  ? !draft.id
                    ? "Preview için önce stratejiyi kaydet."
                    : dirty
                      ? "Kaydedilmemiş değişiklikler var — önce Kaydet."
                      : "Preview zaten çalışıyor…"
                  : undefined;
                return (
                  <span title={previewTitle}>
                    <button
                      onClick={() => {
                        // Round 24 HIGH — local short-circuit + store guard.
                        if (previewing || !draft.id || dirty) return;
                        void preview(draft.id);
                      }}
                      disabled={previewDisabled}
                      data-testid="stra-preview-button">
                      {previewing ? "Yükleniyor…" : "Preview"}
                    </button>
                  </span>
                );
              })()}
              {(!draft.id || dirty) && (
                <span data-testid="stra-preview-hint"
                      style={{ fontSize: 11, color: "var(--text-secondary)", alignSelf: "center" }}>
                  {!draft.id ? "(Preview için önce kaydet)" : "(Önce kaydet)"}
                </span>
              )}
            {draft.id && (
                <button
                  data-testid="stra-sil-button"
                  aria-label="Delete strategy"
                  disabled={removing}
                  onClick={() => {
                    // Round 24 CRITICAL 14 — replace blocking window.confirm
                    // with ConfirmDialog; store-level `removing` short-circuits
                    // the 2nd rapid click.
                    if (removing) return;
                    setPendingConfirm({ kind: "delete", id: draft.id! });
                  }}
                  style={{ marginLeft: "auto", color: "var(--negative)" }}>
                  {removing ? "Siliniyor..." : "Sil"}
                </button>
              )}
            </div>

            {error && (
              <div data-testid="stra-pane-error"
                   style={{ color: "var(--negative)" }}>
                {formatPydanticError(error)}
              </div>
            )}

            {lastPreview && (
              <div style={{ marginTop: 8 }}>
                <h4>Preview ({lastPreview.bars} bar · {lastPreview.source})</h4>
                {/* P1 DATA HONESTY — drive the synthetic disclosure off the
                    backend's real `source` field so it stays truthful if a
                    real-OHLCV preview path ever lands. We only warn when the
                    backend explicitly says the data is synthetic. */}
                {isSyntheticSource(lastPreview.source) && (
                  <div
                    data-testid="stra-preview-synthetic-note"
                    role="note"
                    style={{
                      color: "var(--text-secondary)",
                      fontSize: 11,
                      margin: "0 0 6px",
                      padding: "4px 8px",
                      border: "1px solid var(--border-card)",
                      borderRadius: "var(--radius-md)",
                      background: "var(--surface-2)",
                    }}>
                    ⚠ Preview runs on synthetic random-walk data — validates
                    whether rules fire, NOT real market performance.
                  </div>
                )}
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

      {/* Round 24 CRITICAL 14 + dirty-switch — non-blocking confirm dialog.
          One <ConfirmDialog> for both intents; the body text + handler
          branch off pendingConfirm.kind. */}
      <ConfirmDialog
        open={pendingConfirm !== null}
        title={pendingConfirm?.kind === "delete"
          ? "Stratejiyi sil"
          : "Kaydedilmemiş değişiklikler"}
        body={pendingConfirm?.kind === "delete"
          ? "Stratejiyi silmek istediğinden emin misin? Bu stratejiye bağlı bot'lar etkilenebilir."
          : "Kaydetmediğin değişiklikler kaybolacak. Devam mı?"}
        confirmLabel={pendingConfirm?.kind === "delete" ? "Sil" : "Devam et"}
        destructive={pendingConfirm?.kind === "delete"}
        busy={removing}
        onConfirm={() => {
          if (!pendingConfirm) return;
          if (pendingConfirm.kind === "delete") {
            // Store-level `removing` guard ensures the underlying remove()
            // is single-flight even if React renders this onConfirm twice.
            // `skipConfirm` avoids a second native confirmation in this
            // component's ConfirmDialog flow.
            void remove(pendingConfirm.id, { skipConfirm: true });
          } else if (pendingConfirm.kind === "dirty-switch") {
            if (pendingConfirm.target === "new") openNew();
            else openExisting(pendingConfirm.target);
          }
          setPendingConfirm(null);
        }}
        onCancel={() => setPendingConfirm(null)}
      />
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
 * P1 DATA HONESTY — is the preview's data source synthetic?
 *
 * The backend currently returns "synthetic_random_walk" (POST /preview runs
 * a seeded random walk, NOT real market data). We key off the substring so a
 * future real-OHLCV source (e.g. "exchange_ohlcv") does NOT trip the warning.
 */
function isSyntheticSource(source: string | undefined): boolean {
  return typeof source === "string" && source.toLowerCase().includes("synthetic");
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
          // P4 DISPLAY — fixed grid so left-operand / operator / right-operand
          // + delete line up across rows instead of drifting with flex.
          <div key={idx} style={{
            display: "grid",
            gridTemplateColumns: "140px 140px 1fr auto",
            gap: 4, alignItems: "center", marginTop: 4,
          }}>
            <select value={r.left} onChange={(e) => {
              const next = [...rules]; next[idx] = { ...next[idx], left: e.target.value };
              onChange(next);
            }} aria-label={`rule-${idx}-left`}>
              {operandOptions.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
            <select value={r.kind} onChange={(e) => {
              const next = [...rules]; next[idx] = { ...next[idx], kind: e.target.value as Rule["kind"] };
              onChange(next);
            }} aria-label={`Rule ${idx} operator`}>
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
                   // P4 — mono tabular numerals for the threshold/right operand.
                   className="terminal-grid-numeric"
                   style={{
                     width: "100%",
                     border: rightError ? "1px solid var(--negative)" : undefined,
                   }} />
            <button
              aria-label={`Remove rule ${idx}`}
              onClick={() => onChange(rules.filter((_, i) => i !== idx))}>×</button>
          </div>
        );
      })}
      {rules.some((r) => validateOperand(r.right, operandOptions)) && (
        <div data-testid={testIdPrefix ? `${testIdPrefix}-operand-hint` : undefined}
             style={{ color: "var(--negative)", fontSize: 11, marginTop: 4 }}>
          Sayılar için "literal:" öneki kullan (ör. literal:30).
        </div>
      )}
    </div>
  );
}

export default STRAPane;
