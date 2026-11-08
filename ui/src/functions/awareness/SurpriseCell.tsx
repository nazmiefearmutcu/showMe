/**
 * Surprise (actual minus forecast, in the event's own unit) for an economic print.
 *
 * Direction is shown with a glyph and a signed number, never colour alone:
 * ▲ above consensus, ▼ below, = inline. Unreleased prints render nothing.
 * Signs use the real minus sign (U+2212).
 */
export type SurpriseDirection = "above" | "below" | "inline";

export interface SurpriseCellProps {
  surprise: number | null | undefined;
  unit?: string | null;
  direction?: SurpriseDirection | string | null;
  released: boolean;
}

export function formatSignedValue(value: number): string {
  const body = Math.abs(value).toFixed(2);
  if (value < 0) return `−${body}`;
  return `+${body}`;
}

export function SurpriseCell({ surprise, unit, direction, released }: SurpriseCellProps) {
  if (!released || surprise == null || !Number.isFinite(surprise)) {
    return <span className="aw-surprise aw-surprise--empty" />;
  }
  const unitText = unit ?? "";
  const isInline = Math.abs(surprise) < 1e-9 || direction === "inline";
  if (isInline) {
    return (
      <span
        className="aw-surprise aw-surprise--inline"
        aria-label="Inline with consensus"
        title="Inline with consensus"
      >
        {`= ${Math.abs(surprise).toFixed(2)}${unitText}`}
      </span>
    );
  }
  const dir: SurpriseDirection =
    direction === "above" || direction === "below"
      ? direction
      : surprise > 0
        ? "above"
        : "below";
  const glyph = dir === "above" ? "▲" : "▼";
  const word = dir === "above" ? "Above" : "Below";
  const valueText = `${formatSignedValue(surprise)}${unitText}`;
  return (
    <span
      className={`aw-surprise aw-surprise--${dir}`}
      aria-label={`${word} consensus by ${valueText}`}
      title={`${word} consensus by ${valueText}`}
    >
      <span aria-hidden="true">{glyph} </span>
      {valueText}
    </span>
  );
}
