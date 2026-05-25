/**
 * PreferencesChrome — native tab navigation for the Preferences pane.
 *
 * Extracted in 2026-05-24 to remove the production-path dependency on
 * `@/design-export/showme-design-export`. The previous implementation
 * used `SettingsDesignExportRenderer chromeOnly` purely for the tab
 * strip; this component renders the same affordance with native UI.
 */
import type { SectionId } from "./_types";
import { SECTIONS } from "./_types";

const SECTION_LABELS: Record<SectionId, string> = {
  appearance: "Appearance",
  data: "Data",
  streams: "Streams",
  secrets: "Secrets",
  migration: "Migration",
  llm: "LLM",
  about: "About",
};

export function PreferencesChrome({
  section,
  onSection,
}: {
  section: SectionId;
  onSection: (next: SectionId) => void;
}) {
  return (
    <nav
      role="tablist"
      aria-label="Preferences sections"
      data-testid="preferences-chrome"
      style={{
        display: "flex",
        gap: 4,
        padding: "10px 14px",
        borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,.06))",
        background: "var(--bg-elev-2, rgba(0,0,0,.4))",
        overflowX: "auto",
      }}
    >
      {SECTIONS.map((id) => (
        <button
          key={id}
          role="tab"
          aria-selected={section === id}
          data-section={id}
          onClick={() => onSection(id)}
          style={{
            border: "1px solid var(--border-subtle, rgba(255,255,255,.08))",
            background:
              section === id
                ? "var(--accent, #4a9eff)"
                : "var(--bg-elev-3, rgba(255,255,255,.04))",
            color: section === id ? "var(--bg, #000)" : "var(--text-primary, #ddd)",
            padding: "6px 12px",
            borderRadius: "var(--radius-sm, 4px)",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 12,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          {SECTION_LABELS[id]}
        </button>
      ))}
    </nav>
  );
}
