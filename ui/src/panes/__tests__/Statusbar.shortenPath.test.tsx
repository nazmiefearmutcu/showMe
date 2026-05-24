/**
 * QA-2026-05-24 fix — `shortenPath` must collapse any `/Users/<account>/`
 * prefix to `~/`, not only Nazmi's home folder. Prior implementation
 * hard-coded `/Users/nazmi/` which silently no-op'd on every other
 * developer's machine and leaked the home directory into demo
 * screenshots + screen-share sessions.
 */
import { describe, expect, it } from "vitest";
import { shortenPath } from "@/shell/Statusbar";

describe("Statusbar.shortenPath — strip macOS user home", () => {
  it("collapses Nazmi's machine path (legacy)", () => {
    const path =
      "/Users/nazmi/Library/Application Support/app.showme.terminal/data";
    expect(shortenPath(path)).toBe(
      "~/Library/Application Support/app.showme.terminal/data",
    );
  });

  it("collapses a different developer's home (was a silent no-op pre-fix)", () => {
    const path = "/Users/alice/Desktop/Projeler/proje/showMe/engine";
    expect(shortenPath(path)).toBe("~/Desktop/Projeler/proje/showMe/engine");
  });

  it("leaves non-/Users paths intact (Linux, /tmp, etc.)", () => {
    expect(shortenPath("/var/folders/cache/showme")).toBe(
      "/var/folders/cache/showme",
    );
    expect(shortenPath("/tmp/showme")).toBe("/tmp/showme");
  });

  it("leaves an already-short ~ path alone", () => {
    expect(shortenPath("~/Library/Application Support/showMe")).toBe(
      "~/Library/Application Support/showMe",
    );
  });

  it("does not strip the literal hard-coded /Users/nazmi/ string for another user", () => {
    // Belt-and-braces: must never restore the legacy behaviour.
    const path = "/Users/bob/Desktop/x";
    expect(shortenPath(path)).not.toContain("nazmi");
    expect(shortenPath(path)).toBe("~/Desktop/x");
  });
});
