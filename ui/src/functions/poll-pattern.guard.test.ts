/**
 * Poll-pattern guard — pins the 2026-09-11 campaign's runaway-poll fix
 * (verify-3 §1: "every effect that calls `refetch()` ends `}, [tick])`").
 *
 * Context: `useFunction` fingerprints its `params` into the fetch key, so a
 * visibility tick placed in the dependency array of an effect that CALLS
 * `refetch()` re-keys the fetch and flashes the skeleton on every poll. The
 * hazard shipped in eight panes and was fixed to the canonical form
 * (`useVisibilityTick` + `useEffect(() => { refetch(); }, [tick])`). A pane
 * test that mocks `useFunction` cannot catch a reintroduction, so this guard
 * reads the real sources with node fs (fonts.test.ts precedent).
 *
 * Two assertions:
 *   1. NEGATIVE — no effect that calls `refetch()` may list `refetch` in its
 *      dependency array. The safe ref-mirror idiom (`refetchRef.current =
 *      refetch` in `}, [refetch])`) is allowed because it never calls
 *      refetch — flagged in verify-3 §5 so a mechanical sweep doesn't
 *      misread it as a regression.
 *   2. POSITIVE — the campaign's canonical refetch-calling effects still
 *      exist in the panes that were fixed.
 *
 * A meaningful file count (>100) is asserted so a path/glob regression that
 * silently scans nothing fails loudly instead of passing vacuously.
 */
import { describe, expect, it, vi } from "vitest";
import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { createElement } from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { TECHPane } from "./TECH";

/**
 * verify-3 §5 residual: pane tests mock `useFunction`, so they cannot catch a
 * dependency-loop reintroduction. This real-hook check renders a fixed pane
 * with the REAL `useFunction` (only `runFunction` + the visibility tick are
 * mocked) and requires the refetch count to stop after a tick. With the old
 * `[tick, refetch]` deps, each refetch re-renders with a fresh `refetch`
 * identity → the effect re-runs → unbounded refetch loop.
 */
const realHook = vi.hoisted(() => ({
  runFunction: vi.fn(),
  tick: { value: 0 },
}));

vi.mock("@/lib/functions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/functions")>();
  return { ...actual, runFunction: realHook.runFunction };
});

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => realHook.tick.value,
}));

const FUNCTIONS_DIR = resolve(__dirname);
const REFETCH_CALL = /(?:^|[^\w.])refetch\s*\(/;

/** Recursively collect non-test `.tsx` panes under ui/src/functions. */
function collectFunctionTsxFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectFunctionTsxFiles(full));
    } else if (
      entry.name.endsWith(".tsx") &&
      !entry.name.includes(".test.") &&
      !entry.name.includes(".spec.")
    ) {
      out.push(full);
    }
  }
  return out;
}

interface EffectRecord {
  line: number;
  deps: string;
  body: string;
}

/**
 * Line-oriented scanner for `useEffect(...)` blocks. It collects each call
 * from the `useEffect(` line through its dependency-array terminator
 * (`}, [deps]);`), handling both single-line and multi-line dep arrays.
 * Effects without a dep array are skipped (they cannot key the fetch).
 */
function scanEffects(source: string): EffectRecord[] {
  const lines = source.split(/\r?\n/);
  const records: EffectRecord[] = [];
  let i = 0;
  while (i < lines.length) {
    if (!/\buse(?:Layout)?Effect\s*\(/.test(lines[i] ?? "")) {
      i += 1;
      continue;
    }
    const start = i;
    const body: string[] = [];
    let deps: string | null = null;
    let cursor = start;
    while (cursor < lines.length && cursor - start < 400) {
      const line = lines[cursor] ?? "";
      const single = /\}\s*,\s*\[([^\]]*)\]\s*\)\s*;?\s*$/.exec(line);
      if (single) {
        body.push(line);
        deps = single[1] ?? "";
        break;
      }
      const multi = /\}\s*,\s*\[/.exec(line);
      if (multi) {
        body.push(line);
        const collected: string[] = [
          line.slice((multi.index ?? 0) + multi[0].length),
        ];
        let closed = false;
        let inner = cursor + 1;
        while (inner < lines.length && inner - start < 400) {
          const innerLine = lines[inner] ?? "";
          body.push(innerLine);
          collected.push(innerLine);
          if (/\][^[\]]*\)\s*;?\s*$/.test(innerLine)) {
            closed = true;
            cursor = inner;
            break;
          }
          inner += 1;
        }
        if (closed) {
          const flat = collected.join("\n");
          const arr = /\[([\s\S]*)\]/.exec(flat);
          deps = arr?.[1] ?? flat;
        }
        break;
      }
      body.push(line);
      cursor += 1;
    }
    if (deps != null) {
      records.push({ line: start + 1, deps, body: body.join("\n") });
    }
    i = Math.max(cursor + 1, start + 1);
  }
  return records;
}

