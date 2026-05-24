/**
 * QA-2026-05-23 — Agent E scope.
 *
 * Top-nav (Overview / Watchlist / Portfolio / AAPL / Markets / News /
 * Functions) and the Prefs button must all DO something real now (was
 * visual-only). Each click routes to a registered surface or — for
 * Markets — loads a built-in preset.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Titlebar } from "./Titlebar";
import { useAppStore } from "@/lib/store";
import { useWorkspace, leaf } from "@/lib/workspace";

// Tauri invoke is a no-op in jsdom.
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  listen: vi.fn(async () => () => undefined),
}));

beforeEach(() => {
  window.location.hash = "#/";
  useAppStore.setState({
    paletteOpen: false,
    sidebarVisible: false,
    functionIndex: [],
    sidecarStatus: "healthy",
  });
  useWorkspace.setState({
    tree: leaf("HOME"),
    focusedId: "HOME",
  });
});

afterEach(() => cleanup());

describe("Titlebar top-nav — QA-2026-05-23 wire-up", () => {
  it("Overview routes to /", () => {
    render(<Titlebar />);
    window.location.hash = "#/fn/DES";
    fireEvent.click(screen.getByRole("button", { name: "Overview" }));
    expect(window.location.hash).toBe("#/");
  });

  it("Watchlist routes to /fn/WATCH", () => {
    render(<Titlebar />);
    fireEvent.click(screen.getByRole("button", { name: "Watchlist" }));
    expect(window.location.hash).toBe("#/fn/WATCH");
  });

  it("Portfolio routes to /fn/PORT", () => {
    render(<Titlebar />);
    fireEvent.click(screen.getByRole("button", { name: "Portfolio" }));
    expect(window.location.hash).toBe("#/fn/PORT");
  });

  it("AAPL routes to a DES pane scoped to AAPL", () => {
    render(<Titlebar />);
    fireEvent.click(screen.getByRole("button", { name: "AAPL" }));
    expect(window.location.hash).toBe("#/symbol/AAPL/DES");
  });

  it("News routes to /fn/NI", () => {
    render(<Titlebar />);
    fireEvent.click(screen.getByRole("button", { name: "News" }));
    expect(window.location.hash).toBe("#/fn/NI");
  });

  it("Markets loads the markets-overview preset (tree mutates)", () => {
    render(<Titlebar />);
    const before = useWorkspace.getState().tree;
    fireEvent.click(screen.getByRole("button", { name: "Markets" }));
    const after = useWorkspace.getState().tree;
    expect(after).not.toBe(before);
    expect(after.kind).toBe("split"); // markets-overview is a 2×2 split.
  });

  it("Functions opens the command palette", () => {
    render(<Titlebar />);
    expect(useAppStore.getState().paletteOpen).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Functions" }));
    expect(useAppStore.getState().paletteOpen).toBe(true);
  });

  it("Prefs button navigates to /preferences", () => {
    render(<Titlebar />);
    fireEvent.click(screen.getByRole("button", { name: /Preferences/i }));
    expect(window.location.hash).toBe("#/preferences");
  });

  it("Overview gets aria-current='page' when route === welcome", () => {
    render(<Titlebar />);
    const btn = screen.getByRole("button", { name: "Overview" });
    expect(btn.getAttribute("aria-current")).toBe("page");
  });

  it("New button no longer advertises ⌘N in title (QA: fake shortcut)", () => {
    render(<Titlebar />);
    const btn = screen.getByRole("button", { name: /new window/i });
    expect(btn.getAttribute("title") ?? "").not.toContain("⌘N");
  });
});
