/**
 * S02 contract guard for WATCH.
 *
 * The S01 → S02 recovery brief is explicit: WATCH must consume the canonical
 * `lib/market-data` layer instead of hand-wiring `fetchQuote` and
 * `subscribeQuote`. This is a lightweight static-analysis test so a future
 * refactor that re-introduces bespoke quote polling fails CI loudly.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(here, "WATCH.tsx"), "utf8");

describe("WATCH consumes the canonical market-data layer", () => {
  it("imports useLiveQuotes from lib/market-data", () => {
    expect(source).toMatch(/from\s+["']@\/lib\/market-data["']/);
    expect(source).toMatch(/useLiveQuotes/);
  });

  it("does not import the low-level quote snapshot helper", () => {
    expect(source).not.toMatch(/from\s+["']@\/lib\/quotes["']/);
    expect(source).not.toMatch(/\bfetchQuote\s*\(/);
  });

  it("does not subscribe to the raw WebSocket helper", () => {
    expect(source).not.toMatch(/from\s+["']@\/lib\/stream["']/);
    expect(source).not.toMatch(/\bsubscribeQuote\s*\(/);
  });

  it("does not hand-roll a price polling interval", () => {
    // The canonical hook owns the poll cadence. WATCH must not run
    // setInterval on its own snapshot fetcher.
    expect(source).not.toMatch(/setInterval\(\s*refresh/);
    expect(source).not.toMatch(/setInterval\(\s*refreshPrices/);
  });
});
