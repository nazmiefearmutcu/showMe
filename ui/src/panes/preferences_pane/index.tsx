import { useEffect, useMemo, useState } from "react";
import {
  readDensity,
  readState,
  setCustom,
  setDensity,
  setPreset,
  type CustomColors,
  type Density,
  type Preset,
  type ThemeState,
} from "@/lib/theme";
import { locale, setLocale, t, type Locale } from "@/i18n";
import { toast } from "@/lib/toast";
import { useAppStore } from "@/lib/store";
import { fetchSidecarInfo } from "@/lib/sidecar";
import { PRESET_LABELS } from "@/lib/theme";
import { navigate, useRoute } from "@/lib/router";
import { PreferencesChrome } from "./PreferencesChrome";
import { LOCALE_LABELS, SECTIONS, type SectionId } from "./_types";
import { AppearanceSection } from "./appearance";
import { SecretsSection } from "./secrets";
import { MigrationSection } from "./migration";
import { StreamsSection } from "./streams";
import { DataSection } from "./data";
import { AboutSection } from "./about";
import { LlmSection } from "./llm";

export function Preferences({ section }: { section?: string }) {
  const route = useRoute();
  const routeSection =
    route.kind === "preferences" || route.kind === "settings"
      ? route.section
      : undefined;
  const resolvedSection = section ?? routeSection;
  const initial = useMemo<SectionId>(
    () =>
      resolvedSection && (SECTIONS as readonly string[]).includes(resolvedSection)
        ? (resolvedSection as SectionId)
        : "appearance",
    [resolvedSection],
  );
  const [active, setActive] = useState(initial);
  const [themeState, setLocalThemeState] = useState<ThemeState>(() => readState());
  const [density, setDensityState] = useState<Density>(readDensity());
  const [loc, setLocState] = useState<Locale>(locale());
  const [info, setInfo] = useState<Awaited<ReturnType<typeof fetchSidecarInfo>> | null>(null);
  const port = useAppStore((s) => s.sidecarPort);

  useEffect(() => {
    fetchSidecarInfo().then(setInfo).catch(() => setInfo(null));
  }, [port]);

  useEffect(() => {
    setActive(initial);
  }, [initial]);

  const updateActive = (next: SectionId) => {
    setActive(next);
    if (next !== resolvedSection) {
      navigate(`#/preferences/${next}`);
    }
  };

  const applyLocale = (next: Locale) => {
    setLocale(next);
    setLocState(next);
    toast.info(t("language.changed", { locale: LOCALE_LABELS[next] }));
  };
  const applyPreset = (next: Preset) => {
    setLocalThemeState(setPreset(next));
    // Per-preset display name via i18n keys (theme.midnight, theme.matrix…).
    // Falls back to PRESET_LABELS if the i18n key isn't shipped yet.
    const themeKey = `theme.${next}`;
    const themeName = t(themeKey);
    const display = themeName === themeKey ? PRESET_LABELS[next] : themeName;
    toast.info(t("theme.changed", { theme: display }));
  };
  const applyCustom = (slot: keyof CustomColors, hex: string) => {
    const updated = setCustom({ [slot]: hex });
    setLocalThemeState(updated);
  };
  const applySavedDensity = (next: Density) => {
    setLocalThemeState(setDensity(next));
    setDensityState(next);
  };

  // Native PreferencesChrome (extracted 2026-05-24 fakery removal) replaces
  // SettingsDesignExportRenderer chromeOnly. The native section below is the
  // single source of truth for theme/data/streams/etc controls.
  return (
    <main className="prefs-main prefs-main--native-settings prefs-main--design-preview" aria-label="Preferences">
      <PreferencesChrome
        section={active}
        onSection={(next) => updateActive(next)}
      />

      <div
        className="prefs-main__sections prefs-main__controls"
        data-testid="prefs-native-sections"
        data-section={active}
      >
        {active === "appearance" && (
          <AppearanceSection
            state={themeState}
            density={density}
            locale={loc}
            onPreset={applyPreset}
            onCustom={applyCustom}
            onDensity={applySavedDensity}
            onLocale={applyLocale}
          />
        )}

        {active === "data" && <DataSection />}

        {active === "streams" && <StreamsSection />}

        {active === "secrets" && <SecretsSection />}

        {active === "migration" && <MigrationSection />}

        {active === "llm" && <LlmSection />}

        {active === "about" && <AboutSection info={info} />}
      </div>
    </main>
  );
}

export default Preferences;
