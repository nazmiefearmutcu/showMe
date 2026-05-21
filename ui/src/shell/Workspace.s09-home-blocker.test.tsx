/**
 * S09 + S10 regression tests — pins both halves of the contract:
 *
 *  S09 (HARD RULE — must never regress):
 *   - `Workspace.tsx` must NEVER route HOME to `DesignExportRenderer`.
 *   - A mounted HOME pane must NEVER leak the design-export strings
 *     "SITUATION BRIEFING" or "SIDECAR :8421" or the structural marker
 *     `[data-design-code="HOME"]` / `.design-export`.
 *   - Critical codes (GP/HP/DES/WATCH/SCAN/PORT/TOP/NI/CN/MIS) must
 *     resolve to "native" (or "critical-missing" if the native pane is
 *     missing) — never to design-export.
 *
 *  S10 (dashboard restore — corrects the S09 regression):
 *   - The default workspace tree is a single `leaf("HOME")` again —
 *     because HOME is safe and native (`<Welcome />`).
 *   - `App.tsx routeToTarget(welcome)` returns `{ code: "HOME" }` again,
 *     so `#/` resolves to the native dashboard surface.
 *   - Sidebar Overview click only navigates — it does NOT call
 *     `loadBuiltinPreset("markets-overview")`. Markets Overview stays a
 *     separate preset reachable via the preset menu / command palette.
 *   - `restoreWorkspace` no longer filters out a single-HOME persisted
 *     tree — the legacy default is valid again.
 *   - The Markets Overview preset still exists and still contains GP +
 *     DES + WEI + TOP, just no longer the cold-boot default.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { Workspace, choosePaneRenderer } from "./Workspace";
import {
  leaf,
  useWorkspace,
  type LeafNode,
  type WorkspaceNode,
} from "@/lib/workspace";
import { BUILTIN_PRESETS, loadBuiltinPreset } from "@/lib/builtinPresets";

function collectLeafCodes(node: WorkspaceNode, out: string[] = []): string[] {
  if (node.kind === "leaf") {
    out.push(node.code);
  } else {
    for (const child of node.children) collectLeafCodes(child, out);
  }
  return out;
}

function findLeafByCode(node: WorkspaceNode, code: string): LeafNode | null {
  if (node.kind === "leaf") return node.code === code ? node : null;
  for (const child of node.children) {
    const hit = findLeafByCode(child, code);
    if (hit) return hit;
  }
  return null;
}

/**
 * Snapshot of the live workspace store so tests can mutate it (force a
 * HOME-only tree, swap to a preset, etc.) without leaking state into the
 * next test. The store is a Zustand singleton — the previous tree must
 * be put back on cleanup.
 */
function snapshotWorkspace() {
  const { tree, focusedId } = useWorkspace.getState();
  return { tree, focusedId };
}

function restoreWorkspaceSnapshot(snap: ReturnType<typeof snapshotWorkspace>) {
  useWorkspace.setState({ tree: snap.tree, focusedId: snap.focusedId });
}

