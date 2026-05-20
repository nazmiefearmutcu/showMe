import type React from "react";
import type { Preset } from "@/lib/theme";
import type { Locale } from "@/i18n";

export const SECTIONS = [
  "appearance",
  "data",
  "streams",
  "secrets",
  "migration",
  "llm",
  "about",
] as const;

export type SectionId = typeof SECTIONS[number];

export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  tr: "Türkçe",
  de: "Deutsch",
  fr: "Français",
  es: "Español",
  it: "Italiano",
  ja: "日本語",
  zh: "中文",
  ko: "한국어",
  ar: "العربية",
  pt: "Português",
  ru: "Русский",
};

export const APPEARANCE_PRESETS: Exclude<Preset, "custom">[] = [
  "midnight",
  "matrix",
  "iced",
  "amber",
  "papyrus",
  "neon",
];

export interface MigrationSummary {
  source: string;
  target: string;
  positions_imported: number;
  positions_skipped: number;
  trades_imported: number;
  trades_skipped: number;
  daily_pnl?: number | null;
  paper_balance?: number | null;
  bot_start_time?: string | null;
  mode: string;
  warnings: string[];
}

export interface LlmCost {
  today_usd: number;
  cap_usd: number;
  remaining_usd: number;
  exhausted: boolean;
  providers: Array<{ name: string; model: string }>;
  entries: Array<{
    ts: string;
    provider: string;
    model: string;
    input_tokens: number;
    output_tokens: number;
    usd: number;
    purpose: string;
  }>;
}

export interface InstallResult {
  ok: boolean;
  source: string;
  target: string;
  already_installed: boolean;
}

export const btnStyle = {
  background: "var(--bg-elev-3)",
  border: "1px solid var(--border-strong)",
  borderRadius: "var(--radius-sm)",
  color: "var(--text-primary)",
  font: "inherit",
  fontSize: 11,
  padding: "2px 8px",
  cursor: "default",
};

export const modeBtn: React.CSSProperties = {
  height: 24,
  padding: "0 10px",
  border: "1px solid var(--border-subtle)",
  borderRadius: "var(--radius-sm)",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 11,
  cursor: "default",
};
