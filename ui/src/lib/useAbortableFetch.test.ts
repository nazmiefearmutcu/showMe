/**
 * Bundle D / ABORT-01 — useAbortableFetch contract.
 *
 *  - Aborts in-flight request on unmount.
 *  - Aborts previous request when a new run() is called.
 *  - `isMounted()` returns false post-unmount.
 *  - `cancel()` aborts without unmounting.
 */
import { renderHook, act } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useAbortableFetch } from "./useAbortableFetch";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAbortableFetch", () => {
  it("aborts the in-flight request on unmount", async () => {
    const { result, unmount } = renderHook(() => useAbortableFetch());
    let observedSignal: AbortSignal | null = null;
    const d = deferred<string>();
    const p = result.current.run<string>((signal) => {
      observedSignal = signal;
      signal.addEventListener("abort", () => d.reject(new DOMException("aborted", "AbortError")));
      return d.promise;
    });
    expect(observedSignal!.aborted).toBe(false);
    unmount();
    expect(observedSignal!.aborted).toBe(true);
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });

  it("cancels a previous run when a new one starts", () => {
    const { result } = renderHook(() => useAbortableFetch());
    let firstSignal: AbortSignal | null = null;
    let secondSignal: AbortSignal | null = null;
    act(() => {
      void result.current.run((signal) => {
        firstSignal = signal;
        return new Promise(() => {});
      });
    });
    expect(firstSignal!.aborted).toBe(false);
    act(() => {
      void result.current.run((signal) => {
        secondSignal = signal;
        return new Promise(() => {});
      });
    });
    expect(firstSignal!.aborted).toBe(true);
    expect(secondSignal!.aborted).toBe(false);
  });

  it("isMounted() returns false after unmount", () => {
    const { result, unmount } = renderHook(() => useAbortableFetch());
    expect(result.current.isMounted()).toBe(true);
    unmount();
    expect(result.current.isMounted()).toBe(false);
  });

  it("cancel() aborts the in-flight request without unmounting", () => {
    const { result } = renderHook(() => useAbortableFetch());
    let observedSignal: AbortSignal | null = null;
    act(() => {
      void result.current.run((signal) => {
        observedSignal = signal;
        return new Promise(() => {});
      });
    });
    expect(observedSignal!.aborted).toBe(false);
    act(() => {
      result.current.cancel();
    });
    expect(observedSignal!.aborted).toBe(true);
    expect(result.current.isMounted()).toBe(true);
  });
});
