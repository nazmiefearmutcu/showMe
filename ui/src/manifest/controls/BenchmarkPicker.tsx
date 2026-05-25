/**
 * BenchmarkPicker — placeholder. Identical UX to SymbolPicker but tagged
 * separately so a richer benchmark autocomplete can replace it later.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

export function BenchmarkPicker({ spec, value, onChange }: ControlProps): JSX.Element {
  return (
    <label
      className="manifest-control manifest-control--benchmark_picker"
      data-control="benchmark_picker"
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
        placeholder="SPY, ^GSPC, …"
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        aria-label={spec.label}
      />
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </label>
  );
}

export default BenchmarkPicker;
