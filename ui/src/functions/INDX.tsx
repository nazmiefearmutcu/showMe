/**
 * INDX — Indicator Index. Sub-system F user surface.
 *
 * Left: searchable grid of indicator cards (display_name + family + confidence meter).
 * Right: detail view of selected indicator (description, parameters table, formula,
 * rationale, suggested strategy).
 *
 * HONESTY: the per-indicator `confidence` (1-10) is a SUBJECTIVE editorial
 * assessment — NOT a backtested/validated metric. It is disclosed as such next to
 * every place it is shown. `suggested_strategy` is illustrative, not validated.
 */
import { useEffect, useMemo, useState } from "react";
import {
  type IndicatorEntry, type IndicatorParam,
  confidenceColor, useIndicatorStore,
} from "@/lib/indicator-store";
import { Empty, Pill, Skeleton } from "@/design-system";

const FAMILIES = ["all", "momentum", "trend", "volatility", "volume"] as const;

const CONFIDENCE_TITLE = "Güven = öznel editör değerlendirmesi (backtest değil)";

/**
 * Confidence rendered as a meter — NOT color-only. The numeric "c/10" text is
 * always visible; the tier color from {@link confidenceColor} is an ADDITION,
 * never the sole signal. Meter semantics let assistive tech read the value.
 */
function ConfidenceMeter({ c }: { c: number }) {
  const pct = Math.max(0, Math.min(100, (c / 10) * 100));
  return (
    <span
      role="meter"
      aria-label={`Güven: ${c}/10 (öznel)`}
      aria-valuenow={c}
      aria-valuemin={0}
      aria-valuemax={10}
      title={CONFIDENCE_TITLE}
      style={{
        position: "relative",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: 40,
        height: 18,
        padding: "0 6px",
        borderRadius: 4,
        overflow: "hidden",
        background: "var(--surface-2)",
        border: "1px solid var(--border-1)",
        fontSize: 11,
        fontWeight: 600,
        fontFamily: "var(--font-mono)",
        color: "var(--text-primary)",
      }}
    >
      <span
        aria-hidden
        style={{
          position: "absolute",
          inset: "0 auto 0 0",
          width: `${pct}%`,
          background: confidenceColor(c),
          opacity: 0.35,
        }}
      />
      <span style={{ position: "relative" }}>{c}/10</span>
    </span>
  );
}

