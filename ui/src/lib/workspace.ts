/**
 * Workspace tree — first-party multi-pane state.
 *
 * The tree is a recursive structure of:
 *   leaf  → { id, kind: "leaf", code, symbol? }
 *   split → { id, kind: "split", direction: "h"|"v", children, sizes }
 *
 * `sizes` always sums to ~1.0 and matches `children.length`. The renderer
 * (shell/Workspace.tsx) walks this tree and lays panes out.
 *
 * Round 15 keeps the pane content addressed by `code`+`symbol`, looked up
 * via the same `resolvePane` registry as the single-pane router. The hash
 * router still owns navigation; it pushes route changes into the *focused*
 * leaf so ⌘K and the sidebar remain symmetric with single-pane mode.
 */
import { create } from "zustand";
import { normalizeSymbolInput } from "./symbols";

export type Direction = "h" | "v";

export interface LeafNode {
  id: string;
  kind: "leaf";
  code: string;
  symbol?: string;
  /** Symbol-link group: leaves sharing a non-empty group rebind in lockstep. */
  linkGroup?: string;
}

export interface SplitNode {
  id: string;
  kind: "split";
  direction: Direction;
  children: WorkspaceNode[];
  sizes: number[];
}

export type WorkspaceNode = LeafNode | SplitNode;

/**
 * CRITICAL #3 (UI-Shell-Bundle UB) — node-id generator.
 *
 * The old implementation paired a module-scoped `_id` counter with a 4-char
 * random suffix. That breaks down across multi-window Tauri shells because
 * the counter only protects within a single JS realm — two webviews can
 * (and did) hand out `n1-abcd` simultaneously, then collide when one
 * workspace is serialized into the other's persistence file. The 4-char
 * suffix is also a 1-in-1.6M collision risk per realm given the small
 * working set sizes (≤30 leaves).
 *
 * Switching to a 16-char crypto-random suffix gives ~2^80 of entropy per
 * id and removes the counter dependency entirely. In jsdom (vitest) and
 * older webviews where `crypto.randomUUID` is missing we fall back to
 * `crypto.getRandomValues` + base36 — same entropy budget. Last-resort
 * `Math.random` keeps the function pure on truly broken environments.
 */
function nextId(): string {
  const g = typeof globalThis === "undefined" ? undefined : (globalThis as { crypto?: Crypto });
  const c = g?.crypto;
  if (c && typeof c.randomUUID === "function") {
    return `n-${c.randomUUID().replace(/-/g, "").slice(0, 16)}`;
  }
  if (c && typeof c.getRandomValues === "function") {
    const buf = new Uint8Array(10);
    c.getRandomValues(buf);
    let out = "";
    for (let i = 0; i < buf.length; i += 1) out += buf[i].toString(36).padStart(2, "0");
    return `n-${out.slice(0, 16)}`;
  }
  // Defensive last-resort — keep entropy high enough to avoid the 4-char
  // birthday problem from the legacy generator.
  return `n-${Math.random().toString(36).slice(2, 10)}${Math.random().toString(36).slice(2, 10)}`;
}

export function leaf(code: string, symbol?: string): LeafNode {
  return { id: nextId(), kind: "leaf", code: code.toUpperCase(), symbol };
}

export function split(
  direction: Direction,
  children: WorkspaceNode[],
  sizes?: number[],
): SplitNode {
  const n = children.length;
  const equal = Array.from({ length: n }, () => 1 / n);
  return {
    id: nextId(),
    kind: "split",
    direction,
    children,
    sizes: sizes && sizes.length === n ? normalize(sizes) : equal,
  };
}

export function normalize(sizes: number[]): number[] {
  const sum = sizes.reduce((s, v) => s + Math.max(v, 0), 0);
  if (sum <= 0) return sizes.map(() => 1 / sizes.length);
  return sizes.map((v) => Math.max(v, 0) / sum);
}

// HIGH #9 (UI-Shell-Bundle UB) — `resetTo` subscribers.
//
// When the workspace tree is wholesale replaced (preset switch, S11
// migration self-heal, programmatic reset) any in-flight pane fetches
// and lingering AbortControllers used to outlive the unmount and write
// back into stores belonging to leaves that no longer existed. The
// public `onWorkspaceReset` hook lets feature modules (sidecar request
// queue, pin store, link-group registry) register a cleanup callback
// that fires *before* the tree is swapped. Synchronous to keep React's
// commit cycle untangled.
type ResetSubscriber = () => void;
const resetSubscribers = new Set<ResetSubscriber>();

export function onWorkspaceReset(fn: ResetSubscriber): () => void {
  resetSubscribers.add(fn);
  return () => resetSubscribers.delete(fn);
}

function runResetSubscribers(): void {
  for (const fn of resetSubscribers) {
    try {
      fn();
    } catch (err) {
      console.warn("onWorkspaceReset subscriber threw", err);
    }
  }
}

