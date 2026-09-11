/**
 * L3 — universal security context store.
 *
 * Pins the frozen contract: `useSecurityContext()` mirrors the imperative
 * `setActiveSecurity()` for non-React callers (command line / palette), the
 * value is pushed from the focused pane by the Titlebar, and repeated
 * value-equal pushes are deduped so the desk doesn't re-render in a loop.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { setActiveSecurity, useSecurityContext, type ActiveSecurity } from "./security-context";

const AAPL: ActiveSecurity = { symbol: "AAPL", label: "US Equity", assetClass: "EQUITY" };
const BTC: ActiveSecurity = { symbol: "BTCUSDT", label: "Crypto", assetClass: "CRYPTO" };

beforeEach(() => {
  setActiveSecurity(null);
});

describe("security-context", () => {
  it("starts empty — no security in context", () => {
    const { result } = renderHook(() => useSecurityContext());
    expect(result.current.active).toBeNull();
  });

  it("imperative setter updates hook consumers (non-React callers)", () => {
    const { result } = renderHook(() => useSecurityContext());
    act(() => setActiveSecurity(AAPL));
    expect(result.current.active).toEqual(AAPL);
  });

  it("hook setter and imperative setter address the same store", () => {
    const { result } = renderHook(() => useSecurityContext());
    act(() => result.current.setActive(BTC));
    expect(result.current.active).toEqual(BTC);
    const second = renderHook(() => useSecurityContext());
    expect(second.result.current.active).toEqual(BTC);
  });

  it("clearing via setActive(null) empties the context", () => {
    const { result } = renderHook(() => useSecurityContext());
    act(() => setActiveSecurity(AAPL));
    act(() => result.current.setActive(null));
    expect(result.current.active).toBeNull();
  });

  it("value-equal pushes do not notify subscribers (loop guard)", () => {
    let renders = 0;
    const { result } = renderHook(() => {
      renders += 1;
      return useSecurityContext();
    });
    act(() => setActiveSecurity({ ...AAPL }));
    const afterFirst = renders;
    act(() => setActiveSecurity({ ...AAPL }));
    expect(result.current.active).toEqual(AAPL);
    expect(renders).toBe(afterFirst);
  });
});
