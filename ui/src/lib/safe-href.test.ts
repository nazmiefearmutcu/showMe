import { describe, expect, it } from "vitest";
import { safeHref } from "./safe-href";

describe("safeHref (SEC-8)", () => {
  it("keeps absolute http(s) URLs as given", () => {
    expect(safeHref("https://www.sec.gov/Archives/x.htm")).toBe("https://www.sec.gov/Archives/x.htm");
    expect(safeHref(" http://example.com/a?b=1 ")).toBe("http://example.com/a?b=1");
  });

  it("drops other schemes, relative paths and non-strings", () => {
    for (const bad of ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,x", "file:///C:/x",
      "/relative", "www.example.com", "", "https://", "https://exa mple.com", null, undefined, 42, {}]) {
      expect(safeHref(bad)).toBeUndefined();
    }
  });
});
