import { useId, useRef, useState, type KeyboardEvent } from "react";

/**
 * Info button that lists the providers behind one calendar row.
 *
 * Each `sources[]` entry comes from the awareness payload (provider, basis,
 * fetched_at). The popover opens on click and closes on Escape, which returns
 * focus to the button.
 */
export interface ProvenanceSource {
  provider: string;
  url?: string | null;
  fetched_at?: string | null;
  basis?: string | null;
}

export interface ProvenanceButtonProps {
  sources: ProvenanceSource[] | null | undefined;
  /** Human subject for the accessible name, e.g. "Nonfarm Payrolls". */
  subject?: string;
}

function hhmmUtc(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--";
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function ProvenanceButton({ sources, subject = "row" }: ProvenanceButtonProps) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popId = useId();
  const list = sources ?? [];

  if (list.length === 0) {
    return (
      <span className="aw-prov aw-prov--none" aria-label="No source recorded">
        —
      </span>
    );
  }

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    }
  };

  return (
    <span className="aw-prov" onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        className="aw-prov__btn"
        aria-expanded={open}
        aria-controls={popId}
        aria-label={`Sources for ${subject}: ${list.length}`}
        title={`${list.length} source${list.length === 1 ? "" : "s"}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span aria-hidden="true">ⓘ</span>
      </button>
      {open ? (
        <div
          id={popId}
          className="aw-prov__pop"
          role="region"
          aria-label={`Sources for ${subject}`}
        >
          <ul className="aw-prov__list">
            {list.map((s, i) => (
              <li key={`${s.provider}-${i}`} className="aw-prov__item">
                <span className="aw-prov__name">{s.provider}</span>
                {s.basis ? <span className="aw-prov__basis">{s.basis}</span> : null}
                {s.fetched_at ? (
                  <span className="aw-prov__time">{hhmmUtc(s.fetched_at)} UTC</span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </span>
  );
}
