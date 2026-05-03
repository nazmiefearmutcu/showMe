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

export async function bootstrapSidecarPort(timeoutMs = 45_000): Promise<number | null> {
  if (!isInTauri()) return null;
  await ensureSidecarPortListener();
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
  if (storedPort) return `http://127.0.0.1:${storedPort}`;
  // Fallback for browser-only dev.
  return "http://127.0.0.1:8765";
}

export function sidecarWsUrl(): string {
  if (_port) return `ws://127.0.0.1:${_port}`;
  if (isInTauri()) return "ws://127.0.0.1:0";
  const storedPort = browserStoredSidecarPort();
  if (storedPort) return `ws://127.0.0.1:${storedPort}`;
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
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${path}: ${res.status} ${res.statusText}`);
  useAppStore.getState().setSidecarStatus("healthy");
  return (await res.json()) as T;
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
