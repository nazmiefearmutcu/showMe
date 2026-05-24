/**
 * UA-CRITICAL-04 / UA-CRITICAL-05 — function_stub symbol-switch contracts.
 *
 * CRITICAL-04: param merge order. defaults < paramsOverride (seed defaults
 *              from a symbol-switch reset) < controlParams (user has been
 *              editing controls *after* mount) < paramsText (free-form JSON
 *              override). Previously `paramsOverride ?? controlParams` ate
 *              all user edits the moment the upstream symbol-change effect
 *              re-ran with a fresh `initialControlParams`.
 *
 * CRITICAL-05: query reset on symbol-only change. `setQueryText(initialQuery)`
 *              used to fire unconditionally inside the symbol-switch effect,
 *              wiping a query the user just typed. Fix: only reset when the
 *              function *code* itself changed (pane swap), or when the user
 *              hasn't typed anything yet.
 */
import { describe, expect, it } from "vitest";

// ---- CRITICAL-04 merge contract --------------------------------------------
type Params = Record<string, unknown>;
function mergeParams(opts: {
  defaults: Params;
  paramsOverride?: Params;
  controlParams: Params;
  paramsTextParsed?: Params;
  userEditedControls: boolean;
}): Params {
  const { defaults, paramsOverride, controlParams, paramsTextParsed, userEditedControls } = opts;
  return {
    ...defaults,
    ...(paramsOverride ?? {}),
    ...(userEditedControls || paramsOverride == null ? controlParams : {}),
    ...(paramsTextParsed ?? {}),
  };
}

describe("UA-CRITICAL-04: function_stub param merge order", () => {
  it("defaults are baseline", () => {
    expect(mergeParams({
      defaults: { limit: 10 },
      controlParams: {},
      userEditedControls: false,
    })).toEqual({ limit: 10 });
  });

  it("paramsOverride (reset seed) wins over defaults", () => {
    expect(mergeParams({
      defaults: { limit: 10 },
      paramsOverride: { limit: 50 },
      controlParams: {},
      userEditedControls: false,
    })).toEqual({ limit: 50 });
  });

  it("user-edited controlParams win over paramsOverride", () => {
    expect(mergeParams({
      defaults: { limit: 10 },
      paramsOverride: { limit: 50 },
      controlParams: { limit: 999 },
      userEditedControls: true,
    })).toEqual({ limit: 999 });
  });

  it("paramsOverride wins on a symbol-switch when user has NOT edited", () => {
    // This is the new behaviour. Previously controlParams (stale, defaulted)
    // would have shadowed the override silently.
    expect(mergeParams({
      defaults: { limit: 10 },
      paramsOverride: { limit: 50 },
      controlParams: { limit: 10 }, // looks like a default value
      userEditedControls: false,
    })).toEqual({ limit: 50 });
  });

  it("paramsText (free-form JSON) is the highest precedence", () => {
    expect(mergeParams({
      defaults: { limit: 10 },
      paramsOverride: { limit: 50 },
      controlParams: { limit: 999 },
      paramsTextParsed: { limit: 1 },
      userEditedControls: true,
    })).toEqual({ limit: 1 });
  });

  it("when no override is supplied, controlParams always win over defaults", () => {
    expect(mergeParams({
      defaults: { limit: 10 },
      controlParams: { limit: 42 },
      userEditedControls: true,
    })).toEqual({ limit: 42 });
  });
});

// ---- CRITICAL-05 query reset contract --------------------------------------
function shouldResetQuery(codeChanged: boolean, userQueryEdited: boolean): boolean {
  return codeChanged || !userQueryEdited;
}

describe("UA-CRITICAL-05: function_stub query reset on symbol switch", () => {
  it("does NOT reset when user typed a query and only the symbol changed", () => {
    expect(shouldResetQuery(false, true)).toBe(false);
  });

  it("resets when the function code itself changes (pane swap)", () => {
    expect(shouldResetQuery(true, true)).toBe(true);
    expect(shouldResetQuery(true, false)).toBe(true);
  });

  it("resets when user hasn't typed anything yet, even on symbol-only change", () => {
    expect(shouldResetQuery(false, false)).toBe(true);
  });
});
