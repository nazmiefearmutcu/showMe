/**
 * S04-R — Source-level regression guards for the ShowMe critical-pane
 * UI / no-op / live-state recovery sweep.
 *
 * These tests read the owned function panes with `readFileSync` and
 * assert string-level invariants for the bugs fixed in S04-R. They
 * intentionally do NOT mount the React tree — the heavy panes
 * (SCAN, TOP) require sidecar fetch, workspace store, and router
 * providers to render even a smoke output, and the bugs being pinned
 * are purely copy / structural drift that the existing component
 * surface already exposes textually.
 *
 * Style mirrors session16.regressions.test.ts so the runner picks the
 * same path-resolution convention.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = resolve(__dirname, "..", "..", "..");
const SCAN_SRC = readFileSync(resolve(ROOT, "ui/src/functions/SCAN.tsx"), "utf8");
const TOP_SRC = readFileSync(resolve(ROOT, "ui/src/functions/TOP.tsx"), "utf8");

describe("S04-R · SCAN drawer Phase C copy is honest", () => {
  it("Drawer signature accepts phaseC so the empty-fine message can differentiate", () => {
    // Without this prop the drawer cannot tell apart "user disabled
    // Phase C" from "Phase C ran and produced no fine data" — both
    // collapsed into a misleading "enable the toggle and re-run".
    expect(SCAN_SRC).toMatch(/phaseC:\s*boolean/);
  });

  it("Pane passes phaseC down to the drawer instance", () => {
    expect(SCAN_SRC).toMatch(/<Drawer[\s\S]{0,400}phaseC=\{phaseC\}/);
  });

  it("Empty-fine branch shows distinct copy when Phase C is on vs off", () => {
    // phaseC=true: "ran but produced no fine-scan output"
    expect(SCAN_SRC).toMatch(/Phase C ran but produced no fine-scan output/);
    // phaseC=false: spell out where the toggle lives so the user can
    // actually find it from the drawer view.
    expect(SCAN_SRC).toMatch(/filter rail/);
    expect(SCAN_SRC).toMatch(/Phase C is disabled/);
  });

  it("Legacy misleading copy is gone", () => {
    // Previous copy: "Phase C disabled · enable the toggle and re-run."
    // It said the toggle existed but never pointed at the filter rail,
    // and it lied to the user whenever phaseC was already on.
    expect(SCAN_SRC).not.toMatch(/Phase C disabled · enable the toggle and re-run/);
  });
});

describe("S04-R · SCAN filter-rail Reset/Apply wrapper is structurally honest", () => {
  it("Wrapper span no longer carries btn / btn--accent classes", () => {
    // The pre-fix wrapper was:
    //   <span className="u-inline-flex u-gap-6 u-items-center btn btn--ghost u-btn-mini btn--accent">
    //     <button>Reset</button><button>Apply</button>
    //   </span>
    // Visually one ghost+accent pill containing two real buttons that
    // inherited nothing. After the fix the wrapper is layout-only.
    expect(SCAN_SRC).not.toMatch(
      /className="u-inline-flex u-gap-6 u-items-center btn[^"]*">\s*<button[\s\S]{0,80}Reset/,
    );
  });

  it("Reset button is now a real ghost btn with its own className", () => {
    // Two independent assertions instead of a greedy multi-line regex
    // so a future formatter that re-flows the onClick body cannot
    // accidentally fail the test without changing intent.
    const resetBlock = SCAN_SRC.match(
      /<button[\s\S]{0,1200}?>\s*Reset\s*<\/button>/,
    );
    expect(resetBlock).not.toBeNull();
    expect(resetBlock?.[0]).toMatch(/className="btn btn--ghost u-btn-mini"/);
  });

  it("Apply button is now a real accent btn with its own className", () => {
    const applyBlock = SCAN_SRC.match(
      /<button[\s\S]{0,1200}?>\s*Apply\s*<\/button>/,
    );
    expect(applyBlock).not.toBeNull();
    expect(applyBlock?.[0]).toMatch(/className="btn btn--accent u-btn-mini"/);
  });

  it("Apply button surfaces the reason it is disabled via title", () => {
    // Pre-fix the disabled button had no title — the user could not
    // tell whether the empty-intent gate or the in-flight scan gate
    // was triggering the disable.
    expect(SCAN_SRC).toMatch(/Enter intent text first/);
    expect(SCAN_SRC).toMatch(/Scan in flight/);
  });
});

describe("S04-R · TOP header live-state pill is honest", () => {
  it("Hardcoded LIVE · 60s pill is removed", () => {
    // The literal pill ignored fetch state — green even mid-error.
    expect(TOP_SRC).not.toMatch(
      /<Pill\s+tone="positive"\s+variant="soft"\s+withDot>\s*LIVE · 60s\s*<\/Pill>/,
    );
  });

  it("State honesty now comes from the Awareness states, not a local pill", () => {
    // 2026-11-08: TOP was rebuilt on the Awareness story list. The data-mode pill lives in
    // PaneChrome (from the function contract); the pane itself must render the honest
    // service-down state and the provider-health strip instead of any hand-made LIVE pill.
    expect(TOP_SRC).toMatch(/NewsFrame/);
    const frame = readFileSync(resolve(ROOT, "ui/src/functions/awareness/NewsFrame.tsx"), "utf8");
    expect(frame).toMatch(/AwarenessUnavailable/);
    expect(frame).toMatch(/ProviderHealthStrip/);
    expect(TOP_SRC).not.toMatch(/withDot>\s*LIVE/);
  });
});

describe("S04-R · TOP sort indicator is not falsely interactive", () => {
  it("The decorative BY RECENT ↓ pill no longer carries a sort arrow", () => {
    // The arrow read as a clickable column-sort toggle on a static
    // <Pill> (presentational <span>, no onClick).
    expect(TOP_SRC).not.toMatch(/BY RECENT ↓/);
  });

  it("No fake sort toggle is rendered", () => {
    // The Awareness list is ordered newest-first by the backend; no decorative sort control.
    expect(TOP_SRC).not.toMatch(/RECENT FIRST/);
    expect(TOP_SRC).not.toMatch(/<Pill[^>]*>\s*IMPORTANCE/);
  });
});
