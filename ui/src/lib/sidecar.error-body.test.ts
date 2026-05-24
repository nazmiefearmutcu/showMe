/**
 * Regression — audit S2 (CRITICAL, cross-cutting).
 *
 * `sidecarFetch` used to throw `${path}: ${status} ${statusText}` and discard
 * the response body. Every form pane (OrderTicket, BOT, STRA, CONN, ALRT,
 * TMPL) saw the meaningless "422 Unprocessable Entity" instead of the
 * pydantic validation message backend produced.
 *
 * These tests pin the contract: on non-OK, sidecarFetch attaches
 *   - err.status (number)
 *   - err.detail (raw parsed JSON detail OR string)
 *   - err.path  (request path, for downstream logging)
 * AND the message text includes the human-readable detail.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// We need a real `loadSidecarAuthToken` path; mock at the module level so
// `waitForSidecarReady` resolves and the fetch path runs.
vi.mock("./tauri", () => ({
  invoke: vi.fn(),
  isInTauri: () => false,
  listen: vi.fn(),
}));

import {
  sidecarFetch,
  isSidecarError,
  type SidecarError,
} from "./sidecar";

const origFetch = globalThis.fetch;

function mockFetch(handler: (input: RequestInfo | URL) => Response): void {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
    handler(input),
  ) as unknown as typeof fetch;
}

beforeEach(() => {
  // First call is the /api/health probe waitForSidecarReady fires; then the
  // real request. We override per-test so each test owns the body shape.
  mockFetch(() => new Response("{}", { status: 200 }));
});

afterEach(() => {
  globalThis.fetch = origFetch;
});

async function expectThrow<T = unknown>(p: Promise<T>): Promise<unknown> {
  try {
    await p;
  } catch (err) {
    return err;
  }
  throw new Error("expected promise to reject");
}

describe("sidecarFetch error body preservation (audit S2)", () => {
  it("preserves pydantic-style `detail: string` from a 422", async () => {
    // health probe (OK) then the real call (422 with detail)
    let nthCall = 0;
    mockFetch((input) => {
      nthCall += 1;
      if (typeof input === "string" && input.endsWith("/api/health")) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(
        JSON.stringify({ detail: "field 'symbol' is required" }),
        { status: 422, statusText: "Unprocessable Entity" },
      );
    });

    const err = (await expectThrow(
      sidecarFetch("/api/exchange/credentials", { method: "POST" }),
    )) as SidecarError;

    expect(isSidecarError(err)).toBe(true);
    expect(err.status).toBe(422);
    expect(err.detail).toBe("field 'symbol' is required");
    expect(err.path).toBe("/api/exchange/credentials");
    expect(err.message).toContain("422");
    expect(err.message).toContain("field 'symbol' is required");
    expect(nthCall).toBeGreaterThanOrEqual(2);
  });

  it("preserves pydantic-style `detail: [{msg, loc, type}, ...]` flattened", async () => {
    mockFetch((input) => {
      if (typeof input === "string" && input.endsWith("/api/health")) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "symbol"], msg: "must not be blank", type: "value_error" },
            { loc: ["body", "side"], msg: "must be buy or sell", type: "value_error" },
          ],
        }),
        { status: 422, statusText: "Unprocessable Entity" },
      );
    });

    const err = (await expectThrow(
      sidecarFetch("/api/trading/order", { method: "POST" }),
    )) as SidecarError;

    expect(err.status).toBe(422);
    expect(Array.isArray(err.detail)).toBe(true);
    expect(err.message).toContain("must not be blank");
    expect(err.message).toContain("must be buy or sell");
  });

  it("falls through with raw text when body is not JSON", async () => {
    mockFetch((input) => {
      if (typeof input === "string" && input.endsWith("/api/health")) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response("plain text crash", {
        status: 500,
        statusText: "Internal Server Error",
      });
    });

    const err = (await expectThrow(
      sidecarFetch("/api/something"),
    )) as SidecarError;

    expect(err.status).toBe(500);
    expect(err.detail).toBe("plain text crash");
    expect(err.message).toContain("plain text crash");
  });

  it("handles empty body gracefully", async () => {
    mockFetch((input) => {
      if (typeof input === "string" && input.endsWith("/api/health")) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response("", { status: 404, statusText: "Not Found" });
    });

    const err = (await expectThrow(
      sidecarFetch("/api/missing"),
    )) as SidecarError;

    expect(err.status).toBe(404);
    expect(err.detail).toBe("");
    // No " — " separator when detail is empty.
    expect(err.message).not.toContain(" — ");
  });

  it("attaches status/detail even on raw-JSON (no `detail` key) body", async () => {
    mockFetch((input) => {
      if (typeof input === "string" && input.endsWith("/api/health")) {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }
      return new Response(
        JSON.stringify({ error_code: "X1", hint: "retry later" }),
        { status: 503, statusText: "Service Unavailable" },
      );
    });

    const err = (await expectThrow(
      sidecarFetch("/api/raw"),
    )) as SidecarError;

    expect(err.status).toBe(503);
    expect(err.detail).toEqual({ error_code: "X1", hint: "retry later" });
  });
});
