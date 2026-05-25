/**
 * SelectControl — placeholder. Renders any kind of options array as a
 * `<select>`. Values stringified for DOM transport; consumers convert back.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

interface NormalizedOption {
  /** Stringified value for DOM transport. */
  value: string;
  /** Display label (= value when option is a plain primitive). */
  label: string;
  /** Original payload, so onChange can echo the right type. */
  raw: unknown;
}

function normalize(options: unknown[] | null | undefined): NormalizedOption[] {
  if (!options) return [];
  return options.map((o): NormalizedOption => {
    if (o && typeof o === "object" && !Array.isArray(o)) {
      const rec = o as Record<string, unknown>;
      const v = rec.value;
      const l = rec.label;
      return {
        value: typeof v === "string" || typeof v === "number" ? String(v) : JSON.stringify(v),
        label: typeof l === "string" ? l : String(v),
        raw: v ?? o,
      };
    }
    const v = typeof o === "string" || typeof o === "number" || typeof o === "boolean" ? o : JSON.stringify(o);
    return { value: String(v), label: String(v), raw: o };
  });
}

export function SelectControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const opts = normalize(spec.options);
  const current =
    typeof value === "string" || typeof value === "number" || typeof value === "boolean"
      ? String(value)
      : "";
  return (
    <label
      className="manifest-control manifest-control--select"
      data-control="select"
      data-input-name={spec.name}
    >
      <span className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
      </span>
      <select
        name={spec.name}
        value={current}
        aria-label={spec.label}
        onChange={(e) => {
          const next = opts.find((o) => o.value === e.target.value);
          onChange(next ? next.raw : e.target.value);
        }}
      >
        {!spec.required && !current ? <option value="">—</option> : null}
        {opts.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default SelectControl;
