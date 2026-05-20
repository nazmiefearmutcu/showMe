import type { CSSProperties } from "react";
import {
  terminalChartHeight,
  terminalChartHostStyle,
  terminalSvgChartStyle,
} from "@/lib/chart-layout";

export const functionBody: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto minmax(0, 1fr)",
  minHeight: 0,
  padding: 0,
};

export const commandBar: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 10,
  alignItems: "stretch",
  padding: "12px 14px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--scrim-low)",
  minWidth: 0,
};

export const resultPane: CSSProperties = {
  padding: 14,
  overflow: "auto",
  minWidth: 0,
  minHeight: 0,
};

export const functionIdentity: CSSProperties = {
  display: "grid",
  gap: 6,
  alignContent: "center",
  minWidth: 0,
};

export const metaLabel: CSSProperties = {
  color: "var(--text-mute)",
  fontSize: 10,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
};

export const codeLine: CSSProperties = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 13,
  fontWeight: 700,
};

export const identityMeta: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
};

export const symbolTools: CSSProperties = {
  display: "grid",
  gridTemplateRows: "auto auto",
  gap: 6,
  minWidth: 0,
};

export const ticketControls: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))",
  gap: 8,
  alignItems: "end",
  minWidth: 0,
};

export const optionStrategyControl: CSSProperties = {
  gridColumn: "span 2",
  minWidth: 0,
  maxWidth: "100%",
};

export const controlInlinePanel: CSSProperties = {
  display: "grid",
  gap: 6,
  gridColumn: "1 / -1",
};

export const resultMetaLine: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: "6px 12px",
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  textTransform: "uppercase",
};

export const quickRow: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

export const scopeBlock: CSSProperties = {
  display: "grid",
  gap: 4,
  alignContent: "center",
  minWidth: 0,
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 12,
};

export const commandActions: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
  gap: 6,
  alignContent: "center",
};

export const advancedPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  padding: "10px 14px 12px",
  borderBottom: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  minWidth: 0,
};

export const advancedHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: 12,
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

export const metricBox: CSSProperties = {
  padding: "8px 10px",
  background: "var(--bg-elev-2)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
};

export const metricRibbon: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
  gap: 8,
};

export const metricRibbonItem: CSSProperties = {
  display: "grid",
  gap: 4,
  padding: "8px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--scrim-low)",
  minWidth: 0,
};

export const metricRibbonValue: CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 13,
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};

export const chartPanel: CSSProperties = {
  position: "relative",
  display: "grid",
  gap: 10,
  gridTemplateRows: "auto minmax(0, 1fr) auto",
  height: terminalChartHeight,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 12,
  background: "var(--bg-elev-2)",
  minWidth: 0,
  overflow: "hidden",
};

export const chartHeader: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: 16,
  alignItems: "start",
  minWidth: 0,
};

export const chartStats: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(84px, 1fr))",
  gap: 6,
  flex: "1 1 320px",
  minWidth: 0,
  width: "min(460px, 100%)",
};

export const chartSvg: CSSProperties = {
  ...terminalSvgChartStyle,
};

export const lightweightChartHost: CSSProperties = {
  ...terminalChartHostStyle,
};

export const heatmapGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(118px, 1fr))",
  gap: 8,
  alignContent: "start",
  minHeight: 0,
  overflow: "auto",
};

export const heatmapCell: CSSProperties = {
  minHeight: 62,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "8px 10px",
  display: "grid",
  alignContent: "space-between",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  overflow: "hidden",
};

export const chartAxis: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

export const warningBox: CSSProperties = {
  padding: 10,
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  color: "var(--warn)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  display: "grid",
  gap: 4,
};

export const statusBox: CSSProperties = {
  padding: 12,
  border: "1px solid color-mix(in srgb, var(--warn) 40%, transparent)",
  background: "var(--warn-soft)",
  borderRadius: "var(--radius-sm)",
  display: "grid",
  gap: 10,
};

export const compactStatusBox: CSSProperties = {
  ...statusBox,
  padding: 10,
};

export const textareaStyle: CSSProperties = {
  minHeight: 68,
  resize: "vertical",
  background: "var(--bg-elev-3)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  lineHeight: 1.4,
  padding: "7px 8px",
  outline: "none",
};

export const kvPanel: CSSProperties = {
  display: "grid",
  gap: 1,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
};

export const kvRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "180px 1fr",
  gap: 12,
  padding: "6px 10px",
  background: "var(--scrim-low)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

export const newsList: CSSProperties = {
  display: "grid",
  gap: 8,
};

export const methodologyPanel: CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid color-mix(in srgb, var(--accent) 24%, transparent)",
  borderRadius: "var(--radius-md)",
  padding: "10px 12px",
  background: "var(--accent-soft)",
};

export const methodologyText: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

export const fieldDictionaryGrid: CSSProperties = {
  display: "grid",
  gap: 1,
  marginTop: 6,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  overflow: "hidden",
};

export const fieldDictionaryRow: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "180px 1fr",
  gap: 12,
  padding: "6px 8px",
  background: "var(--bg-elev-2)",
  color: "var(--text-secondary)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
};

export const briefPanel: CSSProperties = {
  display: "grid",
  gap: 8,
  border: "1px solid color-mix(in srgb, var(--accent) 30%, transparent)",
  borderRadius: "var(--radius-md)",
  padding: "12px 14px",
  background: "var(--accent-soft)",
};

export const briefTitle: CSSProperties = {
  margin: 0,
  color: "var(--text-primary)",
  fontSize: 18,
  lineHeight: 1.2,
};

export const briefSubhead: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--accent)",
  fontSize: 12,
  fontFamily: "JetBrains Mono, monospace",
  textTransform: "uppercase",
  letterSpacing: 0,
};

export const briefText: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

export const briefBullet: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "10px 1fr",
  gap: 8,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

export const briefBulletMark: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
};

export const newsItem: CSSProperties = {
  display: "grid",
  gap: 6,
  padding: "10px 12px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "var(--scrim-low)",
};

export const newsTitle: CSSProperties = {
  color: "var(--text-primary)",
  fontWeight: 700,
  textDecoration: "none",
};

export const sourceBadge: CSSProperties = {
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  whiteSpace: "nowrap",
};

export const reasonBadge: CSSProperties = {
  color: "var(--text-secondary)",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: "2px 6px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
  background: "var(--scrim-low)",
};

export const newsSummary: CSSProperties = {
  margin: 0,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

export const mediaGrid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
  gap: 10,
};

export const mediaFigure: CSSProperties = {
  margin: 0,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  overflow: "hidden",
  background: "var(--bg-elev-2)",
};

export const mediaImage: CSSProperties = {
  display: "block",
  width: "100%",
  aspectRatio: "16 / 9",
  objectFit: "cover",
  background: "var(--bg-elev-3)",
};

export const mediaCaption: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 10,
  padding: "8px 10px",
  color: "var(--text-primary)",
  fontSize: 11,
};

export const sourceStrip: CSSProperties = {
  display: "grid",
  gap: 10,
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  padding: 10,
  background: "var(--bg-elev-2)",
};

export const detailsBox: CSSProperties = {
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-md)",
  padding: 10,
  background: "var(--bg-elev-2)",
};

export const preStyle: CSSProperties = {
  margin: "10px 0 0",
  maxHeight: 260,
  overflow: "auto",
  color: "var(--text-secondary)",
  fontSize: 11,
  lineHeight: 1.45,
};
