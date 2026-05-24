/**
 * Sidecar HTTP client — talks to the Python backend on its discovered port.
 *
 * Outside Tauri (vite preview / browser dev) we fall back to localhost:8765
 * so designers can still wire components to a hand-started ShowMe instance.
 */
import { useAppStore } from "./store";
import { invoke, isInTauri, listen } from "./tauri";

let _port: number | null = null;
let _listenStarted = false;
const subs = new Set<(port: number) => void>();

// Auth token captured at sidecar boot. The Tauri shell exposes it via the
// `sidecar_auth_token` invoke command and republishes on respawn through the
// `sidecar:auth_token` event. Backend rejects /api/* requests (except
// /api/health and /api/x/health) without a matching X-ShowMe-Token header.
// See ARCH-05 P2 in the quality audit.
let _authToken: string | null = null;
let _authTokenListenStarted = false;

function publishPort(port: number) {
  _port = port;
  useAppStore.getState().setSidecarPort(port);
  subs.forEach((s) => s(port));
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function rejectAfter(ms: number, message: string): Promise<never> {
  return new Promise((_, reject) => {
    window.setTimeout(() => reject(new Error(message)), ms);
  });
}

function timeoutSignal(timeoutMs: number): { signal: AbortSignal; cancel: () => void } {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  return {
    signal: controller.signal,
    cancel: () => window.clearTimeout(timer),
  };
}

async function readPortSnapshot(): Promise<number | null> {
  try {
    const { port } = await invoke<{ port: number | null }>("sidecar_port");
    if (port) publishPort(port);
    return port ?? null;
  } catch (err) {
    console.warn("sidecar_port invoke failed", err);
    return null;
  }
}

async function ensureSidecarPortListener() {
  if (_listenStarted || !isInTauri()) return;
  _listenStarted = true;
  try {
    await listen<number>("sidecar:port", (e) => {
      if (e.payload) publishPort(e.payload);
    });
  } catch (err) {
    _listenStarted = false;
    console.warn("sidecar:port listen failed", err);
  }
}

async function ensureSidecarAuthTokenListener() {
  if (_authTokenListenStarted || !isInTauri()) return;
  _authTokenListenStarted = true;
  try {
    await listen<string | null>("sidecar:auth_token", (e) => {
      // Tauri republishes on respawn so the renderer always carries the
      // current token. Null payloads clear the cache.
      _authToken = e.payload ?? null;
    });
  } catch (err) {
    _authTokenListenStarted = false;
    console.warn("sidecar:auth_token listen failed", err);
  }
}

/**
 * Fetch (and memoize) the current sidecar auth token from the Tauri shell.
 * Returns null when running outside Tauri or when the shell has not produced
 * a token yet. Subsequent calls hit the cache; respawn refresh comes from
 * the `sidecar:auth_token` event.
 */
export async function loadSidecarAuthToken(): Promise<string | null> {
  if (!isInTauri()) {
    // Browser-mode dev fallback: if the operator started a dev sidecar with
    // `SHOWME_AUTH_TOKEN=<x>` and stashed the same string in
    // `localStorage["showme.devAuthToken"]`, attach it to outgoing fetches.
    // Tauri builds never read this — they go through the invoke path below.
    if (typeof window !== "undefined") {
      const fromLs = window.localStorage.getItem("showme.devAuthToken");
      if (fromLs) return fromLs;
    }
    return null;
  }
  await ensureSidecarAuthTokenListener();
  if (_authToken) return _authToken;
  try {
    const t = await invoke<string | null>("sidecar_auth_token");
    if (t) _authToken = t;
    return _authToken;
  } catch (err) {
    console.warn("sidecar_auth_token invoke failed", err);
    return null;
  }
}

export async function bootstrapSidecarPort(timeoutMs = 45_000): Promise<number | null> {
  if (!isInTauri()) return null;
  await ensureSidecarPortListener();
  // Install the auth-token listener early so respawn events don't slip past
  // before the first protected fetch fires.
  await ensureSidecarAuthTokenListener();
  const deadline = Date.now() + timeoutMs;
  do {
    const port = await readPortSnapshot();
    if (port) return port;
    await sleep(150);
  } while (!_port && Date.now() < deadline);
  return _port;
}

export function onSidecarPort(cb: (port: number) => void): () => void {
  subs.add(cb);
  if (_port) cb(_port);
  return () => subs.delete(cb);
}

export function sidecarBaseUrl(): string {
  if (_port) return `http://127.0.0.1:${_port}`;
  if (isInTauri()) return "http://127.0.0.1:0";
  const storedPort = browserStoredSidecarPort();
  if (storedPort) {
    publishPort(storedPort);
    return `http://127.0.0.1:${storedPort}`;
  }
  // Fallback for browser-only dev.
  publishPort(8765);
  return "http://127.0.0.1:8765";
}

export function sidecarWsUrl(): string {
  if (_port) return `ws://127.0.0.1:${_port}`;
  if (isInTauri()) return "ws://127.0.0.1:0";
  const storedPort = browserStoredSidecarPort();
  if (storedPort) {
    publishPort(storedPort);
    return `ws://127.0.0.1:${storedPort}`;
  }
  publishPort(8765);
  return "ws://127.0.0.1:8765";
}

function browserStoredSidecarPort(): number | null {
  if (isInTauri() || typeof window === "undefined") return null;
  const raw = window.localStorage.getItem("showme.sidecarPort");
  const port = raw ? Number(raw) : NaN;
  return Number.isInteger(port) && port > 0 ? port : null;
}

export async function waitForSidecarReady(timeoutMs = 12_000): Promise<string> {
  if (isInTauri() && !_port) {
    await bootstrapSidecarPort(Math.min(timeoutMs, 45_000));
  }
  if (isInTauri() && !_port) {
    useAppStore.getState().setSidecarStatus("booting");
    throw new Error("ShowMe native sidecar port has not been published yet");
  }
  const deadline = Date.now() + timeoutMs;
  let lastError = "";
  do {
    const base = sidecarBaseUrl();
    try {
      const res = await fetch(`${base}/api/health`);
      if (res.ok) {
        useAppStore.getState().setSidecarStatus("healthy");
        return base;
      }
      lastError = `${res.status} ${res.statusText}`;
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err);
    }
    await sleep(250);
  } while (Date.now() < deadline);
  useAppStore.getState().setSidecarStatus(_port ? "crashed" : "booting");
  throw new Error(`ShowMe sidecar unavailable at ${sidecarBaseUrl()}: ${lastError}`);
}

