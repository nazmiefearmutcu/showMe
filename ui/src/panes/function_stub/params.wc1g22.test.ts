/**
 * SAT default query - wc1-g22 (SAT-R1).
 *
 * The generic stub must not prefill a San Francisco bbox the user never chose.
 * An empty query lets the SAT handler apply its own labelled preset.
 */
import { describe, expect, it } from "vitest";
import { defaultQueryForFunction } from "./params";

describe("SAT default query", () => {
  it("does not prefill the San Francisco bbox", () => {
    const query = defaultQueryForFunction("SAT");
    expect(query).toBe("");
    expect(query).not.toContain("-122.55");
  });
});
