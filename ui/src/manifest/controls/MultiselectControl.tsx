/**
 * MultiselectControl — placeholder. Native `<select multiple>`; value is
 * `string[]` (raw values stringified for transport, consumers re-parse).
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

function asStringOptions(options: unknown[] | null | undefined): string[] {
  if (!options) return [];
  return options
    .filter((o): o is string | number | boolean =>
      typeof o === "string" || typeof o === "number" || typeof o === "boolean",
    )
    .map((o) => String(o));
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((v): v is string | number | boolean =>
      typeof v === "string" || typeof v === "number" || typeof v === "boolean",
    )
    .map((v) => String(v));
}

export function MultiselectControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const opts = asStringOptions(spec.options);
  const current = asStringArray(value);
  return (
    <label
      className="manifest-control manifest-control--multiselect"
      data-control="multiselect"
      data-input-name={spec.name}
    >
      <span className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
      </span>
      <select
        name={spec.name}
        multiple
        value={current}
        aria-label={spec.label}
        onChange={(e) => {
          const next: string[] = [];
          for (const opt of e.target.selectedOptions) next.push(opt.value);
          onChange(next);
        }}
      >
        {opts.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default MultiselectControl;
