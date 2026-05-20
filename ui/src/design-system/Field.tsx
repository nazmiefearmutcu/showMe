import type { InputHTMLAttributes, ReactNode } from "react";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  hint?: string;
  trailing?: ReactNode;
  width?: number | string;
}

export function Field({
  label, hint, trailing, width, ...rest
}: FieldProps) {
  return (
    <label
      className="ds-field"
      style={{ width: width ?? "100%" }}
    >
      <span className="ds-field__label">{label}</span>
      <div className="ds-field__row">
        <input
          {...rest}
          className={`ds-field__input${rest.className ? ` ${rest.className}` : ""}`}
        />
        {trailing}
      </div>
      {hint && <span className="ds-field__hint">{hint}</span>}
    </label>
  );
}

export function FieldRow({ children }: { children: ReactNode }) {
  return <div className="ds-field-row">{children}</div>;
}
