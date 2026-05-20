/**
 * PresetThumb — mini-preview tile for a workspace or theme preset.
 *
 * Renders a 3-pane abstract preview using inline CSS custom properties so
 * theme presets can be previewed live (without applying them globally).
 * Round-4A: switched from per-element inline styles to a CSS custom-property
 * bridge + utility classes. Each preset thumb now sets THREE CSS variables
 * (`--pt-bg`, `--pt-surface`, `--pt-accent`) on the root and all internal
 * cards reference those via `.preset-thumb__*` classes. This keeps the
 * runtime-data-driven coloring while emptying the inline-attribute surface.
 */

import { memo, type ReactNode, type CSSProperties } from "react";

function PresetThumbImpl({
  bg,
  surface,
  accent,
  active,
  label,
  caption,
  onClick,
  width = 168,
  height = 80,
}: {
  bg: string;
  surface: string;
  accent: string;
  active?: boolean;
  label?: ReactNode;
  caption?: ReactNode;
  onClick?: () => void;
  width?: number;
  height?: number;
}) {
  // UX-09 P2: pick foreground overlays based on surface luminance so the
  // papyrus thumb shows visible mock content instead of a blank cream tile.
  const isLight = isLightHex(surface);
  const overlayBase = isLight ? "0,0,0" : "255,255,255";
  const rootStyle: CSSProperties = {
    ["--pt-bg" as string]: bg,
    ["--pt-surface" as string]: surface,
    ["--pt-accent" as string]: accent,
    ["--pt-overlay-base" as string]: overlayBase,
    ["--pt-width" as string]: `${width}px`,
    ["--pt-height" as string]: `${height}px`,
    ["--pt-sidebar-height" as string]: `${height - 12}px`,
  };
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        `showme-preset-thumb preset-thumb${onClick ? " showme-preset-thumb--interactive preset-thumb--interactive" : ""}${active ? " preset-thumb--active" : ""}`
      }
      aria-pressed={active}
      style={rootStyle}
    >
      <div className="preset-thumb__canvas">
        {/* mock sidebar */}
        <div className="preset-thumb__sidebar">
          <div className="preset-thumb__sidebar-strip preset-thumb__sidebar-strip--accent" />
          <div className="preset-thumb__sidebar-strip preset-thumb__sidebar-strip--ov-18" />
          <div className="preset-thumb__sidebar-strip preset-thumb__sidebar-strip--ov-10" />
          <div className="preset-thumb__sidebar-strip preset-thumb__sidebar-strip--ov-10" />
        </div>
        {/* mock 2 KPI cards */}
        <div className="preset-thumb__kpis">
          <div className="preset-thumb__kpi">
            <div className="preset-thumb__kpi-line preset-thumb__kpi-line--ov-20" />
            <div className="preset-thumb__kpi-line preset-thumb__kpi-line--accent" />
          </div>
          <div className="preset-thumb__kpi">
            <div className="preset-thumb__kpi-line preset-thumb__kpi-line--ov-20" />
            <div className="preset-thumb__kpi-line preset-thumb__kpi-line--ov-50" />
          </div>
        </div>
        {/* mock table row */}
        <div className="preset-thumb__table">
          <div className="preset-thumb__table-row">
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-40" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-18 preset-thumb__table-cell--narrow" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--accent preset-thumb__table-cell--right" />
          </div>
          <div className="preset-thumb__table-row">
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-32" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-14 preset-thumb__table-cell--narrow" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-40 preset-thumb__table-cell--right" />
          </div>
          <div className="preset-thumb__table-row preset-thumb__table-row--last">
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-26" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-10 preset-thumb__table-cell--narrow" />
            <div className="preset-thumb__table-cell preset-thumb__table-cell--ov-30 preset-thumb__table-cell--right" />
          </div>
        </div>
        {active && <div className="preset-thumb__active-mark">✓</div>}
      </div>
      {(label || caption) && (
        <div className="preset-thumb__caption-stack">
          {label && (
            <div className={`preset-thumb__label${active ? " preset-thumb__label--active" : ""}`}>
              {label}
            </div>
          )}
          {caption && <div className="preset-thumb__caption">{caption}</div>}
        </div>
      )}
    </button>
  );
}

/**
 * Returns true when the surface hex (#rgb or #rrggbb) has a luminance >0.5.
 * Used by mock overlays so PresetThumb stays legible on the papyrus thumb.
 */
function isLightHex(hex: string): boolean {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) {
    h = h.split("").map((c) => c + c).join("");
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return false;
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  // Luminance approximation good enough for "is the bg cream-ish?".
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5;
}

export const PresetThumb = memo(PresetThumbImpl);
