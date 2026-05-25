/**
 * DateRangePicker — placeholder. When `spec.options` is populated we render
 * shorthand presets (1M/3M/6M/1Y/…); otherwise a paired native date input.
 */
import { type InputSpec } from "../types";

export interface ControlProps {
  spec: InputSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}

function normalizeOptions(options: unknown[] | null | undefined): string[] {
  if (!options) return [];
  return options
    .filter((o): o is string | number => typeof o === "string" || typeof o === "number")
    .map((o) => String(o));
}

export function DateRangePicker({ spec, value, onChange }: ControlProps): JSX.Element {
  const presets = normalizeOptions(spec.options);
  if (presets.length) {
    const current = typeof value === "string" ? value : "";
    return (
      <label
        className="manifest-control manifest-control--date_range"
        data-control="date_range"
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
          {presets.map((opt) => (
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
  // Free-form range — render a paired date input. Stored shape is
  // `{ from: string; to: string }` so the rest of the system can consume it.
  const safe =
    value && typeof value === "object" && value !== null
      ? (value as { from?: unknown; to?: unknown })
      : {};
  const from = typeof safe.from === "string" ? safe.from : "";
  const to = typeof safe.to === "string" ? safe.to : "";
  const emit = (next: { from: string; to: string }) => onChange(next);
  return (
    <fieldset
      className="manifest-control manifest-control--date_range"
      data-control="date_range"
      data-input-name={spec.name}
    >
      <legend className="manifest-control__label">
        {spec.label}
        {spec.required ? <span aria-hidden="true"> *</span> : null}
      </legend>
      <input
        type="date"
        aria-label={`${spec.label} from`}
        value={from}
        onChange={(e) => emit({ from: e.target.value, to })}
      />
      <input
        type="date"
        aria-label={`${spec.label} to`}
        value={to}
        onChange={(e) => emit({ from, to: e.target.value })}
      />
      {spec.description ? (
        <span className="manifest-control__hint">{spec.description}</span>
      ) : null}
    </fieldset>
  );
}

export default DateRangePicker;
