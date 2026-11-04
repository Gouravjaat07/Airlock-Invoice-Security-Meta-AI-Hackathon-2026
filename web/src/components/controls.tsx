/** Form controls: button, inputs, select, PIN field. */

import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { EyeIcon, EyeOffIcon } from "./icons";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "md" | "sm";
  block?: boolean;
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  block = false,
  loading = false,
  disabled,
  children,
  type,
  ...rest
}: ButtonProps): React.JSX.Element {
  const cls = [
    "ak-btn",
    `ak-btn--${variant}`,
    size === "sm" ? "ak-btn--sm" : "",
    block ? "ak-btn--block" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button type={type ?? "button"} className={cls} disabled={disabled ?? loading} {...rest}>
      {loading ? <span className="ak-spinner" aria-hidden="true" /> : null}
      {children}
    </button>
  );
}

interface FieldProps {
  label: string;
  htmlFor: string;
  error?: string | null;
  hint?: ReactNode;
  children: ReactNode;
}

export function Field({ label, htmlFor, error, hint, children }: FieldProps): React.JSX.Element {
  return (
    <div className="ak-field">
      <label className="ak-label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {error ? (
        <span className="ak-field-error" role="alert">
          {error}
        </span>
      ) : null}
      {hint && !error ? <span className="ak-field-hint">{hint}</span> : null}
    </div>
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>): React.JSX.Element {
  return <input {...props} className={["ak-input", props.className].filter(Boolean).join(" ")} />;
}

export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>): React.JSX.Element {
  return <textarea {...props} className={["ak-textarea", props.className].filter(Boolean).join(" ")} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>): React.JSX.Element {
  return <select {...props} className={["ak-select", props.className].filter(Boolean).join(" ")} />;
}

interface PinInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  id: string;
}

export function PinInput({ id, ...rest }: PinInputProps): React.JSX.Element {
  const [visible, setVisible] = useState(false);
  return (
    <div className="ak-pin-wrap">
      <input
        {...rest}
        id={id}
        type={visible ? "text" : "password"}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        className="ak-input"
      />
      <button
        type="button"
        className="ak-pin-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-pressed={visible}
        aria-label={visible ? "Hide PIN" : "Show PIN"}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          {visible ? <EyeOffIcon /> : <EyeIcon />}
          {visible ? "Hide" : "Show"}
        </span>
      </button>
    </div>
  );
}
