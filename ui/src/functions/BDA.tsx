/**
 * BDA — Bot Dev Assistant. Sub-system J.
 *
 * Top: textarea + Generate buttons + severity-coded honesty notes + result.
 * Bottom: existing-strategy explain panel.
 *
 * HONESTY: this pane is a keyword/regex helper, NOT a real NLP/LLM. The help
 * caption says so and the backend's "ignored concept" / "default disclosure"
 * notes are surfaced with severity styling (warn / info / negative) instead of
 * a flat gray list, so the user can see exactly what was understood, what was
 * defaulted, and what was silently dropped.
 */
import { useEffect, useRef, useState } from "react";
import { Empty, Pill, Skeleton } from "@/design-system";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";

/** Indicators the keyword parser actually recognises (mirrors the backend
 * ``_KNOWN_INDICATORS`` table — keep accurate). */
const SUPPORTED_INDICATORS =
  "RSI, MACD, EMA, SMA, Bollinger, Stochastic, ATR, ADX, CCI, OBV, " +
  "Williams %R, VWAP, Ichimoku, PSAR, KDJ";

const HELP_CAPTION =
  "Anahtar-kelime tabanlı yardımcı — gerçek NLP değil. Tanınan göstergeler: " +
  SUPPORTED_INDICATORS +
  ". Karmaşık ifadeler (divergence, çoklu-gösterge, risk boyutlandırma) yok sayılır.";

type NoteTone = "warn" | "info" | "negative" | "neutral";

/** Classify a backend note string into a severity tone for honest styling. */
function classifyNote(note: string): NoteTone {
  const low = note.toLowerCase();
  if (
    low.includes("başarısız") ||
    low.includes("hata") ||
    low.includes("validation") ||
    low.includes("katalog")
  ) {
    return "negative";
  }
  if (
    note.includes("⚠") ||
    low.includes("yok sayıl") ||
    low.includes("desteklenm") ||
    low.includes("uyarı") ||
    low.includes("ignored") ||
    low.includes("unsupported")
  ) {
    return "warn";
  }
  if (low.includes("varsayılan") || low.includes("default")) {
    return "info";
  }
  return "neutral";
}

const NOTE_CLASS: Record<NoteTone, string> = {
  warn: "u-text-warn",
  negative: "u-text-negative",
  info: "u-text-mute",
  neutral: "",
};

