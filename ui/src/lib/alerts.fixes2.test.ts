/**
 * Bundle D / TOCTOU-02 — concurrent alert writes serialize.
 *
 * Same pattern as the watchlist regression: parallel `addAlert()` calls
 * used to both read against the same baseline, both write, last-writer-
 * wins. The queue funnels mutations so every read sees the freshest
 * publish.
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import {
  addAlert,
  clearAlerts,
  deleteAlert,
  loadAlerts,
  toggleAlert,
  type AlertRow,
} from "./alerts";

function alert(symbol: string): Omit<AlertRow, "id" | "created_at" | "fired_count" | "active"> {
  return {
    symbol,
    field: "price",
    direction: "above",
    threshold: 100,
  };
}

describe("alerts concurrent writes (TOCTOU)", () => {
  beforeEach(async () => {
    await clearAlerts();
  });
  afterEach(async () => {
    await clearAlerts();
  });

  it("two concurrent addAlert() calls both persist", async () => {
    const [a, b] = await Promise.all([
      addAlert(alert("AAPL")),
      addAlert(alert("MSFT")),
    ]);
    expect(a.id).toBeTruthy();
    expect(b.id).toBeTruthy();
    expect(a.id).not.toBe(b.id);
    const rows = await loadAlerts();
    expect(rows.map((r) => r.symbol).sort()).toEqual(["AAPL", "MSFT"]);
  });

  it("ten concurrent adds all land", async () => {
    const syms = Array.from({ length: 10 }, (_, i) => `SYM${i}`);
    await Promise.all(syms.map((s) => addAlert(alert(s))));
    const rows = await loadAlerts();
    expect(rows).toHaveLength(10);
    expect(rows.map((r) => r.symbol).sort()).toEqual([...syms].sort());
  });

  it("toggle/delete races complete deterministically", async () => {
    const a = await addAlert(alert("AAPL"));
    const b = await addAlert(alert("MSFT"));
    await Promise.all([
      toggleAlert(a.id, false),
      toggleAlert(b.id, false),
      deleteAlert(a.id),
    ]);
    const rows = await loadAlerts();
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe(b.id);
    expect(rows[0].active).toBe(false);
  });
});
