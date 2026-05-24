/**
 * BugHunt 2026-05-24 — Theme 3, Bug #3 (HIGH).
 *
 * `findKeyMatching` used to lowercase + strip every non-[a-z0-9] char
 * before comparing. That collapses:
 *   - Greek letter glyphs (Δ, Γ, Θ, ν, ρ) → "" — every Greek column was
 *     indistinguishable, so Δ/Γ/Θ ended up empty for every option chain.
 *   - `IV` ↔ `Iv` ↔ ` IV `: normalises to "iv" (fine), but a backend
 *     field named `Implied Vol` would only match if the template column
 *     was literally `Implied Vol` too — small shorthand mismatch silently
 *     dropped the value.
 *   - `Vol` and `Volume` collide with anything else 3-letter, and the
 *     pre-fix matcher would put the IV decimal in the `Vol` column when
 *     the live payload happened to have the IV key sorted earlier.
 *
 * The fix adds `normalizeColumnKey`, a whitelist-driven mapper that
 * preserves Greek letters and treats `IV`/`Δ`/`Γ`/`OI`/`Vol`/`OpenInt`
 * as distinct stable identifiers.
 */
import { describe, expect, it } from "vitest";
import { mergeLivePayload, normalizeColumnKey } from "../TemplateRenderer";
import { getMockTemplate } from "../mock-data";

describe("normalizeColumnKey", () => {
  it("maps Greek letter glyphs to their lowercase English names", () => {
    expect(normalizeColumnKey("Δ")).toBe("delta");
    expect(normalizeColumnKey("Γ")).toBe("gamma");
    expect(normalizeColumnKey("Θ")).toBe("theta");
    expect(normalizeColumnKey("ν")).toBe("vega");
    expect(normalizeColumnKey("ρ")).toBe("rho");
    expect(normalizeColumnKey("Λ")).toBe("lambda");
  });

  it("collapses common Latin shorthand into canonical ids", () => {
    expect(normalizeColumnKey("IV")).toBe("iv");
    expect(normalizeColumnKey("iv")).toBe("iv");
    expect(normalizeColumnKey("Implied Vol")).toBe("iv");
    expect(normalizeColumnKey("ImpliedVol")).toBe("iv");
    expect(normalizeColumnKey("OI")).toBe("open_interest");
    expect(normalizeColumnKey("Open Interest")).toBe("open_interest");
    expect(normalizeColumnKey("OpenInt")).toBe("open_interest");
    expect(normalizeColumnKey("Vol")).toBe("volume");
    expect(normalizeColumnKey("Volume")).toBe("volume");
    expect(normalizeColumnKey("Px")).toBe("price");
    expect(normalizeColumnKey("Price")).toBe("price");
  });

  it("keeps IV and Vol distinct (the original collision bug)", () => {
    expect(normalizeColumnKey("IV")).not.toBe(normalizeColumnKey("Vol"));
    expect(normalizeColumnKey("iv")).not.toBe(normalizeColumnKey("volume"));
  });

  it("falls back to alphanumeric-stripped lowercase for unknown labels", () => {
    expect(normalizeColumnKey("Total Return")).toBe("totalreturn");
    expect(normalizeColumnKey("Last Close")).toBe("lastclose");
    expect(normalizeColumnKey("β SPX")).toBe("βspx");
  });

  it("returns empty for blank/whitespace inputs", () => {
    expect(normalizeColumnKey("")).toBe("");
    expect(normalizeColumnKey("   ")).toBe("");
  });
});

describe("mergeLivePayload — option-chain Greek + IV column alignment", () => {
  it("OMON: Δ / Γ / IV / OI / Vol all land in their template columns", () => {
    const tpl = getMockTemplate("OMON")!;
    expect(tpl.tableCols).toEqual(["Strike", "IV", "Δ", "Γ", "Vol", "OI"]);
    const merged = mergeLivePayload(tpl, "OMON", {
      rows: [
        {
          Strike: 300,
          IV: "21.4%",
          delta: 0.55,
          gamma: 0.012,
          volume: "9K",
          open_interest: "42K",
        },
      ],
    });
    const row = merged.tableRows![0];
    expect(row.Strike).toBe("300");
    expect(row.IV).toBe("21.4%");
    // The Δ / Γ template columns must pick up `delta` / `gamma` keys.
    expect(row["Δ"]).toBe("0.55");
    expect(row["Γ"]).toBe("0.012");
    // Vol column must NOT receive the IV decimal — pre-fix bug.
    expect(row.Vol).toBe("9K");
    expect(row.OI).toBe("42K");
  });

  it("OMON: backend that returns literal Greek-letter keys also resolves", () => {
    const tpl = getMockTemplate("OMON")!;
    const merged = mergeLivePayload(tpl, "OMON", {
      rows: [
        { Strike: 305, IV: "20.8%", "Δ": 0.48, "Γ": 0.014, Vol: "11K", OI: "62K" },
      ],
    });
    const row = merged.tableRows![0];
    expect(row["Δ"]).toBe("0.48");
    expect(row["Γ"]).toBe("0.014");
    expect(row.IV).toBe("20.8%");
    expect(row.Vol).toBe("11K");
  });

  it("OMON: `OpenInt`/`Implied Vol` shorthand both resolve via whitelist", () => {
    const tpl = getMockTemplate("OMON")!;
    const merged = mergeLivePayload(tpl, "OMON", {
      rows: [
        {
          Strike: 310,
          "Implied Vol": "19.6%",
          delta: 0.41,
          gamma: 0.016,
          volume: "13K",
          OpenInt: "84K",
        },
      ],
    });
    const row = merged.tableRows![0];
    expect(row.IV).toBe("19.6%");
    expect(row.OI).toBe("84K");
    expect(row.Vol).toBe("13K");
  });
});
