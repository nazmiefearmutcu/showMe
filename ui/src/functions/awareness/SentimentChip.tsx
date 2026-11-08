import { signedValue } from "./format";

export interface SentimentChipProps {
  score: number | null | undefined;
  confidence?: number | null;
  model?: string | null;
  /** Shown in the tooltip only, e.g. "lexicon (aw-fin-1)". */
  label?: string;
}

const THRESHOLD = 0.15;

/**
 * Signed sentiment pill. Direction carried by the glyph and the signed number,
 * never colour alone. Renders nothing when the score is missing (no default value).
 */
export function SentimentChip({ score, confidence, model, label }: SentimentChipProps) {
  if (score === null || score === undefined || Number.isNaN(score)) return null;
  const tone = score >= THRESHOLD ? "pos" : score <= -THRESHOLD ? "neg" : "neu";
  const glyph = tone === "pos" ? "\u25B2" : tone === "neg" ? "\u25BC" : "\u25CF";
  const modelText = model ?? "unknown model";
  const conf = confidence != null ? `, confidence ${confidence.toFixed(2)}` : "";
  const title = `${label ?? (score >= 0 ? "Positive" : "Negative")} ${signedValue(score)}, ${modelText}${conf}`;
  return (
    <span className={`aw-sent aw-sent--${tone}`} title={title} aria-label={title}>
      <span aria-hidden="true">{glyph}</span> {signedValue(score)}
    </span>
  );
}