describe("S10 dashboard restore + S09 HOME chart-blocker", () => {
  afterEach(() => {
    cleanup();
  });

  /* ───────────────────── S10 — dashboard restore ───────────────────── */

  it("default workspace tree is a single HOME leaf (the native dashboard)", () => {
    const { tree, focusedId } = useWorkspace.getState();
    expect(tree.kind).toBe("leaf");
    if (tree.kind === "leaf") {
      expect(tree.code).toBe("HOME");
      expect(focusedId).toBe(tree.id);
    }
  });

  it("App.tsx welcome route resolves back to a HOME target", () => {
    const source = readFileSync(resolve(__dirname, "../App.tsx"), "utf8");
    // S10 reverts the S09 `return null` so navigating to `#/` focuses
    // the HOME (Welcome) leaf again. The match is anchored to the
    // welcome branch of `routeToTarget` so other return-statements in
    // the file don't confuse the assertion.
    expect(source).toMatch(
      /case\s+["']welcome["']:[\s\S]{0,400}return\s+\{\s*code:\s*["']HOME["']\s*\}/,
    );
  });

  it("Sidebar Overview click only navigates — does NOT load markets-overview preset", () => {
    const source = readFileSync(
      resolve(__dirname, "./Sidebar.tsx"),
      "utf8",
    );
    // S10 hard rule: the Overview shortcut must NOT auto-load Markets
    // Overview. Markets Overview is a separate preset chip reachable
    // from the preset menu / command palette, not the dashboard click.
    expect(source).not.toMatch(/loadBuiltinPreset\(\s*["']markets-overview["']\s*\)/);
    expect(source).not.toMatch(
      /item\.code\s*===\s*["']HOME["'][\s\S]{0,200}loadBuiltinPreset/,
    );
    // The Overview WORKSPACE_ITEMS entry still anchors to "#/" so the
    // sidebar active-row highlight works (route.kind === "welcome").
    expect(source).toMatch(/code:\s*["']HOME["'],\s*label:\s*["']Overview["']/);
  });

  it("workspace-persist.ts restores single-HOME persisted state without filtering", () => {
    const source = readFileSync(
      resolve(__dirname, "../lib/workspace-persist.ts"),
      "utf8",
    );
    // S10: the S09 single-HOME skip is removed because HOME is safe and
    // native again. `restoreWorkspace` reads the persisted state and
    // calls `loadWorkspace(state)` unconditionally (after the null
    // guard) — no `state.tree.code === "HOME"` filter.
    expect(source).not.toMatch(
      /state\.tree[\s\S]{0,200}kind\s*===\s*["']leaf["'][\s\S]{0,200}code\s*===\s*["']HOME["']/,
    );
    expect(source).toMatch(/loadWorkspace\(state\)/);
  });

  it("Markets Overview preset still exists and still contains GP + DES + WEI + TOP", () => {
    const preset = BUILTIN_PRESETS.find((p) => p.id === "markets-overview");
    expect(preset, "markets-overview preset must remain reachable").toBeTruthy();
    const snap = snapshotWorkspace();
    try {
      const ok = loadBuiltinPreset("markets-overview", "AAPL");
      expect(ok).toBe(true);
      const tree = useWorkspace.getState().tree;
      const codes = collectLeafCodes(tree);
      expect(codes).toContain("GP");
      expect(codes).toContain("DES");
      expect(codes).toContain("WEI");
      expect(codes).toContain("TOP");
      const gp = findLeafByCode(tree, "GP");
      expect(gp?.symbol).toBe("AAPL");
    } finally {
      restoreWorkspaceSnapshot(snap);
    }
  });

  /* ───────────────────── S09 — chart-blocker (still in force) ───────── */

  it("Workspace.tsx HOME branch renders <Welcome />, NEVER DesignExportRenderer", () => {
    const source = readFileSync(
      resolve(__dirname, "./Workspace.tsx"),
      "utf8",
    );
    // The pre-S09 hazard: HOME branch wired to DesignExportRenderer.
    expect(source).not.toMatch(
      /code\s*===\s*["']HOME["'][\s\S]{0,200}DesignExportRenderer/,
    );
    // HOME branch must still exist and must render the native Welcome
    // dashboard.
    expect(source).toMatch(/code\s*===\s*["']HOME["']/);
    expect(source).toMatch(/<Welcome\s*\/>/);
  });

  it("rendered HOME pane leaks no PrChart strings ('SITUATION BRIEFING', 'SIDECAR :8421')", async () => {
    // The smoking-gun render contract: even if every other test passes,
    // if a real mount of `<Workspace />` with a HOME leaf produces the
    // design-export cockpit text, the blocker is back. These strings
    // are uniquely owned by the design-export module — `ProHome` ships
    // "SITUATION BRIEFING" and `PrShell` ships "SIDECAR :8421". Native
    // panes (Welcome, GP, DES, etc.) MUST NOT emit either string.
    const snap = snapshotWorkspace();
    try {
      const homeOnly = leaf("HOME");
      act(() => {
        useWorkspace.setState({ tree: homeOnly, focusedId: homeOnly.id });
      });
      const { container } = render(<Workspace />);
      await waitFor(
        () => {
          const fallback = container.querySelector(".pane-fallback");
          expect(fallback).toBeNull();
        },
        { timeout: 3000 },
      );
      const text = container.textContent ?? "";
      expect(text).not.toMatch(/SITUATION BRIEFING/);
      expect(text).not.toMatch(/SIDECAR\s*:\s*8421/i);
      // Belt: any "SIDECAR :<port>" pattern is design-export-only — the
      // real status bar reads sidecar port via React state, not a
      // hardcoded literal in markup.
      expect(text).not.toMatch(/SIDECAR\s*:\s*\d{4,5}/);
    } finally {
      restoreWorkspaceSnapshot(snap);
    }
  });

  it("rendered HOME pane carries no DesignExportRenderer marker element", async () => {
    // `DesignExportRenderer` wraps its output in
    // `<div className="design-export" data-design-code={code.toUpperCase()}>`.
    // The presence of that wrapper anywhere under a HOME leaf is the
    // structural signature of the design-export cockpit being re-routed.
    const snap = snapshotWorkspace();
    try {
      const homeOnly = leaf("HOME");
      act(() => {
        useWorkspace.setState({ tree: homeOnly, focusedId: homeOnly.id });
      });
      const { container } = render(<Workspace />);
      await waitFor(
        () => {
          const fallback = container.querySelector(".pane-fallback");
          expect(fallback).toBeNull();
        },
        { timeout: 3000 },
      );
      expect(container.querySelector('[data-design-code="HOME"]')).toBeNull();
      expect(container.querySelector(".design-export")).toBeNull();
    } finally {
      restoreWorkspaceSnapshot(snap);
    }
  });

  it("critical GP code still resolves to the native renderer", () => {
    // S05 invariant — kept across S09 + S10. Critical codes (GP, HP,
    // DES, WATCH, SCAN, PORT, TOP, NI, CN, MIS) MUST resolve to "native"
    // — never to design-export, template, or stub.
    expect(choosePaneRenderer("GP")).toBe("native");
    expect(choosePaneRenderer("gp")).toBe("native");
    expect(choosePaneRenderer("DES")).toBe("native");
    expect(choosePaneRenderer("WEI")).toBe("native");
    expect(choosePaneRenderer("TOP")).toBe("native");
  });

  it("resolver invariants: critical→critical-missing, non-critical-design-only→design-export", () => {
    // Pins the renderer contract independent of which codes happen to
    // have templates today.
    //
    // Non-critical, no native, no template, has design-export →
    // "design-export" (legitimate fallback path).
    expect(
      choosePaneRenderer("ANYFAKE", {
        hasNative: () => false,
        hasTemplate: () => false,
        hasDesignExport: () => true,
      }),
    ).toBe("design-export");

    // No design-export anywhere → "stub" (last-resort generic surface).
    expect(
      choosePaneRenderer("ANYFAKE", {
        hasNative: () => false,
        hasTemplate: () => false,
        hasDesignExport: () => false,
      }),
    ).toBe("stub");

    // Critical codes ignore design-export entirely — even if the design
    // module ships a component for the same code, missing-native lands
    // on `critical-missing` rather than design-export. This was the
    // exact failure mode S09 fixed for HOME (treated as a special case
    // in `Workspace.tsx` rather than relying on the critical list).
    for (const critical of ["GP", "HP", "DES", "WATCH", "TOP", "MIS"]) {
      expect(
        choosePaneRenderer(critical, {
          hasNative: () => false,
          hasTemplate: () => false,
          hasDesignExport: () => true,
        }),
      ).toBe("critical-missing");
    }
  });
});
