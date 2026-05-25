/**
 * NumberControl — placeholder. Honors min/max/step/unit from the InputSpec.
 * Emits `number` when parseable, falls back to `undefined` on empty input.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

export function NumberControl({ spec, value, onChange }: ControlProps): JSX.Element {
  const current =
    typeof value === "number" && Number.isFinite(value)
      ? String(value)
      : typeof value === "string"
        ? value
        : "";
  return (
    <label
      className="manifest-control manifest-control--number"
      data-control="number"
      data-input-name={spec.name}
    >
      <span className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
        {spec.unit ? <span className="manifest-control__unit"> ({spec.unit})</span> : null}
      </span>
      <input
        type="number"
        name={spec.name}
        required={spec.required}
        value={current}
        min={spec.min ?? undefined}
        max={spec.max ?? undefined}
        step={spec.step ?? undefined}
        aria-label={spec.label}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const n = Number(raw);
          onChange(Number.isFinite(n) ? n : raw);
        }}
      />
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default NumberControl;
