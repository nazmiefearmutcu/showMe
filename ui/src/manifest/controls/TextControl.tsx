/**
 * TextControl — placeholder. Plain free-form text input.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

export function TextControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const current = typeof value === "string" ? value : "";
  return (
    <label
      className="manifest-control manifest-control--text"
      data-control="text"
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
        aria-label={spec.label}
        onChange={(e) => onChange(e.target.value)}
      />
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default TextControl;
