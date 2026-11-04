import { describe, expect, it } from "vitest";
import { validateSlotFile } from "./FileUploader";

function file(name: string, size: number): File {
  return new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
}

describe("validateSlotFile", () => {
  const accept = [".pdf", ".png"];

  it("accepts a matching file", () => {
    expect(validateSlotFile(file("a.PDF", 10), accept, 100)).toEqual({ ok: true, error: null });
  });

  it("rejects unknown extensions", () => {
    const result = validateSlotFile(file("a.exe", 10), accept, 100);
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/allowed/i);
  });

  it("rejects empty and oversized files", () => {
    expect(validateSlotFile(file("a.pdf", 0), accept, 100).ok).toBe(false);
    expect(validateSlotFile(file("a.pdf", 101), accept, 100).ok).toBe(false);
  });
});
