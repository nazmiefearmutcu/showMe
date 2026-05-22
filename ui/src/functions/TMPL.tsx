/**
 * TMPL — Template bot library browser. Sub-system G.
 *
 * Left: grid of template cards. Right: detail with NL explanation,
 * math, applicability, "Use" button → modal that creates a strategy.
 */
import { useEffect, useState } from "react";
import { useTemplateStore } from "@/lib/template-store";

export function TMPLPane() {
  const entries = useTemplateStore((s) => s.entries);
  const selectedId = useTemplateStore((s) => s.selectedId);
  const loadCatalog = useTemplateStore((s) => s.loadCatalog);
  const setSelected = useTemplateStore((s) => s.setSelected);
  const instantiate = useTemplateStore((s) => s.instantiate);
  const error = useTemplateStore((s) => s.error);

  const [useModal, setUseModal] = useState<string | null>(null);
  const [nameOverride, setNameOverride] = useState("");
  const [symbolOverride, setSymbolOverride] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdId, setCreatedId] = useState<string | null>(null);

  useEffect(() => { if (entries.length === 0) loadCatalog(); }, [entries.length, loadCatalog]);

  const selected = selectedId ? entries.find((e) => e.id === selectedId) ?? null : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", height: "100%",
                  overflow: "hidden" }}>
      <div style={{ borderRight: "1px solid var(--border-1)", padding: 8, overflowY: "auto" }}>
        <h4>Template kütüphanesi ({entries.length})</h4>
        {entries.map((e) => (
          <button key={e.id} onClick={() => setSelected(e.id)}
                  style={{
                    display: "block", width: "100%", textAlign: "left",
                    padding: "8px 10px", borderBottom: "1px solid var(--border-1)",
                    background: selectedId === e.id ? "var(--surface-2)" : "transparent",
                    border: "none", cursor: "pointer",
                  }}>
            <div><strong>{e.name}</strong></div>
            <div style={{ fontSize: 10, color: "var(--fg-2)" }}>
              {e.family} · {e.uses_indicators.join(", ")}
            </div>
          </button>
        ))}
      </div>

      <div style={{ overflowY: "auto", padding: 16 }}>
        {!selected && <div style={{ color: "var(--fg-2)" }}>Soldan bir template seç.</div>}
        {selected && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div>
              <h2 style={{ margin: 0 }}>{selected.name}</h2>
              <div style={{ color: "var(--fg-2)" }}>{selected.family} · {selected.uses_indicators.join(", ")}</div>
              <p>{selected.description}</p>
            </div>
            <div>
              <h4>Açıklama</h4>
              <p style={{ whiteSpace: "pre-wrap" }}>{selected.natural_language_explanation}</p>
            </div>
            <details>
              <summary>Math</summary>
              <pre style={{ background: "var(--surface-2)", padding: 8, fontSize: 11,
                            whiteSpace: "pre-wrap" }}>{selected.math}</pre>
            </details>
            <div>
              <h4>Uygulanabilirlik</h4>
              <p style={{ color: "var(--fg-2)" }}>{selected.applicability}</p>
            </div>
            <div>
              <h4>Önerilen ayarlar</h4>
              <p>Timeframe: <code>{selected.recommended_timeframe}</code></p>
              <p>Semboller: {selected.recommended_symbols.join(", ") || "(serbest)"}</p>
            </div>
            <button onClick={() => {
              setUseModal(selected.id);
              setNameOverride(selected.name);
              setSymbolOverride(selected.recommended_symbols[0] ?? "");
              setCreatedId(null);
            }}>Bu template'i kullan</button>
            {error && <div style={{ color: "var(--accent-err)" }}>{error}</div>}
          </div>
        )}

        {useModal && (
          <div role="dialog" aria-modal="true"
               style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        zIndex: 1000 }}>
            <div style={{ background: "var(--surface-1)", padding: 16, minWidth: 360,
                          border: "1px solid var(--border-1)" }}>
              <h3 style={{ marginTop: 0 }}>Strateji oluştur</h3>
              <label>
                Ad
                <input value={nameOverride} onChange={(e) => setNameOverride(e.target.value)} />
              </label>
              <br />
              <label>
                Sembol (opsiyonel)
                <input value={symbolOverride} onChange={(e) => setSymbolOverride(e.target.value)} />
              </label>
              {createdId && (
                <div style={{ color: "var(--accent-ok)", marginTop: 8 }}>
                  Oluşturuldu (id: {createdId.slice(0, 8)}). STRA paneline gidip düzenleyebilirsin.
                </div>
              )}
              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 8 }}>
                <button onClick={() => { setUseModal(null); setCreatedId(null); }}>
                  Kapat
                </button>
                <button disabled={creating || !nameOverride} onClick={async () => {
                  setCreating(true);
                  const r = await instantiate(useModal, nameOverride, symbolOverride || undefined);
                  setCreating(false);
                  if (r) setCreatedId(r.strategy.id);
                }}>
                  {creating ? "..." : "Oluştur"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default TMPLPane;
