import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { FileSlot } from "./FileUploader";

function Harness({ onChange }: { onChange: (file: File | null, error: string | null) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <FileSlot
      id="slot"
      label="Invoice"
      hint="PDF"
      accept={[".pdf"]}
      maxBytes={100}
      value={file}
      error={error}
      onChange={(f, e) => {
        setFile(f);
        setError(e);
        onChange(f, e);
      }}
    />
  );
}

describe("FileSlot", () => {
  it("accepts a dropped file and reports it", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    const { container } = render(<Harness onChange={onChange} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x".repeat(10)], "a.pdf", { type: "application/pdf" }));
    expect(onChange).toHaveBeenCalledWith(expect.any(File), null);
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
  });

  it("rejects disallowed types with an error", async () => {
    const onChange = vi.fn();
    const { container } = render(<Harness onChange={onChange} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    // fireEvent bypasses the input's accept filter (which userEvent honors),
    // exercising the component's own validation message.
    fireEvent.change(input, {
      target: { files: [new File(["x"], "a.exe", { type: "application/octet-stream" })] },
    });
    expect(screen.getByText(/Unsupported file type/)).toBeInTheDocument();
    expect(onChange).toHaveBeenCalledWith(null, expect.any(String));
  });
});
