import { useSyncExternalStore } from "react";
import type { FunctionEntry } from "./sidecar";
import { normalizeSymbolInput } from "./symbols";
import { safeReadLocal, safeWriteLocal } from "./safe-storage";

export type PinnedItemKind = "function" | "symbol" | "workspace";

export interface PinnedItem {
  id: string;
  kind: PinnedItemKind;
  code: string;
  label: string;
  meta: string;
  path: string;
  href: string;
}

export const PIN_DRAG_MIME = "application/x-showme-pin";

const KEY = "showme.pins.v1";
const MAX_PINNED = 24;

const DEFAULT_PINNED_ITEMS: PinnedItem[] = [
  makeItem({
    id: "symbol:AAPL:DES",
    kind: "symbol",
    code: "AAPL",
    label: "Apple Inc.",
    meta: "AAPL",
    path: "/symbol/AAPL/DES",
  }),
  makeItem({
    id: "symbol:NVDA:DES",
    kind: "symbol",
    code: "NVDA",
    label: "NVIDIA",
    meta: "NVDA",
    path: "/symbol/NVDA/DES",
  }),
  makeItem({
    id: "symbol:BTC:DES",
    kind: "symbol",
    code: "BTC",
    label: "Bitcoin",
    meta: "BTC",
    path: "/symbol/BTC/DES",
  }),
  makeItem({
    id: "symbol:SPX:DES",
    kind: "symbol",
    code: "SPX",
    label: "S&P 500",
    meta: "SPX",
    path: "/symbol/SPX/DES",
  }),
];

const listeners = new Set<() => void>();
let cache: PinnedItem[] | null = null;

function cloneDefaults(): PinnedItem[] {
  return DEFAULT_PINNED_ITEMS.map((item) => ({ ...item }));
}

function hrefFor(path: string): string {
  return path.startsWith("#") ? path : `#${path.startsWith("/") ? path : `/${path}`}`;
}

function normalizeKind(kind: unknown): PinnedItemKind {
  return kind === "symbol" || kind === "workspace" ? kind : "function";
}

function makeItem(item: Omit<PinnedItem, "href"> & { href?: string }): PinnedItem {
  return {
    ...item,
    code: item.code.toUpperCase(),
    href: item.href ?? hrefFor(item.path),
  };
}

function normalizeItem(value: unknown): PinnedItem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<PinnedItem>;
  const code = typeof raw.code === "string" ? raw.code.trim().toUpperCase() : "";
  const label = typeof raw.label === "string" ? raw.label.trim() : "";
  const meta = typeof raw.meta === "string" ? raw.meta.trim().toUpperCase() : code;
  const path = typeof raw.path === "string" ? raw.path.trim() : "";
  const kind = normalizeKind(raw.kind);
  const id =
    typeof raw.id === "string" && raw.id.trim()
      ? raw.id.trim()
      : `${kind}:${code}:${path}`;
  if (!code || !label || !path) return null;
  return makeItem({ id, kind, code, label, meta, path });
}

export function serializePinnedItem(item: PinnedItem): string {
  return JSON.stringify(normalizeItem(item));
}

export function parsePinnedItemPayload(value: string): PinnedItem | null {
  try {
    return normalizeItem(JSON.parse(value));
  } catch {
    return null;
  }
}

export function writePinnedDragData(dataTransfer: DataTransfer, item: PinnedItem): void {
  dataTransfer.effectAllowed = "copyMove";
  dataTransfer.setData(PIN_DRAG_MIME, serializePinnedItem(item));
  dataTransfer.setData("text/plain", item.label);
}

export function readPinnedDragData(dataTransfer: DataTransfer): PinnedItem | null {
  return parsePinnedItemPayload(dataTransfer.getData(PIN_DRAG_MIME));
}

