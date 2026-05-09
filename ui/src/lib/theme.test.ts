import { beforeEach, describe, expect, it } from "vitest";
import {
  applyAccent,
  applyAppearancePrefs,
  applyDensity,
  applyTheme,
  readAccent,
  readDensity,
  readTheme,
  toggleTheme,
} from "./theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-accent");
  document.documentElement.removeAttribute("data-density");
});

describe("theme", () => {
  it("defaults to dark when nothing is stored", () => {
    expect(readTheme()).toBe("dark");
  });

  it("persists choice via localStorage and html attribute", () => {
    applyTheme("light");
    expect(localStorage.getItem("showme.theme")).toBe("light");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(readTheme()).toBe("light");
  });

  it("toggleTheme flips and returns next", () => {
    applyTheme("dark");
    expect(toggleTheme()).toBe("light");
    expect(toggleTheme()).toBe("dark");
  });

  it("persists accent and density personalization", () => {
    expect(readAccent()).toBe("cyan");
    expect(readDensity()).toBe("compact");
    applyAccent("violet");
    applyDensity("comfortable");
    expect(localStorage.getItem("showme.accent")).toBe("violet");
    expect(localStorage.getItem("showme.density")).toBe("comfortable");
    expect(document.documentElement.getAttribute("data-accent")).toBe("violet");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
  });

  it("applies all saved appearance preferences at boot", () => {
    localStorage.setItem("showme.theme", "light");
    localStorage.setItem("showme.accent", "lime");
    localStorage.setItem("showme.density", "comfortable");
    applyAppearancePrefs();
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(document.documentElement.getAttribute("data-accent")).toBe("lime");
    expect(document.documentElement.getAttribute("data-density")).toBe("comfortable");
  });
});
