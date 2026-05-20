export const screenBarStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 10,
  flexWrap: "wrap" as const,
};

export const screenHintStyle = {
  fontSize: 11,
  color: "var(--text-mute)",
  fontFamily: "JetBrains Mono, monospace",
  textTransform: "uppercase" as const,
};

export const twoColumnAnalysisGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
  gap: 12,
};

export const analysisTitleRowStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(260px, 1fr) auto",
  gap: 16,
  alignItems: "end",
};

export const analysisTitleStyle = {
  fontSize: 18,
  fontWeight: 700,
  color: "var(--text-primary)",
};

export const analysisTextStyle = {
  margin: 0,
  fontSize: 12,
  color: "var(--text-secondary)",
  lineHeight: 1.45,
};

export const analysisScoreStyle = {
  display: "grid",
  justifyItems: "end",
  gap: 2,
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 24,
};

export const analysisScoreLabelStyle = {
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase" as const,
};

export const analysisFlowStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
  gap: 8,
};

export const analysisStepStyle = {
  display: "grid",
  gap: 5,
  minWidth: 0,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--text-display) 2.5%, transparent)",
  fontSize: 12,
  color: "var(--text-secondary)",
};

export const analysisStepIndexStyle = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 18,
  height: 18,
  borderRadius: "50%",
  background: "var(--bg-elev-3)",
  color: "var(--accent)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 10,
};

export const analysisListStyle = {
  display: "grid",
  gap: 6,
};

export const analysisListRowStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(120px, 0.3fr) 1fr",
  gap: 8,
  alignItems: "baseline",
  fontSize: 12,
  color: "var(--text-secondary)",
  minWidth: 0,
};

export const analysisWarningListStyle = {
  display: "grid",
  gap: 4,
  color: "var(--warn)",
  fontSize: 11,
  overflowWrap: "anywhere" as const,
};

export const analysisQueryStyle = {
  margin: 0,
  fontSize: 11,
  color: "var(--text-mute)",
  overflowWrap: "anywhere" as const,
};

export const analysisMutedStyle = {
  fontSize: 11,
  color: "var(--text-mute)",
};

export const veryfinderLoadShellStyle = {
  display: "grid",
  gap: 12,
  padding: 12,
  border: "1px solid color-mix(in srgb, var(--warn) 28%, transparent)",
  borderRadius: "var(--radius-md)",
  background: "linear-gradient(135deg, color-mix(in srgb, var(--warn) 9%, transparent), color-mix(in srgb, var(--accent) 5%, transparent))",
};

export const veryfinderLoadTopStyle = {
  display: "grid",
  gridTemplateColumns: "minmax(240px, 1fr) auto",
  gap: 14,
  alignItems: "center",
};

export const veryfinderLoadKickerStyle = {
  fontSize: 10,
  color: "var(--warn)",
  textTransform: "uppercase" as const,
  letterSpacing: "0.08em",
  fontFamily: "JetBrains Mono, monospace",
};

export const veryfinderLoadTitleStyle = {
  marginTop: 3,
  marginBottom: 5,
  fontSize: 18,
  color: "var(--text-primary)",
  fontWeight: 700,
};

export const veryfinderLoadMeterStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(3, 11px)",
  gap: 5,
  alignItems: "end",
  height: 42,
};

export const veryfinderLoadBarStyle = {
  display: "block",
  width: 11,
  borderRadius: 8,
  background: "linear-gradient(180deg, var(--accent), color-mix(in srgb, var(--warn) 88%, white))",
  boxShadow: "0 0 14px color-mix(in srgb, var(--accent) 35%, transparent)",
};

export const veryfinderStepGridStyle = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 8,
};

export const veryfinderStepCardStyle = {
  display: "grid",
  gap: 3,
  padding: "8px 9px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--bg) 60%, transparent)",
  color: "var(--text-secondary)",
  fontSize: 11,
};

export const veryfinderLoadMetaStyle = {
  display: "flex",
  flexWrap: "wrap" as const,
  gap: 10,
  fontSize: 11,
  color: "var(--text-mute)",
};

export const tweetSearchControlStyle = {
  display: "flex",
  alignItems: "end",
  gap: 8,
  flexWrap: "wrap" as const,
  marginBottom: 12,
  minWidth: 0,
};

export const tweetSearchLabelStyle = {
  display: "grid",
  gap: 4,
  minWidth: 116,
  color: "var(--text-mute)",
  fontSize: 10,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
};

export const tweetSearchInputStyle = {
  height: 28,
  width: 154,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 12,
  padding: "0 8px",
};

export const tweetSearchGoButtonStyle = {
  minHeight: 28,
  minWidth: 48,
  padding: "0 12px",
  fontWeight: 700,
};

export const tweetSearchIntentStyle = {
  minHeight: 28,
  display: "inline-flex",
  alignItems: "center",
  color: "var(--text-secondary)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

export const tweetDrawerStyle = {
  display: "grid",
  gap: 8,
  minWidth: 0,
};

export const tweetDrawerToggleStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  width: "100%",
  minHeight: 30,
  textAlign: "left" as const,
};

export const tweetListStyle = {
  display: "grid",
  gap: 8,
  maxHeight: 340,
  overflowY: "auto" as const,
  paddingRight: 4,
};

export const tweetRowStyle = {
  display: "grid",
  gap: 6,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--text-display) 2.5%, transparent)",
  minWidth: 0,
};

export const tweetRowMetaStyle = {
  display: "flex",
  gap: 8,
  alignItems: "center",
  flexWrap: "wrap" as const,
  fontSize: 10,
  color: "var(--text-mute)",
};

export const tweetTextStyle = {
  margin: 0,
  color: "var(--text-secondary)",
  fontSize: 12,
  lineHeight: 1.42,
  overflowWrap: "anywhere" as const,
};

export const tweetTagRowStyle = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap" as const,
  color: "var(--text-mute)",
  fontSize: 10,
  textTransform: "uppercase" as const,
};

export const distributionBlockStyle = {
  display: "grid",
  gap: 8,
  minWidth: 0,
  padding: "9px 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  background: "color-mix(in srgb, var(--text-display) 2.5%, transparent)",
};

export const distributionTitleStyle = {
  fontSize: 10,
  color: "var(--text-mute)",
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
};

export const distributionRowStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 8,
  fontSize: 11,
  color: "var(--text-secondary)",
  minWidth: 0,
};

export const distributionTrackStyle = {
  height: 5,
  overflow: "hidden",
  borderRadius: 999,
  background: "var(--border-strong)",
};

export const distributionFillStyle = {
  display: "block",
  height: "100%",
  borderRadius: 999,
  background: "var(--accent)",
};

export const labelStyle = {
  fontSize: 10,
  letterSpacing: "0.06em",
  textTransform: "uppercase" as const,
  color: "var(--text-mute)",
};

export const selectStyle = {
  height: 28,
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 12,
  padding: "0 8px",
  width: "100%",
};

export const miniSelectStyle = {
  height: 24,
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border-subtle)",
  background: "var(--bg-elev-2)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 11,
  padding: "0 6px",
};

export const veryfinderToggleStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: 5,
  height: 24,
  color: "var(--text-secondary)",
  fontSize: 11,
  fontFamily: "JetBrains Mono, monospace",
};

export const footerSourceStyle = {
  minWidth: 0,
  maxWidth: "48%",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap" as const,
};
