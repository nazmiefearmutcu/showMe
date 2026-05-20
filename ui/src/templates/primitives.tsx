/**
 * Template primitives shared across the 120 design-template-backed panes.
 *
 * These are token-driven adaptations of the `sm-bs-*` classes from the
 * Claude Design export's Basic variant. Each accepts theme via tokens.css
 * (no `data-theme` prop needed). The shell-level chrome (sidebar/header)
 * comes from the existing ShowMe Workspace; templates render INSIDE a
 * PaneChrome, so these primitives only cover the per-fn body.
 */
import type { CSSProperties, ReactNode } from "react";

// ── Sparkline ───────────────────────────────────────────────────────────

function sparkPath(values: number[], w: number, h: number, pad = 2): string {
  if (!values?.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (w - pad * 2) / Math.max(1, values.length - 1);
  return values
    .map((v, i) => {
      const x = pad + i * step;
      const y = h - pad - ((v - min) / span) * (h - pad * 2);
      return (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
    })
    .join(" ");
}

export function TplSpark({
  values,
  tone = "neutral",
  w = 80,
  h = 24,
}: {
  values: number[];
  tone?: "pos" | "neg" | "neutral";
  w?: number;
  h?: number;
}) {
  const stroke =
    tone === "pos"
      ? "var(--positive)"
      : tone === "neg"
        ? "var(--negative)"
        : "var(--accent)";
  return (
    <svg
      className="tpl-spark"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      style={{ width: w, height: h, display: "block" }}
    >
      <path
        d={sparkPath(values, w, h, 2)}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// ── Card ────────────────────────────────────────────────────────────────

export function TplCard({
  children,
  style,
  className = "",
}: {
  children: ReactNode;
  style?: CSSProperties;
  className?: string;
}) {
  return (
    <div className={`tpl-card ${className}`} style={style}>
      {children}
    </div>
  );
}

export function TplCardHeader({
  title,
  sub,
  trailing,
}: {
  title: ReactNode;
  sub?: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="tpl-card__head">
      <h3>{title}</h3>
      {sub && <span className="tpl-card__meta">{sub}</span>}
      {trailing && <span className="tpl-card__trail">{trailing}</span>}
    </div>
  );
}

// ── KPI tile ────────────────────────────────────────────────────────────

export function TplKpiTile({
  label,
  value,
  tone,
  sub,
}: {
  label: string;
  value: ReactNode;
  tone?: "pos" | "neg" | "warn" | "neutral";
  sub?: ReactNode;
}) {
  return (
    <div className="tpl-kpi">
      <span className="tpl-kpi__l">{label}</span>
      <span
        className={`tpl-kpi__v${tone === "pos" ? " pos" : tone === "neg" ? " neg" : tone === "warn" ? " warn" : ""}`}
      >
        {value}
      </span>
      {sub && <span className="tpl-kpi__s">{sub}</span>}
    </div>
  );
}

// ── Chip row (topic / range / preset selectors) ─────────────────────────

export function TplChip({
  active,
  tone,
  count,
  children,
  onClick,
}: {
  active?: boolean;
  tone?: "pos" | "neg" | "warn" | "neutral";
  count?: number | string;
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      className={`tpl-chip${active ? " is-active" : ""}`}
      onClick={onClick}
    >
      {tone && tone !== "neutral" && (
        <span
          className="tpl-chip__dot"
          style={{
            background:
              tone === "pos"
                ? "var(--positive)"
                : tone === "neg"
                  ? "var(--negative)"
                  : "var(--warn)",
          }}
        />
      )}
      <span>{children}</span>
      {count != null && <span className="tpl-chip__n">{count}</span>}
    </button>
  );
}

export function TplChipRow({ children }: { children: ReactNode }) {
  return <div className="tpl-chip-row">{children}</div>;
}

// ── KV row (key-value grid used by API + DES-like + spec pages) ─────────

export function TplKvRow({
  label,
  value,
  mono = true,
}: {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="tpl-kv-row">
      <span className="tpl-kv-row__k">{label}</span>
      <span className={`tpl-kv-row__v${mono ? " is-mono" : ""}`}>{value}</span>
    </div>
  );
}

export function TplKvGrid({
  children,
  cols = 2,
}: {
  children: ReactNode;
  cols?: 1 | 2 | 3;
}) {
  return (
    <div
      className="tpl-kv-grid"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {children}
    </div>
  );
}

// ── Table primitive (used by tables / forms / orderbooks / holders) ─────

export function TplTable({
  cols,
  rows,
  toneFor,
}: {
  cols: string[];
  rows: Array<Record<string, ReactNode>>;
  /**
   * Optional callback: given a row, return a tone-class to apply (used to
   * tint P&L rows / status badges per row).
   */
  toneFor?: (row: Record<string, ReactNode>) => "pos" | "neg" | "warn" | "" | undefined;
}) {
  return (
    <div className="tpl-table">
      <div className="tpl-table__head">
        {cols.map((c) => (
          <span key={c}>{c}</span>
        ))}
      </div>
      <div className="tpl-table__body">
        {rows.map((row, i) => {
          const tone = toneFor?.(row) ?? "";
          return (
            <div className={`tpl-table__row${tone ? ` tone-${tone}` : ""}`} key={i}>
              {cols.map((c) => (
                <span key={c}>{row[c] ?? "—"}</span>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Heatmap cell (sector / world / FX cross-rate grids) ─────────────────

export function TplHeatCell({
  label,
  value,
  intensity,
  tone,
}: {
  label: ReactNode;
  value: ReactNode;
  /** 0..1 — picks one of 5 token steps */
  intensity: number;
  tone: "pos" | "neg" | "warn" | "neutral";
}) {
  const step = Math.max(1, Math.min(5, Math.ceil(intensity * 5)));
  const bg =
    tone === "pos"
      ? `var(--heat-pos-${step})`
      : tone === "neg"
        ? `var(--heat-neg-${step})`
        : tone === "warn"
          ? "var(--warn-soft)"
          : "var(--bg-elev-2)";
  return (
    <div className="tpl-heat-cell" style={{ background: bg }}>
      <span className="tpl-heat-cell__l">{label}</span>
      <span className="tpl-heat-cell__v">{value}</span>
    </div>
  );
}

// ── Feed item (news / events / alerts) ──────────────────────────────────

export function TplFeedItem({
  source,
  time,
  title,
  summary,
  tags,
  impact,
  tone,
}: {
  source: string;
  time: string;
  title: ReactNode;
  summary?: ReactNode;
  tags?: string[];
  impact?: number;
  tone?: "pos" | "neg" | "warn" | "neutral";
}) {
  return (
    <article className={`tpl-feed-item tone-${tone || "neutral"}`}>
      <div className="tpl-feed-item__time">
        <span className="h">{time}</span>
        <span className="src">{source}</span>
      </div>
      <div className="tpl-feed-item__body">
        <div className="tpl-feed-item__title">{title}</div>
        {summary && <div className="tpl-feed-item__sum">{summary}</div>}
        {tags && tags.length > 0 && (
          <div className="tpl-feed-item__tags">
            {tags.map((t) => (
              <span key={t} className="tpl-feed-item__tag">
                #{t}
              </span>
            ))}
          </div>
        )}
      </div>
      {impact != null && (
        <div className="tpl-feed-item__impact">
          <span className="l">Impact</span>
          <div className="bar">
            {[1, 2, 3, 4, 5].map((s) => (
              <span key={s} className={s <= impact ? "on" : ""} />
            ))}
          </div>
        </div>
      )}
    </article>
  );
}

// ── Sparkline value row (watchlist mini, movers) ────────────────────────

export function TplSparkRow({
  symbol,
  name,
  values,
  last,
  changePct,
  width = 56,
}: {
  symbol: string;
  name?: string;
  values: number[];
  last: ReactNode;
  changePct: number;
  width?: number;
}) {
  const tone: "pos" | "neg" = changePct >= 0 ? "pos" : "neg";
  return (
    <div className="tpl-spark-row">
      <span className="tpl-spark-row__sym">
        <span className="tpl-spark-row__logo">{symbol.slice(0, 2)}</span>
        <span className="nm">
          <strong>{symbol}</strong>
          {name && <small>{name}</small>}
        </span>
      </span>
      <span className="tpl-spark-row__chart">
        <TplSpark values={values} tone={tone} w={width} h={24} />
        <span className="price">{last}</span>
      </span>
      <span className={`tpl-spark-row__chg ${tone}`}>
        {changePct >= 0 ? "+" : ""}
        {changePct.toFixed(2)}%
      </span>
    </div>
  );
}

// ── Section header (caps label + meta) ──────────────────────────────────

export function TplSectionHead({
  label,
  meta,
  trailing,
}: {
  label: ReactNode;
  meta?: ReactNode;
  trailing?: ReactNode;
}) {
  return (
    <div className="tpl-section-head">
      <span className="tpl-section-head__l">{label}</span>
      {meta && <span className="tpl-section-head__m">{meta}</span>}
      {trailing && <span className="tpl-section-head__t">{trailing}</span>}
    </div>
  );
}
