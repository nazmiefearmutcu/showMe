import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Pill,
  PresetThumb,
} from "@/design-system";
import {
  PRESET_LABELS,
  presetColors,
  type CustomColors,
  type Density,
  type Preset,
  type ThemeState,
} from "@/lib/theme";
import { listLocales, t, type Locale } from "@/i18n";
import { computeContrast, isLightHex } from "@/lib/a11y";
import {
  POPULAR_TIMEZONES,
  formatTime as formatTzTime,
  getSystemTimezone,
  listAllTimezones,
  readManualTimezone,
  setTimezoneMode,
  timezoneOffsetLabel,
  useTimezone,
  useTimezoneMode,
  writeTimezone,
} from "@/lib/timezone";
import { toast } from "@/lib/toast";
import { APPEARANCE_PRESETS, LOCALE_LABELS } from "./_types";

export function AppearanceSection({
  state,
  density,
  locale: loc,
  onPreset,
  onCustom,
  onDensity,
  onLocale,
}: {
  state: ThemeState;
  density: Density;
  locale: Locale;
  onPreset: (p: Preset) => void;
  onCustom: (slot: keyof CustomColors, hex: string) => void;
  onDensity: (d: Density) => void;
  onLocale: (l: Locale) => void;
}) {
  const colors = state.preset === "custom" ? state.custom : presetColors(state.preset);

  return (
    <div className="u-flex u-flex-col u-gap-12">
      <Card>
        <CardHeader
          trailing={
            <Pill tone="accent" variant="soft" withDot={false}>
              {PRESET_LABELS[state.preset]}
            </Pill>
          }
        >
          Theme presets
        </CardHeader>
        <CardBody>
          <div className="prefs-preset-grid">
            {APPEARANCE_PRESETS.map((p) => {
              const c = presetColors(p);
              return (
                <PresetThumb
                  key={p}
                  bg={c.bg}
                  surface={c.surface}
                  accent={c.accent}
                  active={state.preset === p}
                  label={PRESET_LABELS[p]}
                  caption={`${c.bg.toUpperCase()} · ${c.accent.toUpperCase()}`}
                  onClick={() => onPreset(p)}
                />
              );
            })}
            <PresetThumb
              bg={state.preset === "custom" ? state.custom.bg : "var(--bg)"}
              surface={state.preset === "custom" ? state.custom.surface : "var(--surface)"}
              accent={state.preset === "custom" ? state.custom.accent : "var(--accent)"}
              active={state.preset === "custom"}
              label="Custom"
              caption="Pick your own 3 colors below"
              onClick={() => onPreset("custom")}
            />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <button
              type="button"
              onClick={() => onPreset("midnight")}
              className="btn btn--ghost prefs-reset-btn"
            >
              Reset to Midnight
            </button>
          }
        >
          Custom colors
        </CardHeader>
        <CardBody>
          <p className="prefs-lede">
            Three slots. Background is the deepest layer; Surface drives panels and
            cards; Accent is interactive (CTAs, focus, links). Positive / negative
            P&L colors stay fixed across themes so trade direction always reads.
          </p>
          <div className="prefs-color-grid">
            <ColorSlot
              label="Background"
              hex={colors.bg}
              onChange={(v) => onCustom("bg", v)}
            />
            <ColorSlot
              label="Surface"
              hex={colors.surface}
              onChange={(v) => onCustom("surface", v)}
            />
            <ColorSlot
              label="Accent"
              hex={colors.accent}
              onChange={(v) => onCustom("accent", v)}
            />
          </div>
          <ColorPreviewStrip
            bg={colors.bg}
            surface={colors.surface}
            accent={colors.accent}
          />
          <ContrastWarning bg={colors.bg} surface={colors.surface} accent={colors.accent} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <Pill tone="accent" variant="soft" withDot={false}>
              <TimezoneClock />
            </Pill>
          }
        >
          {t("preferences.appearance.timezone")}
        </CardHeader>
        <CardBody>
          <TimezonePicker />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Density</CardHeader>
        <CardBody>
          <div className="u-flex u-gap-6">
            {(["compact", "comfortable"] as Density[]).map((d) => (
              <button
                type="button"
                key={d}
                onClick={() => onDensity(d)}
                className={`prefs-density-btn${d === density ? " prefs-density-btn--active" : ""}`}
              >
                <span>{d}</span>
                <span
                  aria-hidden
                  className={`prefs-density-stripe prefs-density-stripe--${d}`}
                />
              </button>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>Language</CardHeader>
        <CardBody>
          <div className="prefs-locale-grid">
            {listLocales().map((l) => (
              <button
                type="button"
                key={l}
                onClick={() => onLocale(l)}
                className={`prefs-locale-btn${l === loc ? " prefs-locale-btn--active" : ""}`}
              >
                {LOCALE_LABELS[l]}
              </button>
            ))}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function ColorSlot({
  label,
  hex,
  onChange,
}: {
  label: string;
  hex: string;
  onChange: (v: string) => void;
}) {
  const [draft, setDraft] = useState(hex);
  useEffect(() => setDraft(hex), [hex]);
  const commit = (v: string) => {
    if (/^#([0-9a-f]{3}){1,2}$/i.test(v)) onChange(v);
  };
  return (
    <div className="prefs-color-slot">
      <span className="prefs-color-slot__label">{label}</span>
      <div className="prefs-color-slot__inner">
        <label
          className="prefs-color-slot__swatch"
          style={{ background: hex }}
        >
          <input
            type="color"
            value={hex}
            onChange={(e) => {
              setDraft(e.target.value);
              commit(e.target.value);
            }}
            className="prefs-color-slot__input"
          />
        </label>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(draft)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(draft);
          }}
          spellCheck={false}
          className="prefs-color-slot__hex"
        />
        <button
          type="button"
          onClick={() => navigator.clipboard?.writeText(hex)}
          title="Copy hex"
          className="prefs-color-slot__copy"
        >
          ⎘
        </button>
      </div>
    </div>
  );
}

function ColorPreviewStrip({
  bg,
  surface,
  accent,
}: {
  bg: string;
  surface: string;
  accent: string;
}) {
  // Flip overlay text base depending on surface luminance so the mock-row
  // text and mute KPI labels survive Papyrus / custom-light pickers.
  const textBase = isLightHex(surface) ? "26, 22, 18" : "255, 255, 255";
  const rootStyle: React.CSSProperties = {
    ["--mock-bg" as string]: bg,
    ["--mock-surface" as string]: surface,
    ["--mock-accent" as string]: accent,
    ["--mock-text-base" as string]: textBase,
  };
  return (
    <div className="prefs-mock" style={rootStyle}>
      <div className="prefs-mock__row">
        <MockKpi label="MARKET VALUE" value="$590,397" tone="neutral" />
        <MockKpi label="P&L" value="-$704" tone="negative" />
        <MockKpi label="POSITIONS" value="51" tone="positive" />
      </div>
      <div className="prefs-mock__table">
        <span className="prefs-mock__cell">DOGEUSDT</span>
        <span className="prefs-mock__cell prefs-mock__cell--mute">$86,617</span>
        <span className="prefs-mock__cell prefs-mock__cell--negative">-$211</span>
        <span className="prefs-mock__cell prefs-mock__cell--accent">14.7%</span>
      </div>
    </div>
  );
}

function MockKpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral";
}) {
  return (
    <div className="prefs-mock-kpi">
      <span className="prefs-mock-kpi__label">{label}</span>
      <span className={`prefs-mock-kpi__value prefs-mock-kpi__value--${tone}`}>{value}</span>
      <span className="prefs-mock-kpi__rail" />
    </div>
  );
}

