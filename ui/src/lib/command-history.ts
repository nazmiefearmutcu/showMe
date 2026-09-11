/**
 * Command-line history (campaign 2026-09-11, Lane L2).
 *
 * Session-scoped (sessionStorage) stack of commands the user actually ran,
 * newest first, capped at 50, consecutive duplicates collapsed. The
 * CommandLine input and the palette's empty-query ArrowUp/Down both step
 * the same stack.
 *
 * Key:   `showme.cmd.history.v1`
 * Shape: JSON string[]
 *
 * Stepping semantics (`stepCommandHistory(current, dir)`):
 *   - `dir === -1` (ArrowUp / older):  returns the next older entry, or
 *     the newest entry when `current` is the draft (no history match), or
 *     the oldest entry again when already at the oldest (clamped).
 *   - `dir === 1`  (ArrowDown / newer): returns the next newer entry; when
 *     stepping past the newest (or when `current` is a draft that is not a
 *     history entry) it returns `null` — the caller then restores its own
 *     saved draft. That is how the draft survives a round trip.
 *   - returns `null` when the history is empty in both directions.
 *
 * First-use seeding: when the session key is absent, the palette's recent
 * function codes (`lib/palette-recents.ts`) are copied in so the very first
 * ArrowUp shows something useful instead of nothing. Once the key exists
 * (including an empty array), it is never re-seeded.
 */
import { listRecentCodes } from "./palette-recents";

export const COMMAND_HISTORY_KEY = "showme.cmd.history.v1";
export const COMMAND_HISTORY_MAX = 50;

function storage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function readRaw(): string[] {
  const box = storage();
  if (!box) return [];
  try {
    const raw = box.getItem(COMMAND_HISTORY_KEY);
    if (raw === null) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    return [];
  }
}

function writeRaw(entries: string[]): void {
  const box = storage();
  if (!box) return;
  try {
    box.setItem(COMMAND_HISTORY_KEY, JSON.stringify(entries));
  } catch {
    // Quota / private mode — history is best-effort, never throw.
  }
}

function seedFromRecentsIfAbsent(): void {
  const box = storage();
  if (!box) return;
  try {
    if (box.getItem(COMMAND_HISTORY_KEY) !== null) return;
  } catch {
    return;
  }
  const seeded = listRecentCodes().slice(0, COMMAND_HISTORY_MAX);
  if (seeded.length === 0) return;
  writeRaw(seeded);
}

/** Full history newest-first (a copy — callers must not mutate it). */
export function getCommandHistory(): string[] {
  seedFromRecentsIfAbsent();
  return readRaw().slice(0, COMMAND_HISTORY_MAX);
}

/**
 * Record a command. Empty input and CONSECUTIVE duplicates are ignored
 * (running A, B, A stores all three — the two A runs are not adjacent).
 */
export function pushCommandHistory(cmd: string): void {
  const text = String(cmd ?? "").trim();
  if (!text) return;
  const current = getCommandHistory();
  if (current[0] === text) return;
  writeRaw([text, ...current].slice(0, COMMAND_HISTORY_MAX));
}

/** Cycle the history around `current`; `null` means "restore your draft". */
export function stepCommandHistory(
  current: string | null,
  dir: -1 | 1,
): string | null {
  const history = getCommandHistory();
  if (history.length === 0) return null;
  const index = current == null ? -1 : history.indexOf(current);
  if (dir === -1) {
    if (index === -1) return history[0] ?? null;
    return history[Math.min(index + 1, history.length - 1)] ?? null;
  }
  if (index <= 0) return null;
  return history[index - 1] ?? null;
}

export function clearCommandHistory(): void {
  const box = storage();
  if (!box) return;
  try {
    box.removeItem(COMMAND_HISTORY_KEY);
  } catch {
    // ignore
  }
}

/** Test helper: drop the session stack and the seeding latch. */
export function __resetForTests(): void {
  clearCommandHistory();
}
