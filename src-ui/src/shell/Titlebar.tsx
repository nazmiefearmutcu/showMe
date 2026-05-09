import { useState } from "react";
import { useAppStore } from "@/lib/store";
import { invoke } from "@/lib/tauri";
import { navigate } from "@/lib/router";
import { applyTheme, readTheme, type Theme } from "@/lib/theme";
import { useWorkspace } from "@/lib/workspace";
import { Pill } from "@/design-system";
import { t } from "@/i18n";
import { PresetMenu } from "./PresetMenu";
import { toast } from "@/lib/toast";

export function Titlebar() {
  const status = useAppStore((s) => s.sidecarStatus);
  const port = useAppStore((s) => s.sidecarPort);
  const togglePalette = useAppStore((s) => s.togglePalette);
  const sidebarVisible = useAppStore((s) => s.sidebarVisible);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const splitFocused = useWorkspace((s) => s.splitFocused);
  const closeFocused = useWorkspace((s) => s.closeFocused);
  const [theme, setTheme] = useState<Theme>(readTheme());

  const flipTheme = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };

  const newWindow = async () => {
    const label = `w-${Date.now().toString(36)}`;
    try {
      await invoke("open_window", { label, title: "showMe", url: "/" });
    } catch (err) {
      toast.error("New window failed", String(err));
    }
  };

  const tone =
    status === "healthy"
      ? "positive"
      : status === "stub"
        ? "muted"
        : status === "booting"
          ? "warn"
          : "negative";

  return (
    <header className="titlebar">
      <button
        type="button"
        className="interactive"
        onClick={() => navigate("/")}
        style={{
          background: "transparent",
          border: "none",
          color: "var(--text-secondary)",
          fontFamily: "Inter, SF Pro Text, system-ui, sans-serif",
          fontSize: 13,
          letterSpacing: "0",
          marginRight: 12,
          cursor: "default",
          padding: "0 4px",
        }}
        title={t("app.name")}
      >
        <strong style={{ color: "var(--text-primary)" }}>{t("app.name")}</strong>
        <span style={{ marginLeft: 8, color: "var(--text-mute)" }}>{t("app.tagline")}</span>
      </button>

      <div className="interactive" style={{ display: "flex", gap: 4 }}>
        <button
          type="button"
          className="btn btn--ghost"
          title="Toggle functions panel (⌘B)"
          aria-pressed={sidebarVisible}
          onClick={() => toggleSidebar()}
          style={{
            color: sidebarVisible ? "var(--accent)" : "var(--text-secondary)",
          }}
        >
          Fn
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          title="Split right (⌘\\)"
          onClick={() => splitFocused("h")}
        >
          Split R
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          title="Split below (⌘⇧\\)"
          onClick={() => splitFocused("v")}
        >
          Split B
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          title="Close pane (⌘W)"
          onClick={() => closeFocused()}
        >
          Close
        </button>
      </div>

      <div className="interactive" style={{ flex: 1 }} />

      <button
        type="button"
        className="btn btn--ghost interactive"
        onClick={() => togglePalette()}
        title="Command palette"
        style={{ display: "flex", alignItems: "center", gap: 8 }}
      >
        <span className="kbd">⌘K</span>
      </button>

      <PresetMenu />

      <div
        className="interactive"
        style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: 12 }}
      >
        <Pill tone={tone}>{status}</Pill>
        {port && (
          <span style={{ fontSize: 10, color: "var(--text-mute)" }}>:{port}</span>
        )}
        <button
          type="button"
          className="btn btn--ghost"
          onClick={newWindow}
          title="New window (⌘N)"
        >
          New
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={flipTheme}
          title={t("shell.theme.toggle")}
        >
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => navigate("/preferences")}
          title={t("shell.preferences")}
        >
          Prefs
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => invoke("open_data_folder")}
          title="Reveal data folder"
        >
          Data
        </button>
      </div>
    </header>
  );
}
