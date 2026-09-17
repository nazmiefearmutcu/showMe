/**
 * Regression — stale browser sidecar port (CRASHED :<dead-port> lock-in).
 *
 * Browser-mode dev reads `localStorage["showme.sidecarPort"]` on boot. A
 * leftover entry from an earlier session pinned the whole UI to a dead port:
 * health probes kept failing, every pane stayed DEMO/CRASHED, and a healthy
 * sidecar on the 8765 dev default was never contacted.
 *
 * Contract pinned here:
 *   - stored port dead + default alive  -> stale key dropped, base = 8765,
 *   - stored port alive                 -> honored, key kept,
 *   - nothing alive                     -> rejects, key kept (no data loss).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./tauri", () => ({
  invoke: vi.fn(),
  isInTauri: () => false,
  listen: vi.fn(),
}));

const origFetch = globalThis.fetch;
const STORED_KEY = "showme.sidecarPort";

function installFetchMock(
  impl: (input: RequestInfo | URL) => Promise<Response>,
): void {
  globalThis.fetch = vi.fn(impl) as unknown as typeof fetch;
}

function healthOk(): Response {
  return new Response(JSON.stringify({ ok: true }), { status: 200 });
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  globalThis.fetch = origFetch;
  vi.resetModules();
});

describe("browser stored-port self-heal", () => {
  it("drops a stale stored port and falls back to the dev default", async () => {
    window.localStorage.setItem(STORED_KEY, "8795");
    installFetchMock((input) => {
      const url = String(input);
      if (url.includes(":8795")) {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      if (url.endsWith("/api/health")) return Promise.resolve(healthOk());
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    const { waitForSidecarReady } = await import("./sidecar");
    const base = await waitForSidecarReady(3_000);

    expect(base).toBe("http://127.0.0.1:8765");
    expect(window.localStorage.getItem(STORED_KEY)).toBeNull();
  });

  it("honors a stored port that is actually alive", async () => {
    window.localStorage.setItem(STORED_KEY, "8795");
    installFetchMock((input) => {
      const url = String(input);
      if (url.endsWith("/api/health")) return Promise.resolve(healthOk());
      return Promise.resolve(new Response("{}", { status: 200 }));
    });

    const { waitForSidecarReady } = await import("./sidecar");
    const base = await waitForSidecarReady(3_000);

    expect(base).toBe("http://127.0.0.1:8795");
    expect(window.localStorage.getItem(STORED_KEY)).toBe("8795");
  });

  it("keeps the stored port and reports failure when nothing answers", async () => {
    window.localStorage.setItem(STORED_KEY, "8795");
    installFetchMock(() => Promise.reject(new TypeError("Failed to fetch")));

    const { waitForSidecarReady } = await import("./sidecar");
    await expect(waitForSidecarReady(300)).rejects.toThrow(
      /ShowMe sidecar unavailable/,
    );
    expect(window.localStorage.getItem(STORED_KEY)).toBe("8795");
  });
});