export function BDAPane() {
  const text = useAssistantStore((s) => s.text);
  const result = useAssistantStore((s) => s.result);
  const explanation = useAssistantStore((s) => s.explanation);
  const loadingGenerate = useAssistantStore((s) => s.loadingGenerate);
  const loadingExplain = useAssistantStore((s) => s.loadingExplain);
  const error = useAssistantStore((s) => s.error);
  const setText = useAssistantStore((s) => s.setText);
  const generate = useAssistantStore((s) => s.generate);
  const explainStrategy = useAssistantStore((s) => s.explainStrategy);

  const strategies = useStrategyStore((s) => s.strategies);
  const loadStrategies = useStrategyStore((s) => s.loadList);

  const [selectedStrategy, setSelectedStrategy] = useState("");
  // Track the last result we cleared the box for, so the post-save clear
  // fires exactly once per successful save.
  const lastClearedSavedId = useRef<string | null>(null);

  useEffect(() => { if (strategies.length === 0) loadStrategies(); },
            [strategies.length, loadStrategies]);

  // F3 — clear the textarea after a successful save (saved_id set).
  useEffect(() => {
    const sid = result?.saved_id ?? null;
    if (sid && lastClearedSavedId.current !== sid) {
      lastClearedSavedId.current = sid;
      setText("");
    }
  }, [result?.saved_id, setText]);

  const hasText = text.trim().length > 0;
  const generateTitle = !hasText
    ? "Strateji metni gerekli."
    : loadingGenerate
      ? "Strateji üretiliyor…"
      : undefined;
  const explainTitle = !selectedStrategy
    ? "Strateji seçilmeli."
    : loadingExplain
      ? "Açıklama yükleniyor…"
      : undefined;

  // F2/F3 — Cmd/Ctrl+Enter triggers generate from the textarea.
  function onTextKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (hasText && !loadingGenerate) generate(false);
    }
  }

  const showGenerateSkeleton = loadingGenerate && !result;
  const showEmpty = !hasText && !result && !loadingGenerate;

  return (
    <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ padding: 16, borderBottom: "1px solid var(--border-card)",
                    overflowY: "auto" }}>
        <h3 style={{ margin: "0 0 4px" }}>Strateji yardımcısı</h3>
        <p id="bda-help" data-testid="bda-help"
           style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)",
                    lineHeight: 1.5, margin: "0 0 8px" }}>
          {HELP_CAPTION}
        </p>

        <label htmlFor="bda-text" className="ds-field__label"
               style={{ display: "block", marginBottom: 4 }}>
          Strateji isteği
        </label>
        <textarea id="bda-text"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={onTextKeyDown}
                  rows={4}
                  style={{ width: "100%", fontFamily: "var(--font-mono)",
                           fontSize: "var(--font-size-sm)" }}
                  placeholder='Örn: "RSI 30 altında alım, 70 üstünde satım, BTC/USDT 1h"'
                  aria-describedby={error ? "bda-help bda-error" : "bda-help"} />

        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {/* H-UI-7 — only disable the generate buttons while generate
              is in-flight, not when explain is running. */}
          <button onClick={() => generate(false)}
                  data-testid="bda-generate-button"
                  aria-busy={loadingGenerate}
                  title={generateTitle}
                  disabled={!hasText || loadingGenerate}>
            {loadingGenerate ? "…" : "Strateji öner"}
          </button>
          <button onClick={() => generate(true)}
                  data-testid="bda-generate-save-button"
                  aria-busy={loadingGenerate}
                  title={generateTitle}
                  disabled={!hasText || loadingGenerate}
                  style={{ background: "var(--positive)", color: "var(--accent-on)" }}>
            {loadingGenerate ? "…" : "Strateji öner + kaydet"}
          </button>
        </div>

        {error && (
          <div id="bda-error" role="status"
               data-testid="bda-error"
               className="u-text-negative"
               style={{ marginTop: 8, fontSize: "var(--font-size-sm)" }}>
            {error}
          </div>
        )}

        {/* F3 — initial empty state before the first parse. */}
        {showEmpty && (
          <div data-testid="bda-empty" style={{ marginTop: 12 }}>
            <Empty
              title="Henüz bir strateji üretilmedi"
              body="Yukarıya bir gösterge + koşul yaz, sonra Strateji öner'e bas (veya ⌘/Ctrl+Enter)."
            />
          </div>
        )}

        {/* F3 — loading skeleton in the result area. */}
        {showGenerateSkeleton && (
          <div data-testid="bda-generate-loading"
               style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
            <Skeleton height={16} />
            <Skeleton height={16} width="80%" />
            <Skeleton height={16} width="60%" />
          </div>
        )}

        {result && (
          <div role="region" aria-label="Strateji üretim sonucu" aria-live="polite"
               data-testid="bda-result" style={{ marginTop: 12 }}>
            <h4 style={{ margin: "0 0 4px" }}>Notlar</h4>
            <ul style={{ fontSize: "var(--font-size-sm)", margin: 0, paddingLeft: 18,
                         display: "flex", flexDirection: "column", gap: 2 }}>
              {result.notes.map((n, i) => {
                const tone = classifyNote(n);
                const isWarn = tone === "warn" || tone === "negative";
                return (
                  <li key={i}
                      className={NOTE_CLASS[tone]}
                      data-testid={isWarn ? "bda-note-warn" : "bda-note"}
                      style={isWarn ? { fontWeight: "var(--font-weight-semibold)" } : undefined}>
                    {n}
                  </li>
                );
              })}
            </ul>

            {result.saved_id && (
              <div data-testid="bda-saved-indicator" style={{ marginTop: 8 }}>
                <Pill tone="positive">
                  Kaydedildi: {result.saved_id.slice(0, 8)} — STRA panelinde düzenleyebilirsin
                </Pill>
              </div>
            )}

            {result.spec && (
              <details style={{ marginTop: 8 }}>
                <summary style={{ fontSize: "var(--font-size-xs)",
                                  color: "var(--text-secondary)" }}>
                  Spec JSON (hata ayıklama)
                </summary>
                <pre style={{ background: "var(--surface-2)", padding: 8,
                              fontFamily: "var(--font-mono)",
                              fontSize: "var(--font-size-xs)", overflow: "auto",
                              maxHeight: 240 }}>
                  {JSON.stringify(result.spec, null, 2)}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: 16, overflowY: "auto" }}>
        <h3 style={{ margin: "0 0 4px" }}>Strateji açıkla</h3>
        <p id="bda-explain-help"
           style={{ color: "var(--text-secondary)", fontSize: "var(--font-size-xs)",
                    lineHeight: 1.5, margin: "0 0 8px" }}>
          Kayıtlı bir stratejinin kural-tabanlı TR özetini gör — şablondan
          üretilir, yapay zeka yazımı değildir.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label htmlFor="bda-strategy-select"
                 style={{ fontSize: "var(--font-size-xs)",
                          color: "var(--text-secondary)" }}>
            Strateji:
          </label>
          <select id="bda-strategy-select"
                  aria-label="Açıklanacak strateji"
                  value={selectedStrategy}
                  onChange={(e) => setSelectedStrategy(e.target.value)}>
            <option value="">— seç —</option>
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={() => selectedStrategy && explainStrategy(selectedStrategy)}
                  data-testid="bda-explain-button"
                  aria-busy={loadingExplain}
                  title={explainTitle}
                  disabled={!selectedStrategy || loadingExplain}>
            {loadingExplain ? "…" : "Açıkla"}
          </button>
        </div>
        {explanation && (
          <div role="status" aria-live="polite"
               data-testid="bda-explanation"
               style={{ marginTop: 12, background: "var(--surface-2)",
                        padding: 12, fontFamily: "var(--font-mono)",
                        fontSize: "var(--font-size-sm)", lineHeight: 1.5,
                        whiteSpace: "pre-wrap" }}>
            {explanation}
          </div>
        )}
      </div>
    </div>
  );
}

export default BDAPane;
