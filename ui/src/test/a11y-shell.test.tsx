/**
 * A11Y-05 / A11Y-08 Round-4A tests.
 *
 * Validate:
 *  - Welcome pane exposes the h1 (visually hidden, anchors the document
 *    outline) + ≥4 h2 / h3 landmarks for screen-reader navigation.
 *  - Sidebar function rows are real `<a href="#/fn/CODE">` links so
 *    middle-click, drag-to-tab, and assistive tech land them in nav-mode.
 *  - The CSP utility class layer is present (smoke check) so the Tauri
 *    sibling can safely flip `style-src 'unsafe-inline'` →
 *    `'self' 'nonce-…'`.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Welcome } from "@/panes/Welcome";
import { Sidebar } from "@/shell/Sidebar";
import { useAppStore } from "@/lib/store";
import { pinItem, resetPinnedItemsForTests } from "@/lib/pins";

const __dirname = dirname(fileURLToPath(import.meta.url));
const indexCssRaw = readFileSync(
  resolve(__dirname, "..", "styles", "index.css"),
  "utf-8",
);

beforeEach(() => {
  cleanup();
  localStorage.clear();
  resetPinnedItemsForTests();
  // S11 fix: `readSidebarVisible()` defaults to false (design preset hides
  // the dock) so a fresh test environment renders the collapsed edge
  // hitbox instead of the full Sidebar — every Sidebar landmark test
  // would then miss its drop-zone / pinned heading. Force the docked
  // layout so the assertions reach the real DOM.
  useAppStore.setState({ sidebarVisible: true });
  // Seed a minimal function index so the Sidebar renders entries.
  useAppStore.getState().setFunctionIndex([
    {
      code: "GEX",
      name: "Gamma Exposure",
      category: "derivative",
      description: "Options gamma exposure",
    },
    {
      code: "PORT",
      name: "Portfolio",
      category: "portfolio",
      description: "Track allocations",
    },
    {
      code: "WATCH",
      name: "Watchlist",
      category: "portfolio",
      description: "Streaming quotes",
    },
    {
      code: "AGENT",
      name: "Symbol Agent",
      category: "screen",
      description: "Autonomous research",
    },
  ]);
});

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

describe("Welcome heading hierarchy (A11Y-05)", () => {
  it("renders the pane h2 landmark and at least four h3 sub-headings", () => {
    const { getAllByRole } = render(<Welcome />);
    const h2s = getAllByRole("heading", { level: 2 });
    expect(h2s.length).toBeGreaterThanOrEqual(1);
    const h3s = getAllByRole("heading", { level: 3 });
    // Portfolio board + Command deck + Function inventory + Exposure +
    // Workspace presets = 5 visible h3 sub-headings (and an sr-only KPI
    // ribbon heading lifts the total to 6).
    expect(h3s.length).toBeGreaterThanOrEqual(4);
  });
});

describe("Sidebar nav links (A11Y-08)", () => {
  it("renders each function row as an anchor with href=#/fn/<CODE>", () => {
    const { getByRole } = render(<Sidebar />);
    const portLink = getByRole("link", { name: /PORT/i });
    expect(portLink.tagName.toLowerCase()).toBe("a");
    expect(portLink.getAttribute("href")).toBe("#/fn/PORT");
  });

  it("shows a carried drag ghost and collapses the source row during pin drag", () => {
    const { container, getAllByRole, getByRole, queryByRole } = render(<Sidebar />);
    const pinnedDropZone = container.querySelector<HTMLElement>(
      '[aria-label="Pinned drop zone"]',
    );
    expect(pinnedDropZone).toBeTruthy();
    vi.spyOn(pinnedDropZone!, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 210,
      bottom: 240,
      width: 210,
      height: 240,
      toJSON: () => ({}),
    });

    const gammaSource = getAllByRole("link", { name: /Gamma Exposure GEX/i })[0];
    fireEvent.mouseDown(gammaSource, { button: 0, clientX: 72, clientY: 420 });
    fireEvent.mouseMove(window, { clientX: 92, clientY: 300 });

    const ghost = container.querySelector(".pin-drag-ghost");
    expect(ghost?.textContent).toContain("Gamma Exposure");
    expect(queryByRole("link", { name: /Gamma Exposure GEX/i })).toBeNull();

    fireEvent.mouseUp(window, { clientX: 92, clientY: 140 });
    expect(getByRole("heading", { name: /Pinned\s*5/i })).toBeTruthy();
    expect(getAllByRole("link", { name: /Gamma Exposure GEX/i })).toHaveLength(1);
    expect(queryByRole("link", { name: /GEX Gamma Exposure/i })).toBeNull();
  });

  it("keeps pinned functions out of their original source lists until unpinned", () => {
    pinItem({
      id: "function:GEX",
      kind: "function",
      code: "GEX",
      label: "Gamma Exposure",
      meta: "GEX",
      path: "/fn/GEX",
      href: "#/fn/GEX",
    });

    const { getAllByRole, getByRole, queryByRole } = render(<Sidebar />);

    expect(getByRole("heading", { name: /Pinned\s*5/i })).toBeTruthy();
    expect(getAllByRole("link", { name: /Gamma Exposure GEX/i })).toHaveLength(1);
    expect(queryByRole("link", { name: /GEX Gamma Exposure/i })).toBeNull();
    expect(getByRole("heading", { name: /Recent\s*4/i })).toBeTruthy();
    expect(getByRole("heading", { name: /Quick Functions\s*5/i })).toBeTruthy();
  });
});

describe("CSP utility-class stylesheet (Round-4A)", () => {
  it("ships the core `u-*` utility classes the Tauri sibling depends on", () => {
    // If the stylesheet drops any of these the production CSP flip would
    // regress lots of panes — keep this trip-wire green.
    const expected = [
      ".u-text-mute",
      ".u-pane-host",
      ".u-grid-gap-8",
      ".u-flex",
      ".u-items-center",
      ".u-sr-only",
      ".u-bar-fill",
      ".u-symbol-link",
    ];
    for (const selector of expected) {
      expect(indexCssRaw).toContain(selector);
    }
  });
});

describe("Dashboard theme token integration", () => {
  it("wires the Claude cockpit shell to Preferences theme tokens", () => {
    const marker = "/* Claude Design terminal cockpit integration. */";
    const cockpitCss = indexCssRaw.slice(indexCssRaw.indexOf(marker));
    expect(cockpitCss).toContain("--terminal-bg: var(--bg);");
    expect(cockpitCss).toContain("--terminal-panel: var(--surface-1);");
    expect(cockpitCss).toContain("--terminal-accent: var(--accent);");
    expect(cockpitCss).toContain("--terminal-positive: var(--positive);");
    expect(cockpitCss).toContain("background: var(--bg);");
    expect(cockpitCss).toContain("color: var(--terminal-accent);");

    for (const staleColor of [
      "rgba(126, 224, 170",
      "#050807",
      "#080d0b",
      "#7ee0aa",
      "#e8fff0",
      "#d9f6e7",
    ]) {
      expect(cockpitCss).not.toContain(staleColor);
    }
  });
});
