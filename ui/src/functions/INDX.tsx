/**
 * INDX — Indicator Index. Sub-system F user surface.
 *
 * Left: searchable grid of indicator cards (display_name + family + confidence chip).
 * Right: detail view of selected indicator (description, parameters table, formula,
 * rationale, suggested strategy).
 */
import { useEffect, useMemo, useState } from "react";
import {
  type IndicatorEntry, type IndicatorParam,
  confidenceColor, useIndicatorStore,
} from "@/lib/indicator-store";

const FAMILIES = ["all", "momentum", "trend", "volatility", "volume"] as const;

function ConfidenceChip({ c }: { c: number }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: 32, height: 20, borderRadius: 4, color: "var(--fg-1)",
      background: confidenceColor(c), fontSize: 11, fontWeight: 600,
    }}>
      {c}/10
    </span>
  );
}

function ParameterTable({ params }: { params: IndicatorParam[] }) {
  if (params.length === 0) return <div style={{ color: "var(--fg-2)" }}>(parametre yok)</div>;
  return (
    <table style={{ width: "100%", fontSize: 12 }}>
      <thead>
        <tr style={{ color: "var(--fg-2)", textAlign: "left" }}>
          <th>Param</th><th>Type</th><th>Default</th><th>Min</th><th>Max</th><th>Effect</th>
        </tr>
      </thead>
      <tbody>
        {params.map((p) => (
          <tr key={p.name}>
            <td><strong>{p.name}</strong></td>
            <td>{p.type}</td>
            <td>{String(p.default ?? "-")}</td>
            <td>{p.min ?? "-"}</td>
            <td>{p.max ?? "-"}</td>
            <td>{p.effect}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function IndicatorDetail({ entry }: { entry: IndicatorEntry }) {
  const ss = entry.suggested_strategy;
  return (
    <div style={{ padding: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <h2 style={{ margin: 0 }}>{entry.display_name}</h2>
        <ConfidenceChip c={entry.confidence} />
        <span style={{ color: "var(--fg-2)" }}>{entry.family}</span>
      </div>
      <p>{entry.short_description}</p>
      <pre style={{
        background: "var(--surface-2)", padding: 8, fontSize: 11,
        whiteSpace: "pre-wrap", borderRadius: 4,
      }}>{entry.long_description}</pre>
      <h4>Formula</h4>
      <code style={{ background: "var(--surface-2)", padding: "4px 8px",
                     display: "block", fontSize: 11 }}>{entry.formula}</code>
      <h4>Parameters</h4>
      <ParameterTable params={entry.parameters} />
      <h4>Confidence rationale ({entry.confidence}/10)</h4>
      <p style={{ color: "var(--fg-2)" }}>{entry.confidence_rationale}</p>
      <h4>Suggested strategy: {ss.name ?? "—"}</h4>
      <p>{ss.summary}</p>
      {ss.rules && ss.rules.length > 0 && (
        <ul>
          {ss.rules.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {entry.references.length > 0 && (
        <>
          <h4>References</h4>
          <ul style={{ fontSize: 11, color: "var(--fg-2)" }}>
            {entry.references.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}

export function INDXPane() {
  const entries = useIndicatorStore((s) => s.entries);
  const selectedId = useIndicatorStore((s) => s.selectedId);
  const loadCatalog = useIndicatorStore((s) => s.loadCatalog);
  const setSelected = useIndicatorStore((s) => s.setSelected);
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState<typeof FAMILIES[number]>("all");

  useEffect(() => { if (entries.length === 0) loadCatalog(); }, [entries.length, loadCatalog]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter((e) => {
      if (family !== "all" && e.family !== family) return false;
      if (!q) return true;
      return e.id.toLowerCase().includes(q)
          || e.display_name.toLowerCase().includes(q)
          || e.short_description.toLowerCase().includes(q);
    });
  }, [entries, query, family]);

  const selected = selectedId ? entries.find((e) => e.id === selectedId) ?? null : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr",
                  height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8,
                    borderRight: "1px solid var(--border-1)", overflow: "hidden" }}>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="Indikatör ara…" aria-label="Indikatör ara" />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {FAMILIES.map((f) => (
            <button key={f} onClick={() => setFamily(f)}
                    aria-pressed={family === f}
                    style={{ fontSize: 11, opacity: family === f ? 1 : 0.55 }}>
              {f}
            </button>
          ))}
        </div>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {visible.map((e) => (
            <button key={e.id} onClick={() => setSelected(e.id)}
                    style={{
                      display: "grid", gridTemplateColumns: "1fr auto",
                      gap: 8, alignItems: "center", padding: "8px 10px",
                      width: "100%", textAlign: "left",
                      background: selectedId === e.id ? "var(--surface-2)" : "transparent",
                      border: "none", borderBottom: "1px solid var(--border-1)",
                      cursor: "pointer",
                    }}>
              <div>
                <div><strong>{e.display_name}</strong></div>
                <div style={{ fontSize: 10, color: "var(--fg-2)" }}>{e.family}</div>
              </div>
              <ConfidenceChip c={e.confidence} />
            </button>
          ))}
          {visible.length === 0 && (
            <div style={{ padding: 12, color: "var(--fg-2)" }}>Eşleşen indikatör yok.</div>
          )}
        </div>
      </div>
      <div style={{ overflowY: "auto" }}>
        {selected ? <IndicatorDetail entry={selected} /> : (
          <div style={{ padding: 24, color: "var(--fg-2)" }}>
            Soldan bir indikatör seç.
          </div>
        )}
      </div>
    </div>
  );
}

export default INDXPane;
