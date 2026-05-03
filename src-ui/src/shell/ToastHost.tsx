import { useToastStore, type ToastTone } from "@/lib/toast";

const TONE_COLORS: Record<ToastTone, { fg: string; bg: string; border: string }> = {
  info:    { fg: "var(--text-primary)", bg: "var(--bg-elev-2)", border: "var(--border-strong)" },
  success: { fg: "var(--positive)",     bg: "var(--bg-elev-2)", border: "var(--positive)" },
  warn:    { fg: "var(--warn)",         bg: "var(--bg-elev-2)", border: "var(--warn)" },
  error:   { fg: "var(--negative)",     bg: "var(--bg-elev-2)", border: "var(--negative)" },
};

export function ToastHost() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 32,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        zIndex: 8500,
        pointerEvents: "none",
      }}
    >
      {toasts.map((t) => {
        const tone = TONE_COLORS[t.tone];
        return (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            style={{
              minWidth: 260,
              maxWidth: 360,
              background: tone.bg,
              border: `1px solid ${tone.border}`,
              borderLeft: `3px solid ${tone.fg}`,
              borderRadius: "var(--radius-md)",
              padding: "10px 12px",
              fontSize: 12,
              color: "var(--text-primary)",
              boxShadow: "var(--shadow-elev)",
              pointerEvents: "auto",
              animation: "fade-in var(--motion-base)",
            }}
            onClick={() => dismiss(t.id)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
              <strong style={{ color: tone.fg }}>{t.title}</strong>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  dismiss(t.id);
                }}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--text-mute)",
                  cursor: "default",
                  padding: 0,
                  font: "inherit",
                }}
              >
                ✕
              </button>
            </div>
            {t.body && (
              <div style={{ marginTop: 4, color: "var(--text-secondary)" }}>
                {t.body}
              </div>
            )}
          </div>
        );
      })}
      <style>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
