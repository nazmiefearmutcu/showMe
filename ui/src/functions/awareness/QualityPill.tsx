import { useEffect, useId, useRef, useState } from "react";
import { Pill } from "@/design-system";
import type { NewsQuality } from "./news-types";
import { parseQualityReason } from "./format";

export type QualityLabelValue = NewsQuality | null | undefined;

/** Upper-case pill text for a quality label. A missing label is UNRATED, never STANDARD. */
export function qualityText(label: QualityLabelValue): string {
  switch (label) {
    case "premium":
      return "PREMIUM";
    case "standard":
      return "STANDARD";
    case "low":
      return "LOW";
    case "rejected":
      return "REJECTED";
    default:
      return "UNRATED";
  }
}

/** The quality label as a pill, without the reasons button (used where per-item reasons are absent). */
export function QualityTag({ label }: { label: QualityLabelValue }) {
  const tone = label === "premium" ? "positive" : label === "low" ? "warn" : "muted";
  const variant = label === "premium" ? "soft" : "ghost";
  return (
    <Pill tone={tone} variant={variant} withDot={false}>
      {qualityText(label)}
    </Pill>
  );
}

export interface QualityPillProps {
  label: QualityLabelValue;
  score: number;
  reasons: string[];
}

/** Quality label pill plus a "?" button that opens the reasons table. */
export function QualityPill({ label, score, reasons }: QualityPillProps) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const word = qualityText(label).toLowerCase();
  return (
    <span className="aw-quality">
      <QualityTag label={label} />
      <button
        ref={btnRef}
        type="button"
        className="aw-quality__why"
        aria-label={`Why ${word}: show quality reasons`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        ?
      </button>
      {open ? (
        <QualityWhyPopover
          label={label}
          score={score}
          reasons={reasons}
          onClose={() => {
            setOpen(false);
            btnRef.current?.focus();
          }}
        />
      ) : null}
    </span>
  );
}

export interface QualityWhyPopoverProps {
  label: QualityLabelValue;
  score: number;
  reasons: string[];
  onClose: () => void;
}

/** Reasons table. Focus moves into the popover on open; Esc closes and returns focus. */
export function QualityWhyPopover({
  label,
  score,
  reasons,
  onClose,
}: QualityWhyPopoverProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    dialogRef.current?.focus();
  }, []);
  const parsed = reasons.map(parseQualityReason);
  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-labelledby={titleId}
      tabIndex={-1}
      className="aw-why"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
    >
      <div id={titleId} className="aw-why__title">
        Quality {qualityText(label).toLowerCase()} · {score}/100
      </div>
      {parsed.length === 0 ? (
        <p className="aw-why__empty">No reasons supplied by Awareness.</p>
      ) : (
        <table className="aw-why__table">
          <tbody>
            {parsed.map((r) => (
              <tr key={r.raw}>
                <td>{r.label}</td>
                <td className="aw-why__pts">
                  {r.points === null
                    ? ""
                    : `${r.points > 0 ? "+" : r.points < 0 ? "\u2212" : ""}${Math.abs(r.points)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button type="button" className="aw-btn aw-btn--ghost" onClick={onClose}>
        Close
      </button>
    </div>
  );
}