interface WorkspaceState {
  tree: WorkspaceNode;
  focusedId: string;
  setTree: (tree: WorkspaceNode, focusedId?: string) => void;
  setFocused: (id: string) => void;
  /** Replace the focused leaf's code/symbol (route-driven). */
  setFocusedTarget: (code: string, symbol?: string) => void;
  /** Replace a specific leaf's code/symbol from in-pane controls. */
  setLeafTarget: (leafId: string, code: string, symbol?: string) => void;
  /** Toggle the symbol-link group on the focused leaf. */
  setLeafLinkGroup: (leafId: string, linkGroup?: string) => void;
  /** Split the focused leaf in half along `direction`, opening a new leaf with `code`. */
  splitFocused: (direction: Direction, target?: { code: string; symbol?: string }) => void;
  /** Close the focused leaf; collapses parent split if only 1 sibling remains. */
  closeFocused: () => boolean;
  /** Reset workspace to a single leaf. */
  resetTo: (code: string, symbol?: string) => void;
  /** Update sizes on a split node (called from drag handles). */
  setSplitSizes: (splitId: string, sizes: number[]) => void;
}

// S10 dashboard-restore: cold boot lands on the single HOME leaf, which
// `Workspace.tsx` renders via the native `<Welcome />` dashboard. The
// S09 design-export cockpit (`PrChart` / `SITUATION BRIEFING` /
// `SIDECAR :8421`) is permanently neutered by the HOME branch — HOME is
// safe and native again, so it's the right cold-boot surface. Markets
// Overview stays as an explicit preset (`loadBuiltinPreset("markets-
// overview")`), not the default behavior.
const root = leaf("HOME");

export const useWorkspace = create<WorkspaceState>((set, get) => ({
  tree: root,
  focusedId: root.id,
  setTree: (tree, focusedId) =>
    set({ tree, focusedId: focusedId ?? firstLeafId(tree) }),
  setFocused: (id) => set({ focusedId: id }),
  setFocusedTarget: (code, symbol) =>
    set((s) => {
      const focused = findLeaf(s.tree, s.focusedId);
      let next = updateLeaf(s.tree, s.focusedId, code, symbol);
      // If the focused leaf belongs to a link group, rebroadcast the
      // symbol to every other leaf in the same group (their code stays).
      if (focused?.linkGroup && symbol) {
        next = broadcastSymbolToGroup(next, focused.linkGroup, symbol, focused.id);
      }
      return { tree: next };
    }),
  setLeafTarget: (leafId, code, symbol) =>
    set((s) => {
      const leaf = findLeaf(s.tree, leafId);
      let next = updateLeaf(s.tree, leafId, code, symbol);
      if (leaf?.linkGroup && symbol) {
        next = broadcastSymbolToGroup(next, leaf.linkGroup, symbol, leaf.id);
      }
      return { tree: next };
    }),
  setLeafLinkGroup: (leafId, linkGroup) =>
    set((s) => ({
      tree: replaceNode(s.tree, leafId, (n) =>
        n.kind === "leaf" ? { ...n, linkGroup: linkGroup || undefined } : n,
      ),
    })),
  splitFocused: (direction, target) => {
    const { tree, focusedId } = get();
    const focused = findLeaf(tree, focusedId);
    if (!focused) return;
    const spawn = leaf(target?.code ?? focused.code, target?.symbol ?? focused.symbol);
    const next = replaceNode(tree, focusedId, () =>
      split(direction, [{ ...focused }, spawn]),
    );
    set({ tree: next, focusedId: spawn.id });
  },
  closeFocused: () => {
    const { tree, focusedId } = get();
    const next = removeLeaf(tree, focusedId);
    if (!next) return false;
    set({ tree: next, focusedId: firstLeafId(next) });
    return true;
  },
  resetTo: (code, symbol) => {
    // HIGH #9: notify subscribers that the previous tree is being
    // discarded. The hook lets in-flight pane fetches abort and lets
    // pinned/link bindings drop references to leaf ids that are about
    // to disappear. Errors in subscribers must not block the reset.
    try {
      runResetSubscribers();
    } catch (err) {
      console.warn("workspace.resetTo subscriber threw", err);
    }
    const root = leaf(code, symbol);
    set({ tree: root, focusedId: root.id });
  },
  setSplitSizes: (splitId, sizes) =>
    set((s) => ({ tree: updateSplitSizes(s.tree, splitId, sizes) })),
}));

// ── Pure helpers ─────────────────────────────────────────────────────────

export function firstLeafId(node: WorkspaceNode): string {
  if (node.kind === "leaf") return node.id;
  return firstLeafId(node.children[0]);
}

export function findLeaf(node: WorkspaceNode, id: string): LeafNode | null {
  if (node.kind === "leaf") return node.id === id ? node : null;
  for (const c of node.children) {
    const hit = findLeaf(c, id);
    if (hit) return hit;
  }
  return null;
}

export function findParent(
  node: WorkspaceNode,
  childId: string,
  parent: SplitNode | null = null,
): SplitNode | null {
  if (node.kind === "leaf") return node.id === childId ? parent : null;
  for (const c of node.children) {
    if (c.id === childId) return node;
    const hit = findParent(c, childId, node);
    if (hit) return hit;
  }
  return null;
}

