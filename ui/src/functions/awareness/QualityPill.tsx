import { useEffect, useId, useRef, useState } from "react";
import { Pill } from "@/design-system";
import type { NewsQuality } from "./news-types";
import { parseQualityReason } from "./format";

export interface QualityPillProps {
  label: NewsQuality;
  score: number;
  reasons: string[];
}

/** Quality label pill plus a "?" button that opens the reasons table. */
export function QualityPill({ label, score, reasons }: QualityPillProps) {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);
  const shown =
    label === "premium"
      ? "PREMIUM"
      : label === "low"
        ? "LOW"
        : label === "rejected"
          ? "REJECTED"
          : "STANDARD";
  const tone = label === "premium" ? "positive" : label === "low" ? "warn" : "muted";
  const variant = label === "premium" ? "soft" : "ghost";
  return (
    <span className="aw-quality">
      <Pill tone={tone} variant={variant} withDot={false}>
        {shown}
      </Pill>
      <button
        ref={btnRef}
        type="button"
        className="aw-quality__why"
        aria-label={`Why ${label}: show quality reasons`}
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
  label: NewsQuality;
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
        Quality {label} · {score}/100
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
