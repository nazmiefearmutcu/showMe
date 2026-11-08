/**
 * TRQA title wording (TRQA#1-RQ).
 *
 * The backend now answers over an earnings transcript, an audio transcript or
 * the 8-K earnings press release. The visible pane header and the static
 * catalog name must say so, not the transcript-only title.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TRQAPane } from "./TRQA";
import { STATIC_FUNCTION_INDEX } from "./static-index";

afterEach(() => {
  cleanup();
});

describe("TRQA title covers press releases (TRQA#1-RQ)", () => {
  it("pane header names transcripts and press releases, not transcripts only", () => {
    render(<TRQAPane code="TRQA" symbol="AAPL" />);
    expect(screen.getByText("Transcript & Press Release Q&A")).toBeInTheDocument();
    expect(screen.queryByText("Transcript Q&A")).toBeNull();
  });

  it("static catalog entry names and describes the press release source", () => {
    const entry = STATIC_FUNCTION_INDEX.find((row) => row.code === "TRQA");
    expect(entry?.name).toBe("Transcript & Press Release Q&A");
    expect(entry?.description ?? "").toMatch(/press release/i);
  });
});
