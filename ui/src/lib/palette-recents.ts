/**
 * LocalStorage-backed "recently opened" stack for the command palette.
 * Capped at 5 entries; survives reload but not import-export. UI-INT-04.
 */
const KEY = "showme.palette.recents.v1";
const MAX = 5;

function safeRead(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((s) => typeof s === "string").slice(0, MAX);
  } catch {
    return [];
  }
}

function safeWrite(stack: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(stack));
  } catch {
    // Ignore quota / private-mode errors.
  }
}

export function listRecentCodes(): string[] {
  return safeRead();
}

export function recordRecentCode(code: string): void {
  const upper = code.toUpperCase();
  const current = safeRead().filter((c) => c.toUpperCase() !== upper);
  current.unshift(upper);
  safeWrite(current.slice(0, MAX));
}

export function __resetForTests(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(KEY);
  }
}
