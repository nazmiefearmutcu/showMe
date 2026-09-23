/**
 * runMisScan — caller-owned deadline regression (2026-09-17).
 *
 * A full sweep runs for minutes; the POST used to inherit sidecarFetch's
 * 15 s default and died with "request timed out after 15000ms" while the
 * backend kept scanning. runMisScan must forward the caller's AbortSignal
 * so MIS.tsx can set its own (long) deadline.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { runMisScan } from "./mis";

const sidecarFetchMock = vi.fn();
vi.mock("./sidecar", () => ({
  sidecarFetch: (...args: unknown[]) => sidecarFetchMock(...args),
}));

beforeEach(() => {
  sidecarFetchMock.mockReset();
  sidecarFetchMock.mockResolvedValue({ rows: [] });
});

describe("runMisScan — caller-owned deadline", () => {
  it("forwards the caller signal to sidecarFetch (bypasses the 15s default)", async () => {
    const ac = new AbortController();
    await runMisScan({ markets: ["CRYPTO"] }, { signal: ac.signal });
    expect(sidecarFetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = sidecarFetchMock.mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(path).toBe("/api/mis/scan");
    expect(init.method).toBe("POST");
    expect(init.signal).toBe(ac.signal);
  });

  it("still works when no signal is supplied", async () => {
    await runMisScan({ markets: ["CRYPTO"] });
    const init = sidecarFetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBeUndefined();
  });
});
