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

  it("FeedStatePill helper exists and is invoked from the header", () => {
    expect(TOP_SRC).toMatch(/function FeedStatePill/);
    expect(TOP_SRC).toMatch(/<FeedStatePill[\s\S]{0,200}state=\{state\}/);
    expect(TOP_SRC).toMatch(/hasArticles=\{articles\.length > 0\}/);
  });

  it("FeedStatePill differentiates OFFLINE / LOADING / SNAPSHOT / EMPTY / LIVE", () => {
    // All five honest states must appear as label literals.
    expect(TOP_SRC).toMatch(/OFFLINE/);
    expect(TOP_SRC).toMatch(/LOADING/);
    expect(TOP_SRC).toMatch(/SNAPSHOT · refreshing/);
    expect(TOP_SRC).toMatch(/EMPTY · /);
    expect(TOP_SRC).toMatch(/LIVE · /);
  });

  it("Error state renders the OFFLINE pill with a negative tone and no dot", () => {
    // Read the FeedStatePill body — error branch must not be the green
    // LIVE pill or the user keeps trusting a dead feed.
    const errorBranch = TOP_SRC.match(
      /if \(state === "error"\) \{[\s\S]{0,200}<Pill[\s\S]{0,120}<\/Pill>/,
    );
    expect(errorBranch).not.toBeNull();
    expect(errorBranch?.[0]).toMatch(/tone="negative"/);
    expect(errorBranch?.[0]).toMatch(/withDot=\{false\}/);
  });
});

describe("S04-R · TOP sort indicator is not falsely interactive", () => {
  it("The decorative BY RECENT ↓ pill no longer carries a sort arrow", () => {
    // The arrow read as a clickable column-sort toggle on a static
    // <Pill> (presentational <span>, no onClick).
    expect(TOP_SRC).not.toMatch(/BY RECENT ↓/);
  });

  it("Replaced with an unambiguous passive label", () => {
    expect(TOP_SRC).toMatch(
      /<Pill\s+tone="muted"\s+variant="soft"\s+withDot=\{false\}>\s*RECENT FIRST\s*<\/Pill>/,
    );
  });
});
