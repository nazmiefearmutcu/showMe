/**
 * ScenarioControl — placeholder. Renders the supplied scenario options
 * as a `<select>`; falls back to free-text when none provided.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

function asStringOptions(options: unknown[] | null | undefined): string[] {
  if (!options) return [];
  return options.filter((o): o is string => typeof o === "string");
}

export function ScenarioControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const opts = asStringOptions(spec.options);
  const current = typeof value === "string" ? value : "";
  if (!opts.length) {
    return (
      <label
        className="manifest-control manifest-control--scenario"
        data-control="scenario"
        data-input-name={spec.name}
      >
        <span className="manifest-control__label">
          {spec.label}
          {spec.required ? <span aria-hidden="true"> *</span> : null}
        </span>
        <input
          type="text"
          name={spec.name}
          required={spec.required}
          value={current}
          onChange={(e) => onChange(e.target.value)}
          aria-label={spec.label}
        />
        {spec.description ? (
          <span className="manifest-control__hint">{spec.description}</span>
        ) : null}
      </label>
    );
  }
  return (
    <label
      className="manifest-control manifest-control--scenario"
      data-control="scenario"
      data-input-name={spec.name}
    >
      <span className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
      </span>
      <select
        name={spec.name}
        value={current}
        onChange={(e) => onChange(e.target.value)}
        aria-label={spec.label}
      >
        {!spec.required && !current ? <option value="">—</option> : null}
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

export default ScenarioControl;
