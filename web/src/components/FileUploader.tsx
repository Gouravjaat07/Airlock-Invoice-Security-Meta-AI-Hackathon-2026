/** Single-file upload slot with drag/drop. Client checks are early hints only. */

import { useRef, useState } from "react";
import { formatBytes } from "../utils/format";
import { UploadIcon } from "./icons";

export interface SlotValidation {
  ok: boolean;
  error: string | null;
}

export function validateSlotFile(
  file: File,
  accept: readonly string[],
  maxBytes: number,
): SlotValidation {
  const lower = file.name.toLowerCase();
  const extOk = accept.some((ext) => lower.endsWith(ext.toLowerCase()));
  if (!extOk) {
    return { ok: false, error: `Unsupported file type. Allowed: ${accept.join(", ")}` };
  }
  if (file.size === 0) return { ok: false, error: "The file is empty." };
  if (file.size > maxBytes) {
    return { ok: false, error: `File exceeds ${formatBytes(maxBytes)}.` };
  }
  return { ok: true, error: null };
}

export function FileSlot({
  id,
  label,
  hint,
  accept,
  maxBytes,
  value,
  onChange,
  error,
}: {
  id: string;
  label: string;
  hint: string;
  accept: readonly string[];
  maxBytes: number;
  value: File | null;
  onChange: (file: File | null, error: string | null) => void;
  error: string | null;
}): React.JSX.Element {
  const [active, setActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const take = (file: File | null): void => {
    if (!file) {
      onChange(null, null);
      return;
    }
    const check = validateSlotFile(file, accept, maxBytes);
    onChange(check.ok ? file : null, check.error);
  };

  return (
    <div>
      <span className="ak-label" id={`${id}-label`}>
        {label}
      </span>
      <div style={{ height: 6 }} />
      <div
        className={`ak-drop${active ? " ak-drop--active" : ""}`}
        role="button"
        tabIndex={0}
        aria-labelledby={`${id}-label`}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setActive(true);
        }}
        onDragLeave={() => setActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setActive(false);
          take(event.dataTransfer.files?.[0] ?? null);
        }}
      >
        <UploadIcon />
        <p>
          <strong>Drop a file here or click to browse.</strong>
          <br />
          {hint}
        </p>
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={accept.join(",")}
          tabIndex={-1}
          aria-hidden="true"
          onChange={(event) => {
            take(event.target.files?.[0] ?? null);
            event.target.value = "";
          }}
        />
      </div>
      {value ? (
        <div className="ak-file-chip">
          <span className="ak-filename">{value.name}</span>
          <span className="ak-filesize">{formatBytes(value.size)}</span>
          <button type="button" className="ak-file-remove" onClick={() => take(null)}>
            Remove
          </button>
        </div>
      ) : null}
      {error ? (
        <span className="ak-field-error" role="alert" style={{ display: "block", marginTop: 8 }}>
          {error}
        </span>
      ) : null}
    </div>
  );
}