function replaceNode(
  node: WorkspaceNode,
  id: string,
  replacer: (n: WorkspaceNode) => WorkspaceNode,
): WorkspaceNode {
  if (node.id === id) return replacer(node);
  if (node.kind === "split") {
    return {
      ...node,
      children: node.children.map((c) => replaceNode(c, id, replacer)),
    };
  }
  return node;
}

function updateLeaf(
  node: WorkspaceNode,
  id: string,
  code: string,
  symbol?: string,
): WorkspaceNode {
  return replaceNode(node, id, (n) => {
    if (n.kind !== "leaf") return n;
    const normalizedSymbol = normalizeSymbolInput(symbol);
    return { ...n, code: code.toUpperCase(), symbol: normalizedSymbol || undefined };
  });
}

/**
 * HIGH #10 (UI-Shell-Bundle UB) — cycle-safe link-group broadcast.
 *
 * The legacy version was a pure tree walk that assumed `node` is a real
 * tree. In practice a defensive `visited` set is still cheap and rules
 * out a category of bugs where a malformed persisted tree (or a future
 * graph-style structure) would otherwise recurse forever. We also cap
 * the number of leaves we touch per single broadcast to `MAX_BROADCAST_
 * LEAVES`, so a single setFocusedTarget can never spend more than that
 * many writes on linked siblings even if the tree balloons.
 */
const MAX_BROADCAST_LEAVES = 20;

export function broadcastSymbolToGroup(
  node: WorkspaceNode,
  group: string,
  symbol: string,
  originId: string,
  visited?: Set<string>,
  counter?: { count: number },
): WorkspaceNode {
  const seen = visited ?? new Set<string>();
  const ctr = counter ?? { count: 0 };
  if (seen.has(node.id)) return node; // already walked — bail (cycle)
  seen.add(node.id);
  if (node.kind === "leaf") {
    if (node.id !== originId && node.linkGroup === group) {
      if (ctr.count >= MAX_BROADCAST_LEAVES) return node;
      ctr.count += 1;
      return { ...node, symbol: normalizeSymbolInput(symbol) || undefined };
    }
    return node;
  }
  return {
    ...node,
    children: node.children.map((c) =>
      broadcastSymbolToGroup(c, group, symbol, originId, seen, ctr),
    ),
  };
}

function updateSplitSizes(
  node: WorkspaceNode,
  splitId: string,
  sizes: number[],
): WorkspaceNode {
  return replaceNode(node, splitId, (n) => {
    if (n.kind !== "split") return n;
    return { ...n, sizes: normalize(sizes) };
  });
}

/**
 * Remove the leaf with id. If its parent ends up with one child, replace
 * the parent with that surviving child (collapse). Returns null if the
 * removal would empty the tree (caller should keep a fallback leaf).
 */
export function removeLeaf(
  node: WorkspaceNode,
  id: string,
): WorkspaceNode | null {
  if (node.kind === "leaf") return node.id === id ? null : node;
  // Recurse into children.
  const newChildren: WorkspaceNode[] = [];
  let collapsed = false;
  for (const c of node.children) {
    const r = removeLeaf(c, id);
    if (r === null) {
      collapsed = true;
      continue;
    }
    newChildren.push(r);
  }
  if (newChildren.length === 0) return null;
  if (newChildren.length === 1) return newChildren[0]; // collapse
  // Re-distribute sizes proportionally to survivors when one was removed.
  if (collapsed) {
    const survivors = newChildren.length;
    const sizes = Array.from({ length: survivors }, () => 1 / survivors);
    return { ...node, children: newChildren, sizes };
  }
  return { ...node, children: newChildren };
}

// ── Serialization (presets / window-state) ───────────────────────────────

export interface SerializedWorkspace {
  tree: WorkspaceNode;
  focusedId: string;
  savedAt: string;
}

export function serializeWorkspace(): SerializedWorkspace {
  const { tree, focusedId } = useWorkspace.getState();
  return {
    tree: deepClone(tree),
    focusedId,
    savedAt: new Date().toISOString(),
  };
}

export function loadWorkspace(state: SerializedWorkspace): void {
  if (!state || !state.tree) return;
  // HIGH #9 — preset switch / poison self-heal goes through this code
  // path; run the same reset subscribers so the previous tree's pane
  // requests, link-group bindings, and pinned ids can be cleaned.
  try {
    runResetSubscribers();
  } catch (err) {
    console.warn("loadWorkspace reset subscribers threw", err);
  }
  // Rebuild ids so we don't collide with the live tree.
  const tree = remapIds(state.tree);
  // After remap, focusedId is stale — fall back to first leaf.
  useWorkspace.getState().setTree(tree, firstLeafId(tree));
}

function remapIds(node: WorkspaceNode): WorkspaceNode {
  if (node.kind === "leaf") {
    const symbol = normalizeSymbolInput(node.symbol);
    return { ...node, id: nextId(), symbol: symbol || undefined };
  }
  return {
    ...node,
    id: nextId(),
    children: node.children.map(remapIds),
  };
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
