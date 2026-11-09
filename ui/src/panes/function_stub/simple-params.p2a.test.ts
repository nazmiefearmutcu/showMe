import { describe, expect, it } from "vitest";
import { simpleParamSpecsForFunction } from "./simple-params";

/**
 * ONCH serves Bitcoin only on the keyless path (onch.py _SUPPORTED_CHAINS);
 * the chain hint must not advertise ETH, which returns an input_error.
 */
describe("simple-params ONCH chain hint", () => {
  it("advertises only BTC as the served chain", () => {
    const chain = simpleParamSpecsForFunction("ONCH").find((s) => s.key === "chain");
    expect(chain).toBeDefined();
    expect(chain!.hint).toBe("BTC");
  });
});
