/**
 * SymbolPicker — placeholder. Later iteration will swap to the project's
 * fuzzy ticker autocomplete; for now we render a minimally-styled text input
 * keyed by the manifest InputSpec so derive-controls can wire it.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

export function SymbolPicker({ spec, value, onChange }: ControlProps): JSX.Element {
  return (
    <label
      className="manifest-control manifest-control--symbol_picker"
      data-control="symbol_picker"
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
        placeholder="AAPL, BTC/USDT, …"
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

export default SymbolPicker;
