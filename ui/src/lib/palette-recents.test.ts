import { beforeEach, describe, expect, it } from "vitest";
import { __resetForTests, listRecentCodes, recordRecentCode } from "./palette-recents";

describe("palette recents", () => {
  beforeEach(() => __resetForTests());

  it("starts empty", () => {
    expect(listRecentCodes()).toEqual([]);
  });

  it("records a code at the top of the stack", () => {
    recordRecentCode("PORT");
    expect(listRecentCodes()).toEqual(["PORT"]);
  });

  it("dedupes and reorders existing entries", () => {
    recordRecentCode("PORT");
    recordRecentCode("WATCH");
    recordRecentCode("PORT");
    expect(listRecentCodes()).toEqual(["PORT", "WATCH"]);
  });

  it("caps the stack at 5 entries", () => {
    for (const code of ["A", "B", "C", "D", "E", "F", "G"]) {
      recordRecentCode(code);
    }
    expect(listRecentCodes()).toEqual(["G", "F", "E", "D", "C"]);
  });

  it("uppercases for stable comparisons", () => {
    recordRecentCode("port");
    recordRecentCode("PORT");
    expect(listRecentCodes()).toEqual(["PORT"]);
  });
});
