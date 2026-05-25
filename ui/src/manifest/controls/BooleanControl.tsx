/**
 * BooleanControl — placeholder. Native checkbox.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

export function BooleanControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const current = value === true;
  return (
    <label
      className="manifest-control manifest-control--boolean"
      data-control="boolean"
      data-input-name={spec.name}
    >
      <input
        type="checkbox"
        name={spec.name}
        checked={current}
        aria-label={spec.label}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
      </span>
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default BooleanControl;
