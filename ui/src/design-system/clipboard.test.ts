/**
 * clipboard.ts — scalar/TSV shaping + clipboard fallback ladder.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildTsvRow, copyTextToClipboard, scalarToText } from "./clipboard";

afterEach(() => {
  vi.restoreAllMocks();
  // Remove the test-installed clipboard polyfill.
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("scalarToText", () => {
  it("renders nullish as empty, never 'null'", () => {
    expect(scalarToText(null)).toBe("");
    expect(scalarToText(undefined)).toBe("");
  });

  it("renders finite numbers and booleans plainly", () => {
    expect(scalarToText(12.5)).toBe("12.5");
    expect(scalarToText(true)).toBe("true");
    expect(scalarToText(false)).toBe("false");
  });

  it("joins arrays and drops non-finite numbers", () => {
    expect(scalarToText(["a", 1, null])).toBe("a / 1");
    expect(scalarToText(Number.NaN)).toBe("");
  });
});

describe("buildTsvRow", () => {
  it("joins values with tabs and collapses newlines", () => {
    expect(buildTsvRow(["AAPL", 190.5, null, "a\nb"])).toBe("AAPL\t190.5\t\ta b");
  });
});

describe("copyTextToClipboard", () => {
  it("uses the async Clipboard API when available", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    expect(copyTextToClipboard("hello")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
  });

  it("returns false when no clipboard path exists", () => {
    Reflect.deleteProperty(navigator, "clipboard");
    // jsdom's document.execCommand is undefined by default → false.
    expect(copyTextToClipboard("hello")).toBe(false);
  });

  it("falls back to execCommand when Clipboard API is absent", () => {
    Reflect.deleteProperty(navigator, "clipboard");
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, "execCommand", {
      value: execCommand,
      configurable: true,
    });
    expect(copyTextToClipboard("hello")).toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
    Reflect.deleteProperty(document, "execCommand");
  });
});
