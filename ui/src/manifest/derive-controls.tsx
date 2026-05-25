/**
 * deriveControls — turn a FunctionManifest into ordered JSX controls.
 *
 * Discipline:
 *   - iterates `manifest.inputs` in declaration order
 *   - hides an input when any name in its `depends_on` is unset
 *     (undefined, null, empty string, or empty array)
 *   - honors required/min/max/step/unit via the placeholder controls
 *   - emits one keyed element per visible input
 *
 * The controls themselves are placeholders in `./controls`. Each receives
 * `{ spec, value, onChange }` and writes back via `onChange(next)` — the
 * caller must merge that into its own state.
 */
import type { JSX } from "react";

import {
  BenchmarkPicker,
  BooleanControl,
  DateRangePicker,
  HorizonControl,
  MultiselectControl,
  NumberControl,
  ProviderModeControl,
  ScenarioControl,
  SelectControl,
  SymbolPicker,
  TextControl,
} from "./controls";
import type { ControlProps } from "./controls/BenchmarkPicker";
import { type ControlKind, type FunctionManifest, type InputSpec } from "./types";

/**
 * Treat undefined/null/empty-string/empty-array as "unset". A boolean
 * `false` is intentionally NOT unset — checking a parent checkbox should
 * still satisfy a dependent's depends_on contract.
 */
export function isUnset(v: unknown): boolean {
  if (v === undefined || v === null) return true;
  if (typeof v === "string") return v.length === 0;
  if (Array.isArray(v)) return v.length === 0;
  return false;
}

/**
 * True when EVERY name in `spec.depends_on` resolves to a set value in
 * the given `value` record. Empty `depends_on` ⇒ always visible.
 */
export function isVisible(spec: InputSpec, value: Record<string, unknown>): boolean {
  if (spec.depends_on.length === 0) return true;
  for (const parent of spec.depends_on) {
    if (isUnset(value[parent])) return false;
  }
  return true;
}

/**
 * Pure picker — exposed so renderers + tests can ask "which component would
 * this spec mount?" without going through the whole derive function.
 */
export function controlComponentFor(kind: ControlKind): (p: ControlProps) => JSX.Element {
  switch (kind) {
    case "symbol_picker":
      return SymbolPicker;
    case "benchmark_picker":
      return BenchmarkPicker;
    case "date_range":
      return DateRangePicker;
    case "horizon":
      return HorizonControl;
    case "scenario":
      return ScenarioControl;
    case "provider_mode":
      return ProviderModeControl;
    case "number":
      return NumberControl;
    case "text":
      return TextControl;
    case "select":
      return SelectControl;
    case "multiselect":
      return MultiselectControl;
    case "boolean":
      return BooleanControl;
    // The remaining kinds don't have dedicated widgets yet. Fall back to
    // the text control so the input is at least visible and writable; a
    // later session can ship the real model_assumption / constraint_set UIs.
    case "model_assumption":
    case "constraint_set":
      return TextControl;
    default: {
      // Exhaustiveness guard. The cast to never short-circuits at compile
      // time if a new ControlKind is added without updating this switch.
      const _exhaustive: never = kind;
      void _exhaustive;
      return TextControl;
    }
  }
}

export function deriveControls(
  manifest: FunctionManifest,
  value: Record<string, unknown>,
  onChange: (next: Record<string, unknown>) => void,
): JSX.Element[] {
  const elements: JSX.Element[] = [];
  for (const spec of manifest.inputs) {
    if (!isVisible(spec, value)) continue;
    const Comp = controlComponentFor(spec.control);
    const handleChange = (next: unknown) => {
      // Functional merge — the caller's `value` snapshot might be stale by
      // the time we fire, so produce the next record from the current one.
      onChange({ ...value, [spec.name]: next });
    };
    elements.push(
      <Comp
        key={spec.name}
        spec={spec}
        value={value[spec.name]}
        onChange={handleChange}
      />,
    );
  }
  return elements;
}

export default deriveControls;
