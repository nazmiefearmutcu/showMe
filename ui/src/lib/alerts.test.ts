import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  addAlert,
  clearAlerts,
  deleteAlert,
  loadAlerts,
  recordFire,
  toggleAlert,
} from "./alerts";

describe("alerts (browser-mode)", () => {
  beforeEach(() => clearAlerts());
  afterEach(() => clearAlerts());

  const sample = () => ({
    symbol: "AAPL",
    field: "price" as const,
    direction: "above" as const,
    threshold: 200,
    note: "earnings",
  });

  it("addAlert assigns id and defaults", async () => {
    const row = await addAlert(sample());
    expect(row.id).toMatch(/^a-/);
    expect(row.fired_count).toBe(0);
    expect(row.active).toBe(true);
    expect(row.created_at).toBeTruthy();
  });

  it("loadAlerts returns the most recent first", async () => {
    await addAlert(sample());
    await addAlert({ ...sample(), symbol: "MSFT" });
    const rows = await loadAlerts();
    expect(rows.map((r) => r.symbol)).toEqual(["MSFT", "AAPL"]);
  });

  it("toggleAlert flips active flag", async () => {
    const a = await addAlert(sample());
    const next = await toggleAlert(a.id, false);
    expect(next.find((r) => r.id === a.id)?.active).toBe(false);
  });

  it("recordFire bumps fired_count and stamps last_fired_at", async () => {
    const a = await addAlert(sample());
    const next = await recordFire(a.id);
    const r = next.find((x) => x.id === a.id)!;
    expect(r.fired_count).toBe(1);
    expect(r.last_fired_at).toBeTruthy();
  });

  it("deleteAlert removes by id", async () => {
    const a = await addAlert(sample());
    await addAlert({ ...sample(), symbol: "TSLA" });
    const next = await deleteAlert(a.id);
    expect(next.map((r) => r.symbol)).toEqual(["TSLA"]);
  });
});