function loadPinnedItems(): PinnedItem[] {
  if (typeof localStorage === "undefined") return cloneDefaults();
  const parsed = safeReadLocal<unknown[]>(KEY, [], {
    label: "Pins",
    validate: (v): v is unknown[] => Array.isArray(v),
  });
  if (parsed.length === 0) {
    // Missing or just-cleared corrupt blob — fall back to the seed list. The
    // safeReadLocal corruption-toast already fired if the blob was bad.
    return localStorage.getItem(KEY) ? [] : cloneDefaults();
  }
  const seen = new Set<string>();
  const out: PinnedItem[] = [];
  for (const value of parsed) {
    const item = normalizeItem(value);
    if (!item || seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
    if (out.length >= MAX_PINNED) break;
  }
  return out;
}

function readPinnedItems(): PinnedItem[] {
  if (!cache) cache = loadPinnedItems();
  return cache;
}

function emitPinnedChange(): void {
  for (const listener of listeners) listener();
}

function writePinnedItems(items: PinnedItem[]): void {
  const normalized = items
    .map((item) => normalizeItem(item))
    .filter((item): item is PinnedItem => Boolean(item))
    .slice(0, MAX_PINNED);
  cache = normalized;
  // HIGH FIX (audit S14): route through safeWriteLocal so QuotaExceededError
  // emits a single toast instead of silently failing. The in-memory cache
  // stays updated even if persistence fails so the active session keeps
  // showing the user's pins.
  safeWriteLocal(KEY, normalized, { label: "Pinned items" });
  emitPinnedChange();
}

// HIGH FIX (audit S9): the previous implementation added one window-level
// `storage` listener per subscriber — 24 mounted panes meant 24 listeners
// each parsing every storage event, each calling its captured `listener()`
// callback even though the cache invalidation only needs to happen once.
// Single module-level listener + fan-out via the existing `listeners` set.
let _storageListenerInstalled = false;
function _onStorageEvent(event: StorageEvent): void {
  if (event.key !== KEY) return;
  cache = null;
  for (const listener of listeners) listener();
}

function _ensureStorageListener(): void {
  if (_storageListenerInstalled) return;
  if (typeof window === "undefined") return;
  window.addEventListener("storage", _onStorageEvent);
  _storageListenerInstalled = true;
}

function _maybeRemoveStorageListener(): void {
  if (!_storageListenerInstalled) return;
  if (listeners.size > 0) return;
  if (typeof window === "undefined") return;
  window.removeEventListener("storage", _onStorageEvent);
  _storageListenerInstalled = false;
}

function subscribePinned(listener: () => void): () => void {
  listeners.add(listener);
  _ensureStorageListener();
  return () => {
    listeners.delete(listener);
    _maybeRemoveStorageListener();
  };
}

export function listPinnedItems(): PinnedItem[] {
  return readPinnedItems().map((item) => ({ ...item }));
}

export function usePinnedItems(): PinnedItem[] {
  return useSyncExternalStore(subscribePinned, readPinnedItems, readPinnedItems);
}

export function isPinned(id: string): boolean {
  return readPinnedItems().some((item) => item.id === id);
}

export function pinItem(item: PinnedItem): void {
  const current = readPinnedItems();
  if (current.some((existing) => existing.id === item.id)) return;
  writePinnedItems([item, ...current].slice(0, MAX_PINNED));
}

export function unpinItem(id: string): void {
  writePinnedItems(readPinnedItems().filter((item) => item.id !== id));
}

export function togglePinnedItem(item: PinnedItem): boolean {
  if (isPinned(item.id)) {
    unpinItem(item.id);
    return false;
  }
  pinItem(item);
  return true;
}

export function makePinnedItemForPane(
  code: string,
  symbol: string | undefined,
  entries: FunctionEntry[],
): PinnedItem {
  const upperCode = code.toUpperCase();
  const normalizedSymbol = normalizeSymbolInput(symbol);
  if (upperCode === "HOME") {
    return makeItem({
      id: "workspace:HOME",
      kind: "workspace",
      code: "HOME",
      label: "Overview",
      meta: "OVR",
      path: "/",
    });
  }
  if (upperCode === "PREF") {
    return makeItem({
      id: "workspace:PREF",
      kind: "workspace",
      code: "PREF",
      label: "Preferences",
      meta: "SET",
      path: "/preferences",
    });
  }
  if (normalizedSymbol) {
    return makeItem({
      id: `symbol:${normalizedSymbol}:${upperCode}`,
      kind: "symbol",
      code: normalizedSymbol,
      label: normalizedSymbol,
      meta: upperCode,
      path: `/symbol/${normalizedSymbol}/${upperCode}`,
    });
  }
  const entry = entries.find((item) => item.code.toUpperCase() === upperCode);
  return makeItem({
    id: `function:${upperCode}`,
    kind: "function",
    code: upperCode,
    label: entry?.name ?? upperCode,
    meta: upperCode,
    path: `/fn/${upperCode}`,
  });
}

export function makePinnedItemForFunctionEntry(entry: FunctionEntry): PinnedItem {
  return makeItem({
    id: `function:${entry.code.toUpperCase()}`,
    kind: "function",
    code: entry.code,
    label: entry.name,
    meta: entry.code,
    path: `/fn/${entry.code.toUpperCase()}`,
  });
}

export function resetPinnedItemsForTests(): void {
  cache = null;
}
