/**
 * Tiny fuzzy ranker for the command palette (UI-INT-04 + QA-2026-05-23).
 *
 * Single-token behaviour, by descending priority:
 *   1. Exact code match              → score 2000  (was 1000 — bumped over name
 *                                                   match so "DES" cannot lose
 *                                                   to a name-substring tie)
 *   2. Exact name match              → score 1000
 *   3. Code starts with query        → score 900
 *   4. Token-prefix match in name    → score 700
 *   5. Substring match in code/name  → score 400
 *   6. Subsequence match in code+name (fuzzy, with skips) → score 200
 *   7. Substring match in category   → score 100
 *
 * Multi-token queries (whitespace-delimited) require ALL tokens to match
 * (AND) over the joined `code + " " + name + " " + category` haystack. The
 * aggregate score is the MIN of per-token scores so multi-word matches
 * don't artificially out-rank a tight single-token hit.
 *
 * Returns `null` when no signal at all — caller filters those out.
 * The matcher is case-insensitive; recency boosts (recents stack) are layered
 * on top by the caller.
 */

export interface FuzzyTarget {
  code: string;
  name: string;
  category?: string;
}

export interface FuzzyResult<T extends FuzzyTarget> {
  item: T;
  score: number;
  /** Indices (in code+" "+name) that matched, for highlighter. */
  matches: number[];
}

function scoreSingleToken<T extends FuzzyTarget>(
  item: T,
  query: string,
): FuzzyResult<T> | null {
  const code = item.code.toLowerCase();
  const name = item.name.toLowerCase();
  const category = (item.category ?? "").toLowerCase();
  const haystack = `${code} ${name}`;

  // 1. Exact code match — bumped to 2000 so it always beats name/substring.
  if (code === query) {
    return { item, score: 2000, matches: rangeIndices(0, query.length) };
  }
  // 2. Exact name match.
  if (name === query) {
    const offset = code.length + 1;
    return { item, score: 1000, matches: rangeIndices(offset, query.length) };
  }
  // 3. Code prefix.
  if (code.startsWith(query)) {
    return { item, score: 900, matches: rangeIndices(0, query.length) };
  }
  // 4. Name token prefix.
  const nameTokens = name.split(/\s+/);
  if (nameTokens.some((token) => token.startsWith(query))) {
    const offset = code.length + 1;
    let cursor = 0;
    for (const token of nameTokens) {
      if (token.startsWith(query)) {
        return {
          item,
          score: 700,
          matches: rangeIndices(offset + cursor, query.length),
        };
      }
      cursor += token.length + 1;
    }
  }
  // 5. Substring in code or name.
  const codeIdx = code.indexOf(query);
  if (codeIdx >= 0) {
    return { item, score: 400, matches: rangeIndices(codeIdx, query.length) };
  }
  const nameIdx = name.indexOf(query);
  if (nameIdx >= 0) {
    const offset = code.length + 1;
    return { item, score: 400, matches: rangeIndices(offset + nameIdx, query.length) };
  }
  // 6. Subsequence (fuzzy, allows skips).
  const subseq = subsequenceIndices(haystack, query);
  if (subseq) {
    return { item, score: 200, matches: subseq };
  }
  // 7. Category substring.
  if (category && category.includes(query)) {
    return { item, score: 100, matches: [] };
  }
  return null;
}

export function fuzzyScore<T extends FuzzyTarget>(
  item: T,
  rawQuery: string,
): FuzzyResult<T> | null {
  const trimmed = rawQuery.trim().toLowerCase();
  if (!trimmed) {
    return { item, score: 1, matches: [] };
  }
  // QA-2026-05-23: tokenize on whitespace so "general price" can find
  // GP / Generic Price. Single-token queries take the fast path so the
  // exact-code shortcut still produces score 2000.
  const tokens = trimmed.split(/\s+/).filter(Boolean);
  if (tokens.length <= 1) {
    return scoreSingleToken(item, tokens[0] ?? trimmed);
  }
  let minScore = Infinity;
  const matches = new Set<number>();
  for (const token of tokens) {
    const result = scoreSingleToken(item, token);
    if (!result) return null; // AND — every token must match.
    if (result.score < minScore) minScore = result.score;
    for (const m of result.matches) matches.add(m);
  }
  return {
    item,
    score: minScore,
    matches: [...matches].sort((a, b) => a - b),
  };
}

export function fuzzyRank<T extends FuzzyTarget>(
  items: readonly T[],
  query: string,
  recents: readonly string[] = [],
  limit = 60,
): T[] {
  const recentSet = new Set(recents.map((s) => s.toUpperCase()));
  const ranked: Array<{ item: T; score: number }> = [];
  for (const item of items) {
    const result = fuzzyScore(item, query);
    if (!result) continue;
    let score = result.score;
    if (recentSet.has(item.code.toUpperCase())) {
      score += 50;
    }
    ranked.push({ item, score });
  }
  ranked.sort((a, b) => b.score - a.score);
  return ranked.slice(0, limit).map((entry) => entry.item);
}

function rangeIndices(start: number, length: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < length; i += 1) out.push(start + i);
  return out;
}

function subsequenceIndices(haystack: string, query: string): number[] | null {
  const matches: number[] = [];
  let cursor = 0;
  for (let i = 0; i < query.length; i += 1) {
    const ch = query[i];
    const idx = haystack.indexOf(ch, cursor);
    if (idx === -1) return null;
    matches.push(idx);
    cursor = idx + 1;
  }
  return matches;
}