export async function sidecarFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base = path === "/api/health" ? sidecarBaseUrl() : await waitForSidecarReady();
  const url = base + path;
  // Attach the per-process auth token to every protected request. Health
  // probes (/api/health, /api/x/health) are open by contract; everything
  // else needs X-ShowMe-Token to clear the backend's middleware. See ARCH-05.
  const headers = new Headers(init?.headers || {});
  const token = await loadSidecarAuthToken();
  if (token && !headers.has("X-ShowMe-Token")) {
    headers.set("X-ShowMe-Token", token);
  }
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    // CRITICAL FIX (audit S2): preserve FastAPI's `detail` field instead of
    // discarding the response body. Form panes (OrderTicket / BOT / STRA /
    // CONN / ALRT / TMPL) read `(err as SidecarError).detail` to render
    // human-readable 422 validation errors instead of the meaningless
    // "422 Unprocessable Entity". The body may be plain JSON `{detail: ...}`,
    // a list of validation errors, or a raw string — handle all three.
    let detail: unknown = "";
    let detailText = "";
    try {
      const text = await res.text();
      if (text) {
        try {
          const parsed = JSON.parse(text);
          detail =
            parsed && typeof parsed === "object" && "detail" in parsed
              ? (parsed as { detail: unknown }).detail
              : parsed;
          // Stringify structured details for the Error message text. Pydantic
          // typically returns `[{loc, msg, type}, ...]`; flatten to msg list.
          if (Array.isArray(detail)) {
            detailText = detail
              .map((item) => {
                if (item && typeof item === "object" && "msg" in item) {
                  return String((item as { msg: unknown }).msg ?? "");
                }
                return typeof item === "string" ? item : JSON.stringify(item);
              })
              .filter(Boolean)
              .join("; ");
          } else if (typeof detail === "string") {
            detailText = detail;
          } else if (detail != null) {
            detailText = JSON.stringify(detail);
          }
        } catch {
          // Non-JSON body — surface as-is.
          detail = text;
          detailText = text;
        }
      }
    } catch {
      // network read failed — fall through with empty detail
    }
    const message = `${path}: ${res.status} ${res.statusText}${detailText ? " — " + detailText : ""}`;
    const err = new Error(message) as Error & { status?: number; detail?: unknown; path?: string };
    err.status = res.status;
    err.detail = detail;
    err.path = path;
    throw err;
  }
  useAppStore.getState().setSidecarStatus("healthy");
  return (await res.json()) as T;
}

/** Type-safe getter for the structured error metadata `sidecarFetch` attaches. */
export interface SidecarError extends Error {
  status?: number;
  detail?: unknown;
  path?: string;
}

export function isSidecarError(err: unknown): err is SidecarError {
  return (
    err instanceof Error &&
    ("status" in err || "detail" in err || "path" in err)
  );
}

export interface SidecarHealth {
  ok: boolean;
  engine?: { engine_root: string | null; engine_attached: boolean };
}

export async function fetchHealth(): Promise<SidecarHealth> {
  return sidecarFetch<SidecarHealth>("/api/health");
}

export interface FunctionEntry {
  code: string;
  name: string;
  category: string;
  description: string;
  asset_classes?: string[];
  usage?: {
    purpose?: string;
    scope?: string;
    inputs?: string[];
    steps?: string[];
    example?: unknown;
    asset_classes?: string[];
  };
}

export async function fetchFunctionIndex(timeoutMs = 6_000): Promise<FunctionEntry[]> {
  const { signal, cancel } = timeoutSignal(timeoutMs);
  try {
    return await Promise.race([
      sidecarFetch<FunctionEntry[]>("/api/function-index", { signal }),
      rejectAfter(timeoutMs + 250, `/api/function-index timed out after ${timeoutMs}ms`),
    ]);
  } finally {
    cancel();
  }
}

export interface SidecarInfo {
  version: string;
  python: string;
  platform: string;
  engine?: { engine_root: string | null; engine_attached: boolean };
}

export async function fetchSidecarInfo(): Promise<SidecarInfo> {
  return sidecarFetch<SidecarInfo>("/api/sidecar/info");
}

export interface StreamChannelStats {
  symbol: string;
  subscribers: number;
  last_price: number | null;
  source: string | null;
}

export interface StreamStats {
  channels: StreamChannelStats[];
}

export async function fetchStreamStats(): Promise<StreamStats> {
  return sidecarFetch<StreamStats>("/api/stream/stats");
}
