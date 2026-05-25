/**
 * ProviderModeControl — placeholder. Renders the DataMode choices supplied
 * by the manifest as a `<select>`. Empty options collapses to a disabled
 * read-only display since provider-mode without options is a contract bug.
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

export function ProviderModeControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const opts = asStringOptions(spec.options);
  const current = typeof value === "string" ? value : "";
  return (
    <label
      className="manifest-control manifest-control--provider_mode"
      data-control="provider_mode"
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
        disabled={!opts.length}
      >
        {!spec.required && !current ? <option value="">auto</option> : null}
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

export default ProviderModeControl;