/**
 * UI-INT-03 P1: surface a live WCAG contrast warning when the user's custom
 * palette either collapses two surfaces to the same color or drops below
 * AA-large (3:1) for accent-on-bg / surface text. Inline so users see the
 * problem before they switch presets and lose the diagnostic.
 */
function ContrastWarning({
  bg,
  surface,
  accent,
}: {
  bg: string;
  surface: string;
  accent: string;
}) {
  const issues: string[] = [];
  const bgVsSurface = computeContrast(bg, surface);
  if (bgVsSurface != null && bgVsSurface < 1.05) {
    issues.push(t("preferences.appearance.surface_equals_bg"));
  }
  // Pick the foreground that the active surface would actually display:
  // dark text on light bg (papyrus), light text on dark bg (midnight et al).
  const expectedText = isLightHex(bg) ? "#1a1612" : "#eceef2";
  const textBg = computeContrast(expectedText, bg);
  if (textBg != null && textBg < 4.5) {
    issues.push(`Text on background: ${textBg.toFixed(1)}:1 (AA fail).`);
  }
  const accentOnSurface = computeContrast(accent, surface);
  if (accentOnSurface != null && accentOnSurface < 3) {
    issues.push(`Accent on surface: ${accentOnSurface.toFixed(1)}:1 (focus ring may vanish).`);
  }
  if (!issues.length) return null;
  return (
    <div role="alert" className="prefs-contrast-warn">
      <strong className="prefs-contrast-warn__title">
        {t("preferences.appearance.contrast_warning")}
      </strong>
      <ul className="prefs-contrast-warn__list">
        {issues.map((msg) => (
          <li key={msg}>{msg}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Live wall-clock chip rendered next to the Timezone card header so users
 * can compare picks against "what is it actually now in that city" without
 * leaving the preferences pane.
 */
function TimezoneClock() {
  const tz = useTimezone();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <>
      {formatTzTime(now, { tz, seconds: true })} · {timezoneOffsetLabel(tz, now)}
    </>
  );
}

function TimezonePicker() {
  const tz = useTimezone();
  const mode = useTimezoneMode();
  const all = useMemo(() => listAllTimezones(), []);
  const systemTz = useMemo(() => getSystemTimezone(), []);
  const manualSelection = useMemo(() => readManualTimezone(), [mode, tz]);
  const onPick = (next: string) => {
    const applied = writeTimezone(next);
    toast.info(`Timezone → ${applied}`);
  };
  const onModeChange = (next: "auto" | "manual") => {
    setTimezoneMode(next);
    toast.info(
      next === "auto"
        ? `${t("preferences.appearance.timezone.auto")} → ${getSystemTimezone()}`
        : `${t("preferences.appearance.timezone.manual")} → ${readManualTimezone()}`,
    );
  };
  return (
    <div className="prefs-tz">
      <p className="prefs-lede">{t("preferences.appearance.timezone.hint")}</p>
      <div className="prefs-tz__row">
        <span className="prefs-tz__row-label">
          {t("preferences.appearance.timezone.mode")}
        </span>
        <div className="prefs-tz__chips">
          <button
            type="button"
            onClick={() => onModeChange("auto")}
            className={`prefs-tz__chip${mode === "auto" ? " prefs-tz__chip--active" : ""}`}
            title={systemTz}
          >
            {t("preferences.appearance.timezone.auto")} · {systemTz}
          </button>
          <button
            type="button"
            onClick={() => onModeChange("manual")}
            className={`prefs-tz__chip${mode === "manual" ? " prefs-tz__chip--active" : ""}`}
          >
            {t("preferences.appearance.timezone.manual")}
          </button>
        </div>
      </div>
      {mode === "manual" && (
        <>
          <div className="prefs-tz__row">
            <span className="prefs-tz__row-label">
              {t("preferences.appearance.timezone.popular")}
            </span>
            <div className="prefs-tz__chips">
              {POPULAR_TIMEZONES.slice(0, 6).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onPick(opt.id)}
                  className={`prefs-tz__chip${
                    opt.id === manualSelection ? " prefs-tz__chip--active" : ""
                  }`}
                  title={opt.id}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <div className="prefs-tz__row">
            <label className="prefs-tz__row-label" htmlFor="prefs-tz-select">
              {t("preferences.appearance.timezone.other")}
            </label>
            <select
              id="prefs-tz-select"
              className="prefs-tz__select"
              value={manualSelection}
              onChange={(e) => onPick(e.target.value)}
            >
              {all.map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
    </div>
  );
}
