/**
 * BDA — Bot Dev Assistant. Sub-system J.
 *
 * Top: textarea + Generate buttons + result preview.
 * Bottom: existing-strategy explain panel.
 */
import { useEffect, useState } from "react";
import { useAssistantStore } from "@/lib/assistant-store";
import { useStrategyStore } from "@/lib/strategy-store";

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

  useEffect(() => { if (strategies.length === 0) loadStrategies(); },
            [strategies.length, loadStrategies]);

  return (
    <div style={{ display: "grid", gridTemplateRows: "1fr 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ padding: 16, borderBottom: "1px solid var(--border-1)",
                    overflowY: "auto" }}>
        <h3>NL → Strateji</h3>
        <p style={{ color: "var(--fg-2)", fontSize: 12 }}>
          Doğal dilde bir strateji yaz. Örnek: "RSI 30 altında alım, 70 üstünde satım yap, BTC/USDT 1h"
        </p>
        <textarea value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={4} style={{ width: "100%", fontFamily: "inherit" }}
                  placeholder="Strateji isteğini buraya yaz…"
                  aria-label="Strategy request" />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {/* H-UI-7 — only disable the generate buttons while generate
              is in-flight, not when explain is running. */}
          <button onClick={() => generate(false)}
                  data-testid="bda-generate-button"
                  disabled={!text.trim() || loadingGenerate}>
            {loadingGenerate ? "..." : "Strateji öner"}
          </button>
          <button onClick={() => generate(true)}
                  data-testid="bda-generate-save-button"
                  disabled={!text.trim() || loadingGenerate}
                  style={{ background: "var(--accent-ok)", color: "white" }}>
            Strateji öner + kaydet
          </button>
        </div>
        {error && <div style={{ color: "var(--accent-err)", marginTop: 8 }}>{error}</div>}
        {result && (
          <div style={{ marginTop: 12 }}>
            <h4>Notlar</h4>
            <ul style={{ fontSize: 12 }}>
              {result.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
            {result.saved_id && (
              <div data-testid="bda-saved-indicator"
                   style={{ color: "var(--accent-ok)" }}>
                Kaydedildi: {result.saved_id.slice(0, 8)} (STRA panelinde düzenleyebilirsin)
              </div>
            )}
            {result.spec && (
              <details style={{ marginTop: 8 }}>
                <summary>Spec JSON</summary>
                <pre style={{ background: "var(--surface-2)", padding: 8,
                              fontSize: 10, overflow: "auto", maxHeight: 240 }}>
                  {JSON.stringify(result.spec, null, 2)}
                </pre>
              </details>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: 16, overflowY: "auto" }}>
        <h3>Strateji açıkla</h3>
        <p style={{ color: "var(--fg-2)", fontSize: 12 }}>
          Kayıtlı bir stratejinin TR-dili özetini gör.
        </p>
        <div style={{ display: "flex", gap: 8 }}>
          <select value={selectedStrategy} onChange={(e) => setSelectedStrategy(e.target.value)}>
            <option value="">— seç —</option>
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <button onClick={() => selectedStrategy && explainStrategy(selectedStrategy)}
                  data-testid="bda-explain-button"
                  disabled={!selectedStrategy || loadingExplain}>
            {loadingExplain ? "..." : "Açıkla"}
          </button>
        </div>
        {explanation && (
          <div style={{ marginTop: 12, background: "var(--surface-2)",
                        padding: 12, fontSize: 12, lineHeight: 1.5,
                        whiteSpace: "pre-wrap" }}>
            {explanation}
          </div>
        )}
      </div>
    </div>
  );
}

export default BDAPane;