const files = collectFunctionTsxFiles(FUNCTIONS_DIR);

describe("poll-pattern guard (campaign 2026-09-11)", () => {
  it("scans a meaningful number of function panes", () => {
    // 157 panes at campaign close-out; a broken glob/path fails loudly.
    expect(files.length).toBeGreaterThan(100);
  });

  it("never lists refetch in the deps of an effect that calls refetch()", () => {
    const hazards: string[] = [];
    let effectCount = 0;
    for (const file of files) {
      for (const record of scanEffects(readFileSync(file, "utf8"))) {
        effectCount += 1;
        if (/refetch/.test(record.deps) && REFETCH_CALL.test(record.body)) {
          hazards.push(
            `${file.replace(FUNCTIONS_DIR, "functions")}:${record.line} deps=[${record.deps.trim()}]`,
          );
        }
      }
    }
    // Sanity: the scanner really walked the panes (not an empty mis-parse).
    expect(effectCount).toBeGreaterThan(50);
    expect(hazards).toEqual([]);
  });

  it("keeps the campaign's canonical refetch-on-tick effects in place", () => {
    const fixedPanes = [
      "FXIP",
      "GLCO",
      "OVDV",
      "POLY",
      "TCA",
      "WB",
      "WCRS",
      "WIRP",
      "TRDH",
      "DEBT",
    ];
    for (const name of fixedPanes) {
      const file = files.find((candidate) => candidate.endsWith(`${name}.tsx`));
      expect(file, `${name}.tsx not found under ui/src/functions`).toBeTruthy();
      const records = scanEffects(readFileSync(file as string, "utf8"));
      const canonical = records.some(
        (record) => REFETCH_CALL.test(record.body) && !/refetch/.test(record.deps),
      );
      expect(canonical, `${name} lost its refetch-on-tick effect`).toBe(true);
    }
  });
});

describe("poll-pattern real-hook regression (verify-3 §5 residual)", () => {
  it("bounds refetches after a visibility tick with the real useFunction", async () => {
    realHook.runFunction.mockReset();
    realHook.tick.value = 0;
    let calls = 0;
    const payload = {
      data: {
        status: "provider_unavailable",
        reason: "test",
        rows: [],
        history: [],
      },
      sources: [],
      warnings: [],
    };
    // Runaway cap: a reintroduced dep loop never settles, which would hang
    // the suite on React's update storm — fail fast with a clear error.
    realHook.runFunction.mockImplementation(() => {
      calls += 1;
      if (calls > 20) throw new Error("runaway refetch loop detected");
      return Promise.resolve(payload);
    });
    try {
      const { rerender } = render(
        createElement(TECHPane, { code: "TECH", symbol: "AAPL" }),
      );
      await waitFor(() =>
        expect(realHook.runFunction).toHaveBeenCalledTimes(1),
      );
      realHook.tick.value = 1;
      rerender(createElement(TECHPane, { code: "TECH", symbol: "AAPL" }));
      await waitFor(() =>
        expect(realHook.runFunction).toHaveBeenCalledTimes(2),
      );
      // Settle macrotasks: a `[tick, refetch]` regression would keep
      // refetching here without bound. Allow at most one trailing settle.
      await new Promise((resolveTick) => setTimeout(resolveTick, 50));
      expect(realHook.runFunction.mock.calls.length).toBeLessThanOrEqual(3);
    } finally {
      cleanup();
    }
  });
});
