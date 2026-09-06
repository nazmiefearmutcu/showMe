/**
 * FLW pane — wiring + data-honesty tests.
 *
 * The FlowMap library (`@/functions/flowmap`) and the sidecar transport are
 * mocked; the tests pin the pane contract:
 *
 *  - a crypto symbol renders the PaneHeader + full-bleed canvas and wires
 *    `createFlowMap` with a `/ws/flowmap` URL carrying the sidecar token;
 *  - the status pill follows the library's `onStatus` (connecting → live) and
 *    the Hello capability line (depth mode + `history: reconstructed` badge);
 *  - a band change re-subscribes on the SAME handle (no session rebuild);
 *  - a non-crypto symbol shows the honest "crypto depth only" info state and
 *    NEVER calls `createFlowMap` (no fake heatmap, no synthetic fallback);
 *  - `destroy()` runs on unmount (StrictMode-safe teardown contract).
 */
import { cleanup, render, screen, waitFor, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/functions/flowmap", () => ({
  createFlowMap: vi.fn(() => ({ subscribe: vi.fn(), destroy: vi.fn() })),
}));

vi.mock("@/lib/sidecar", () => ({
  sidecarWsUrl: () => "ws://127.0.0.1:8765",
  loadSidecarAuthToken: vi.fn(async () => "tok"),
  onSidecarPort: vi.fn(() => () => undefined),
}));

import { createFlowMap, type FlowMapOptions, type FlowMapStatus } from "@/functions/flowmap";
import { FLWPane } from "./FLW";

const createFlowMapMock = vi.mocked(createFlowMap);

function firstCallOptions(): {
  opts: FlowMapOptions;
  onStatus: (status: FlowMapStatus) => void;
} {
  expect(createFlowMapMock).toHaveBeenCalled();
  const opts = createFlowMapMock.mock.calls[0][1];
  const onStatus = opts.onStatus;
  if (!onStatus) throw new Error("expected onStatus to be wired");
  return { opts, onStatus };
}

async function renderAndWaitForSession(props: { code: string; symbol?: string }) {
  const view = render(<FLWPane {...props} />);
  await waitFor(() => expect(createFlowMapMock).toHaveBeenCalled());
  return view;
}

beforeEach(() => {
  // usePersistentOption + recent-symbols both read localStorage — keep every
  // test on pristine defaults (band "wide", default symbol BTCUSDT).
  window.localStorage.clear();
  createFlowMapMock.mockClear();
});

afterEach(() => cleanup());

describe("FLW pane — session wiring", () => {
  it("renders header + canvas and wires createFlowMap with the sidecar flowmap URL", async () => {
    const { container } = await renderAndWaitForSession({ code: "FLW", symbol: "BTCUSDT" });
    expect(screen.getByText("FlowMap")).toBeInTheDocument();
    expect(container.querySelector("canvas")).not.toBeNull();
    const { opts } = firstCallOptions();
    expect(opts.wsUrl.startsWith("ws://127.0.0.1:8765/ws/flowmap")).toBe(true);
    expect(opts.wsUrl).toContain("token=tok");
    expect(opts.target).toEqual({ market: "crypto", symbol: "BTCUSDT", band: "wide" });
  });

  it("falls back to the crypto default symbol (BTCUSDT) when none is given", async () => {
    await renderAndWaitForSession({ code: "FLW" });
    expect(firstCallOptions().opts.target.symbol).toBe("BTCUSDT");
  });

  it("calls destroy on the handle when the pane unmounts", async () => {
    const { unmount } = await renderAndWaitForSession({ code: "FLW", symbol: "BTCUSDT" });
    const handle = createFlowMapMock.mock.results[0].value;
    expect(handle.destroy).not.toHaveBeenCalled();
    unmount();
    expect(handle.destroy).toHaveBeenCalledTimes(1);
  });
});

describe("FLW pane — status honesty", () => {
  it("follows onStatus from connecting to live and surfaces the capability line", async () => {
    await renderAndWaitForSession({ code: "FLW", symbol: "ETHUSDT" });
    const { onStatus } = firstCallOptions();

    act(() => onStatus({ conn: "connecting", webgl: true }));
    expect(screen.getByText("connecting")).toBeInTheDocument();

    act(() =>
      onStatus({
        conn: "live",
        webgl: true,
        capability: { depth: "L2", history: "reconstructed" },
        latencyMs: 42,
      }),
    );
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.getByText("depth L2")).toBeInTheDocument();
    expect(screen.getByText(/history: reconstructed/i)).toBeInTheDocument();
    expect(screen.getByText("42 ms")).toBeInTheDocument();
  });

  it("renders the WebGL2 fallback instead of a canvas when webgl is unavailable", async () => {
    const { container } = await renderAndWaitForSession({ code: "FLW", symbol: "BTCUSDT" });
    const { onStatus } = firstCallOptions();
    act(() => onStatus({ conn: "error", webgl: false }));
    expect(screen.getByText(/WebGL2 unavailable/i)).toBeInTheDocument();
    expect(container.querySelector("canvas")).toBeNull();
  });
});

describe("FLW pane — band control", () => {
  it("re-subscribes the SAME handle with the new band without rebuilding the session", async () => {
    await renderAndWaitForSession({ code: "FLW", symbol: "ETHUSDT" });
    const handle = createFlowMapMock.mock.results[0].value;
    expect(createFlowMapMock).toHaveBeenCalledTimes(1);
    expect(handle.subscribe).not.toHaveBeenCalled();

    act(() => {
      screen.getByRole("button", { name: "deep" }).click();
    });

    expect(handle.subscribe).toHaveBeenCalledTimes(1);
    expect(handle.subscribe).toHaveBeenCalledWith({
      market: "crypto",
      symbol: "ETHUSDT",
      band: "deep",
    });
    expect(createFlowMapMock).toHaveBeenCalledTimes(1);
  });
});

describe("FLW pane — crypto-only honesty", () => {
  it("shows the crypto-depth-only info state and never wires the library for a non-crypto symbol", async () => {
    const { container } = render(<FLWPane code="FLW" symbol="AAPL" />);
    expect(screen.getByText(/Crypto depth only/i)).toBeInTheDocument();
    expect(container.querySelector("canvas")).toBeNull();
    // Give every pending microtask a chance — createFlowMap must stay cold.
    await waitFor(() => expect(createFlowMapMock).not.toHaveBeenCalled());
    expect(createFlowMapMock).not.toHaveBeenCalled();
  });
});
