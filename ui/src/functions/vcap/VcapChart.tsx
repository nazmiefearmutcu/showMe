import { useId, useMemo } from "react";
import type { Observation } from "./types";
import { CHART_COLORS, chartGeometry, exactValue, axisValue } from "./chart";

export function VCAPChart({ rows }: { rows: Observation[] }) {
  // Bound the SVG as well as the exact-value table. Exports retain every row.
  const shown = useMemo(() => (rows.length > 3000 ? rows.slice(-3000) : rows), [rows]);
  const geometry = useMemo(() => chartGeometry(shown), [shown]);
  const id = useId();
  const {
    width,
    height,
    left,
    right,
    top,
    bottom,
    plotHeight,
    marks,
    series,
    ticks,
    ceiling,
    divisor,
    axisLabel,
  } = geometry;
  return (
    <section
      className="vcap-chart"
      data-testid="vcap-chart"
      aria-label="Reported observations chart"
    >
      <div className="vcap-section-title">
        <h3>Reported observations</h3>
        <span>{axisLabel} · missing periods remain gaps</span>
      </div>
      {rows.length > 3000 && (
        <p>
          Chart shows the last 3,000 returned observations. The table and exports include
          all {rows.length.toLocaleString("en-US")} rows.
        </p>
      )}
      <div className="vcap-chart-scroll">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-labelledby={`${id}-title ${id}-desc`}
        >
          <title id={`${id}-title`}>
            Source-specific reported investment, financing or deal observations
          </title>
          <desc id={`${id}-desc`}>
            Chronological grouped bars in {axisLabel}. Missing observations use a cross at
            the baseline; zero uses a short baseline mark. Exact values and dates follow in
            the observation table.
          </desc>
          <text x={left} y={16} className="vcap-axis-label">
            {axisLabel}
          </text>
          {[0, 0.25, 0.5, 0.75, 1].map((fraction) => {
            const y = top + plotHeight * (1 - fraction);
            return (
              <g key={fraction}>
                <line
                  x1={left}
                  x2={width - right}
                  y1={y}
                  y2={y}
                  className="vcap-grid-line"
                />
                <text x={left - 10} y={y + 4} textAnchor="end" className="vcap-axis-label">
                  {axisValue((ceiling * fraction) / divisor)}
                </text>
              </g>
            );
          })}
          {marks.map((mark, i) => {
            const title = `${mark.row.period}; ${mark.row.source_name}; ${mark.row.geography}; ${mark.row.stage}; ${exactValue(mark.row)}; ${mark.row.status}${mark.row.is_partial ? "; partial period" : ""}${mark.row.coverage_cutoff ? `; coverage through ${mark.row.coverage_cutoff}` : ""}`;
            return (
              <g key={`${mark.row.snapshot_id ?? ""}-${i}`}>
                {mark.missing ? (
                  <path
                    d={`M${mark.x},${height - bottom - 3}l6,6m-6,0l6,-6`}
                    stroke={mark.color}
                    fill="none"
                  >
                    <title>{title}</title>
                  </path>
                ) : (
                  <rect
                    x={mark.x}
                    y={mark.height === 0 ? mark.y - 1 : mark.y}
                    width={mark.width}
                    height={Math.max(mark.height, 1)}
                    fill={mark.color}
                    opacity={
                      mark.row.is_partial || mark.row.status === "provisional" ? 0.55 : 0.95
                    }
                    data-period={mark.row.period}
                    data-value={mark.row.value ?? "missing"}
                  >
                    <title>{title}</title>
                  </rect>
                )}
              </g>
            );
          })}
          {ticks.map((tick) => (
            <text
              key={tick.label}
              x={tick.x}
              y={height - 25}
              textAnchor="middle"
              className="vcap-axis-label"
            >
              {tick.label}
            </text>
          ))}
          <text
            x={(left + width - right) / 2}
            y={height - 5}
            textAnchor="middle"
            className="vcap-axis-label"
          >
            Measurement period
          </text>
        </svg>
      </div>
      <ul className="vcap-legend" aria-label="Source and geography legend">
        {series.map((item, i) => (
          <li key={item.id}>
            <span
              aria-hidden="true"
              style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
            />
            {item.label}
          </li>
        ))}
      </ul>
      <p className="vcap-muted">
        Faded bars are provisional or partial. A cross indicates a missing value; an
        unreported period stays empty. Series are never added together.
      </p>
    </section>
  );
}
