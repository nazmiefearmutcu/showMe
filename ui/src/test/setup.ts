import "@testing-library/jest-dom/vitest";

/**
 * jsdom 25's localStorage shim ships partial under vitest 2.x — `.clear()` /
 * `.removeItem()` aren't always exposed. Replace with an in-memory store so
 * persistence tests run cleanly.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>();
  get length(): number { return this.store.size; }
  clear(): void { this.store.clear(); }
  getItem(k: string): string | null { return this.store.get(k) ?? null; }
  key(i: number): string | null { return [...this.store.keys()][i] ?? null; }
  removeItem(k: string): void { this.store.delete(k); }
  setItem(k: string, v: string): void { this.store.set(k, String(v)); }
}

Object.defineProperty(window, "localStorage", {
  value: new MemoryStorage(),
  writable: true,
});
Object.defineProperty(window, "sessionStorage", {
  value: new MemoryStorage(),
  writable: true,
});
