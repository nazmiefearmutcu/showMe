import { type CSSProperties, type ReactNode } from "react";
import { Pill } from "@/design-system";
import {
  NEWS_LIMITS,
  ROW_LIMITS,
  TOP_N_LIMITS,
  type LoadState,
  type NewsLimit,
  type PrimitiveControlValue,
  type RowLimit,
  type TopNLimit,
} from "./function-control-state";

interface SegmentOption<T extends PrimitiveControlValue> {
  value: T;
  label?: string;
  title?: string;
}

interface SegmentedControlProps<T extends PrimitiveControlValue> {
  label: string;
  value: T;
  options: readonly (T | SegmentOption<T>)[];
  onChange: (value: T) => void;
  disabled?: boolean;
  title?: string;
}

export function SegmentedControl<T extends PrimitiveControlValue>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  title,
}: SegmentedControlProps<T>) {
  return (
    <div aria-label={title ?? label} className="fn-segmented">
      <span style={controlLabelStyle}>{label}</span>
      {options.map((raw) => {
        const option = normalizeOption(raw);
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            disabled={disabled || active}
            onClick={() => onChange(option.value)}
            title={option.title ?? `${label} ${option.label ?? option.value}`}
            className={`fn-segmented__opt${active ? " fn-segmented__opt--active" : ""}${disabled && !active ? " fn-segmented__opt--disabled" : ""}`}
          >
            {option.label ?? option.value}
          </button>
        );
      })}
    </div>
  );
}

export function NewsLimitControl({
  value,
  onChange,
  disabled,
}: {
  value: NewsLimit;
  onChange: (value: NewsLimit) => void;
  disabled?: boolean;
}) {
  return (
    <SegmentedControl
      label="LAST"
      value={value}
      options={NEWS_LIMITS}
      onChange={onChange}
      disabled={disabled}
      title="Last news count"
    />
  );
}

export function RowLimitControl({
  value,
  onChange,
  disabled,
  label = "ROWS",
}: {
  value: RowLimit | TopNLimit;
  onChange: (value: RowLimit | TopNLimit) => void;
  disabled?: boolean;
  label?: string;
}) {
  const options = label === "TOP" ? TOP_N_LIMITS : ROW_LIMITS;
  return (
    <SegmentedControl
      label={label}
      value={value}
      options={options}
      onChange={(next) => onChange(next)}
      disabled={disabled}
      title={`${label} count`}
    />
  );
}

export function RefreshButton({
  loading,
  onClick,
  disabled,
  title = "Refresh",
  label,
}: {
  loading?: boolean;
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      className={`btn btn--ghost fn-refresh-btn${label ? " fn-refresh-btn--labeled" : ""}`}
      onClick={onClick}
      disabled={disabled || loading}
      title={title}
      aria-label={title}
    >
      {loading ? "..." : label ?? "↻"}
    </button>
  );
}

export function LoadStatePill({
  state,
  status,
}: {
  state: LoadState;
  status?: string | null;
}) {
  const normalized = status?.trim().toLowerCase();
  const label = state === "ok" && normalized && normalized !== "ok" ? normalized : state;
  const tone =
    state === "loading"
      ? "warn"
      : state === "error" || normalized === "input_error" || normalized === "calc_error"
        ? "negative"
        : normalized === "empty" ||
            normalized === "provider_unavailable" ||
            normalized === "ready_no_positions"
          ? "warn"
          : state === "ok"
      ? "positive"
          : "muted";
  return (
    <Pill tone={tone} withDot={state === "loading" || tone === "positive"}>
      {label}
    </Pill>
  );
}

export function FunctionControlGroup({ children }: { children: ReactNode }) {
  return <div className="fn-control-group">{children}</div>;
}

function normalizeOption<T extends PrimitiveControlValue>(
  raw: T | SegmentOption<T>,
): SegmentOption<T> {
  if (typeof raw === "object" && raw !== null && "value" in raw) return raw;
  return { value: raw };
}

const controlLabelStyle: CSSProperties = {
  padding: "0 5px",
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 9,
  color: "var(--text-mute)",
  letterSpacing: "0.06em",
  whiteSpace: "nowrap",
};
