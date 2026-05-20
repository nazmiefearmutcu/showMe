import { useToastStore, type ToastTone } from "@/lib/toast";
import { useReducedMotion } from "@/lib/a11y";
import { t as tr } from "@/i18n";

const TONE_COLORS: Record<ToastTone, { fg: string; bg: string; border: string }> = {
  info:    { fg: "var(--text-primary)", bg: "var(--bg-elev-2)", border: "var(--border-strong)" },
  success: { fg: "var(--positive)",     bg: "var(--bg-elev-2)", border: "var(--positive)" },
  warn:    { fg: "var(--warn)",         bg: "var(--bg-elev-2)", border: "var(--warn)" },
  error:   { fg: "var(--negative)",     bg: "var(--bg-elev-2)", border: "var(--negative)" },
};

export function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);
  const reducedMotion = useReducedMotion();

  return (
    <div className="toast-host">
      {toasts.map((t) => {
        const tone = TONE_COLORS[t.tone];
        return (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            className={`toast-host__card${reducedMotion ? " toast-host__card--reduced" : ""}`}
            style={{
              ["--toast-bg" as string]: tone.bg,
              ["--toast-border" as string]: tone.border,
              ["--toast-fg" as string]: tone.fg,
            }}
            onClick={() => dismiss(t.id)}
          >
            <div className="toast-host__head">
              <strong style={{ color: tone.fg }}>{t.title}</strong>
              <button
                type="button"
                aria-label={tr("shell.toast.dismiss")}
                title={tr("shell.toast.dismiss")}
                onClick={(e) => {
                  e.stopPropagation();
                  dismiss(t.id);
                }}
                className="toast-host__dismiss"
              >
                <span aria-hidden>✕</span>
              </button>
            </div>
            {t.body && (
              <div className="toast-host__body">{t.body}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