function ParameterTable({ params }: { params: IndicatorParam[] }) {
  if (params.length === 0) return <div style={{ color: "var(--text-secondary)" }}>(parametre yok)</div>;
  return (
    <table style={{ width: "100%", fontSize: 12 }}>
      <caption className="u-sr-only">İndikatör parametreleri ve etkileri</caption>
      <thead>
        <tr style={{ color: "var(--text-secondary)", textAlign: "left" }}>
          <th scope="col">Param</th>
          <th scope="col">Type</th>
          <th scope="col">Default</th>
          <th scope="col">Min</th>
          <th scope="col">Max</th>
          <th scope="col">Effect</th>
        </tr>
      </thead>
      <tbody>
        {params.map((p) => (
          <tr key={p.name}>
            <td><strong className="u-mono">{p.name}</strong></td>
            <td className="u-mono">{p.type}</td>
            <td className="u-mono">{String(p.default ?? "-")}</td>
            <td className="u-mono">{p.min ?? "-"}</td>
            <td className="u-mono">{p.max ?? "-"}</td>
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
        <ConfidenceMeter c={entry.confidence} />
        <Pill tone="muted" withDot={false}>{entry.family}</Pill>
      </div>
      <p>{entry.short_description}</p>
      <pre style={{
        background: "var(--surface-2)", padding: 8, fontSize: 11,
        whiteSpace: "pre-wrap", borderRadius: 4,
      }}>{entry.long_description}</pre>
      <h4>Formula</h4>
      <code className="u-mono" style={{ background: "var(--surface-2)", padding: "4px 8px",
                     display: "block", fontSize: 11 }}>{entry.formula}</code>
      <h4>Parameters</h4>
      <ParameterTable params={entry.parameters} />
      <h4 title={CONFIDENCE_TITLE}>Değerlendirme gerekçesi (öznel) — {entry.confidence}/10</h4>
      <p style={{ fontSize: 11, color: "var(--text-secondary)", margin: "0 0 6px" }}>
        Güven skoru ve gerekçesi öznel editör değerlendirmesidir — backtest veya
        doğrulanmış bir performans ölçütü değildir.
      </p>
      <p style={{ color: "var(--text-secondary)" }}>{entry.confidence_rationale}</p>
      <h4>Örnek strateji (illüstratif — doğrulanmamış): {ss.name ?? "—"}</h4>
      <p style={{ fontSize: 11, color: "var(--text-secondary)", margin: "0 0 6px" }}>
        Bu strateji yalnızca bir örnektir — backtest edilmemiş, doğrulanmamıştır.
      </p>
      <p>{ss.summary}</p>
      {ss.rules && ss.rules.length > 0 && (
        <ul>
          {ss.rules.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {entry.references.length > 0 && (
        <>
          <h4>References</h4>
          <ul style={{ fontSize: 11, color: "var(--text-secondary)" }}>
            {entry.references.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </>
      )}
    </div>
  );
}

export function INDXPane() {
  const entries = useIndicatorStore((s) => s.entries);
  const loading = useIndicatorStore((s) => s.loading);
  const error = useIndicatorStore((s) => s.error);
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
  // Distinguish "filter hid everything" from "catalog is genuinely empty" so the
  // empty-state copy doesn't blame a filter the user never applied.
  const hasActiveFilter = query.trim() !== "" || family !== "all";

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr",
                  height: "100%", overflow: "hidden" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8,
                    borderRight: "1px solid var(--border-1)", overflow: "hidden" }}>
        <label htmlFor="indx-search" className="u-sr-only">Indikatör ara</label>
        <input id="indx-search" value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="Indikatör ara…" />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }} role="group" aria-label="Aile filtresi">
          {FAMILIES.map((f) => (
            <button key={f} onClick={() => setFamily(f)}
                    aria-pressed={family === f}
                    aria-label={`Aile: ${f}`}
                    style={{ fontSize: 11, opacity: family === f ? 1 : 0.55 }}>
              {f}
            </button>
          ))}
        </div>
        <div role="status" aria-live="polite"
             style={{ fontSize: 10, color: "var(--text-secondary)" }}>
          {visible.length} indikatör
        </div>
        <p
          title={CONFIDENCE_TITLE}
          style={{ fontSize: 10, color: "var(--text-secondary)", margin: 0 }}
        >
          Güven = öznel editör değerlendirmesi (backtest değil)
        </p>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {loading && entries.length === 0 && (
            <div data-testid="indx-loading" style={{ padding: 8, display: "flex",
                 flexDirection: "column", gap: 8 }}>
              <Skeleton height={36} />
              <Skeleton height={36} />
              <Skeleton height={36} />
            </div>
          )}
          {error && (
            <div data-testid="indx-error" role="alert"
                 style={{ padding: 12, color: "var(--accent-err)", fontSize: 12 }}>
              Katalog yüklenemedi: {error}
            </div>
          )}
          {!loading && !error && visible.map((e) => (
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
                <div style={{ fontSize: 10, color: "var(--text-secondary)" }}>{e.family}</div>
              </div>
              <ConfidenceMeter c={e.confidence} />
            </button>
          ))}
          {!loading && !error && visible.length === 0 && (
            <div data-testid="indx-empty" style={{ padding: 12 }}>
              {hasActiveFilter ? (
                <Empty title="Eşleşen indikatör yok."
                       body="Aramayı veya aile filtresini değiştir." />
              ) : (
                <Empty title="Katalogda indikatör yok."
                       body="Henüz indikatör yok." />
              )}
            </div>
          )}
        </div>
      </div>
      <div role="region" aria-label="Indikatör detayları" style={{ overflowY: "auto" }}>
        <span role="status" className="u-sr-only">
          {selected ? `Seçili indikatör: ${selected.display_name}` : ""}
        </span>
        {selected ? <IndicatorDetail entry={selected} /> : (
          <div style={{ padding: 24, color: "var(--text-secondary)" }}>
            Soldan bir indikatör seç.
          </div>
        )}
      </div>
    </div>
  );
}

export default INDXPane;
