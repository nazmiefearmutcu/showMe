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

describe("Statusbar.shortenPath — strip Windows user home (HNT-05)", () => {
  it("collapses C:\\Users\\<account>\\ to ~\\", () => {
    const path = "C:\\Users\\Kullanıcı\\AppData\\Local\\showme\\engine\\data";
    expect(shortenPath(path)).toBe("~\\AppData\\Local\\showme\\engine\\data");
  });

  it("collapses any drive letter and any account name", () => {
    expect(shortenPath("D:\\Users\\alice\\Desktop\\x")).toBe("~\\Desktop\\x");
    expect(shortenPath("c:\\users\\bob\\projects\\showme")).toBe("~\\projects\\showme");
  });

  it("handles forward-slash Windows paths without rewriting the remainder", () => {
    expect(shortenPath("C:/Users/alice/Desktop/x")).toBe("~\\Desktop/x");
  });

  it("leaves non-home Windows paths intact", () => {
    expect(shortenPath("C:\\Program Files\\showme")).toBe("C:\\Program Files\\showme");
    expect(shortenPath("C:\\Users")).toBe("C:\\Users");
  });

  it("does not leak the account name for any home form", () => {
    for (const path of [
      "C:\\Users\\Kullanıcı\\Desktop\\x",
      "D:/Users/alice/Desktop/x",
    ]) {
      expect(shortenPath(path)).not.toContain("Kullanıcı");
      expect(shortenPath(path)).not.toContain("alice");
    }
  });
});
