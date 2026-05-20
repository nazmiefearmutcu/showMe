import { beforeEach, describe, expect, it } from "vitest";
import {
  applyAccent,
  applyAppearancePrefs,
  applyDensity,
  applyTheme,
  readAccent,
  readDensity,
  readState,
  readTheme,
  setCustom,
  setDensity,
  setPreset,
  toggleTheme,
} from "./theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-accent");
  document.documentElement.removeAttribute("data-density");
  document.documentElement.removeAttribute("data-preset");
  document.documentElement.style.removeProperty("--bg");
  document.documentElement.style.removeProperty("--surface");
  document.documentElement.style.removeProperty("--accent");
});

describe("theme v2", () => {
  it("defaults to papyrus preset when nothing is stored", () => {
    const s = readState();
    expect(s.preset).toBe("papyrus");
    expect(s.density).toBe("compact");
  });

  it("migrates the old stored midnight default to papyrus once", () => {
    localStorage.setItem(
      "showme.theme.v2",
      JSON.stringify({
        preset: "midnight",
        custom: { bg: "#07080a", surface: "#0f1115", accent: "#7c7aff" },
        density: "comfortable",
      }),
    );

    const s = readState();

    expect(s.preset).toBe("papyrus");
    expect(s.density).toBe("comfortable");
    const stored = JSON.parse(localStorage.getItem("showme.theme.v2")!);
    expect(stored.preset).toBe("papyrus");
    expect(localStorage.getItem("showme.theme.defaultPapyrus.v1")).toBe("1");
  });

  it("setPreset writes data-preset and persists to localStorage v2", () => {
    setPreset("iced");
    expect(document.documentElement.getAttribute("data-preset")).toBe("iced");
    const stored = JSON.parse(localStorage.getItem("showme.theme.v2")!);
    expect(stored.preset).toBe("iced");
    expect(stored.custom.accent).toBe("#5bc0eb");
  });

  it("ships the ShowMe 0.01 theme preset set, including Matrix", () => {
    setPreset("matrix");
    expect(readState().preset).toBe("matrix");
    expect(document.documentElement.getAttribute("data-preset")).toBe("matrix");
    const stored = JSON.parse(localStorage.getItem("showme.theme.v2")!);
    expect(stored.custom).toEqual({
      bg: "#000000",
      surface: "#040b06",
      accent: "#00ff41",
    });
  });

  it("setCustom writes inline --bg / --surface / --accent and flips preset to custom", () => {
    setCustom({ bg: "#101010", surface: "#202020", accent: "#ff00aa" });
    expect(document.documentElement.getAttribute("data-preset")).toBe("custom");
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe("#101010");
    expect(document.documentElement.style.getPropertyValue("--surface")).toBe(
      "#202020",
    );
    expect(document.documentElement.style.getPropertyValue("--accent")).toBe(
      "#ff00aa",
    );
  });

  it("setDensity persists separately from preset", () => {
    setPreset("amber");
    setDensity("comfortable");
    expect(document.documentElement.getAttribute("data-density")).toBe(
      "comfortable",
    );
    const stored = JSON.parse(localStorage.getItem("showme.theme.v2")!);
    expect(stored.density).toBe("comfortable");
    expect(stored.preset).toBe("amber");
  });

  it("rejects non-hex custom colors and keeps prior values", () => {
    setCustom({ bg: "#101010", surface: "#202020", accent: "#ff00aa" });
    setCustom({ bg: "not-a-color" } as unknown as { bg: string });
    expect(document.documentElement.style.getPropertyValue("--bg")).toBe("#101010");
  });
});

describe("theme legacy API (back-compat)", () => {
  it("applyTheme + readTheme map onto presets", () => {
    applyTheme("light");
    expect(readTheme()).toBe("light");
    expect(document.documentElement.getAttribute("data-preset")).toBe("papyrus");
    applyTheme("dark");
    expect(readTheme()).toBe("dark");
    expect(document.documentElement.getAttribute("data-preset")).toBe("midnight");
  });

  it("toggleTheme flips and returns next", () => {
    applyTheme("dark");
    expect(toggleTheme()).toBe("light");
    expect(toggleTheme()).toBe("dark");
  });

  it("applyAccent maps to nearest preset", () => {
    applyAccent("amber");
    expect(readAccent()).toBe("amber");
    expect(document.documentElement.getAttribute("data-preset")).toBe("amber");
  });

  it("applyDensity persists", () => {
    applyDensity("comfortable");
    expect(readDensity()).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-density")).toBe(
      "comfortable",
    );
  });

  it("applyAppearancePrefs resolves a stored state on boot", () => {
    localStorage.setItem(
      "showme.theme.v2",
      JSON.stringify({
        preset: "iced",
        custom: { bg: "#07111c", surface: "#122033", accent: "#5bc0eb" },
        density: "comfortable",
      }),
    );
    applyAppearancePrefs();
    expect(document.documentElement.getAttribute("data-preset")).toBe("iced");
    expect(document.documentElement.getAttribute("data-density")).toBe(
      "comfortable",
    );
  });

  it("migrates v1 keys (theme=light, density=comfortable) on first read", () => {
    localStorage.setItem("showme.theme", "light");
    localStorage.setItem("showme.density", "comfortable");
    const s = readState();
    expect(s.preset).toBe("papyrus");
    expect(s.density).toBe("comfortable");
  });
});
