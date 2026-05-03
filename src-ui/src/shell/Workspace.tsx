/**
 * Workspace renderer — recursive split tree with drag-resize handles.
 *
 * Single source of multi-pane layout. Each leaf renders the focused
 * pane via `resolvePane`; the registry's `FunctionStub` handles codes
 * we haven't ported natively.
 */
import { useEffect, useRef } from "react";
import {
  useWorkspace,
  type LeafNode,
  type SplitNode,
  type WorkspaceNode,
} from "@/lib/workspace";
import { resolvePane } from "@/functions/registry";
import { FunctionStub } from "@/panes/FunctionStub";
import { Welcome } from "@/panes/Welcome";
import { Preferences } from "@/panes/Preferences";
import { PaneChrome } from "./PaneChrome";

const HANDLE_PX = 4;

export function Workspace() {
  const tree = useWorkspace((s) => s.tree);
  return <Node node={tree} />;
}

function Node({ node }: { node: WorkspaceNode }) {
  if (node.kind === "leaf") return <Leaf node={node} />;
  return <Split node={node} />;
}

function Leaf({ node }: { node: LeafNode }) {
  const focusedId = useWorkspace((s) => s.focusedId);
  const setFocused = useWorkspace((s) => s.setFocused);
  const isFocused = focusedId === node.id;
  return (
    <div
      onMouseDownCapture={() => setFocused(node.id)}
      style={{
        height: "100%",
        width: "100%",
        outline: isFocused
          ? "1px solid var(--accent)"
          : "1px solid transparent",
        outlineOffset: -1,
        transition: "outline-color var(--motion-fast)",
        display: "grid",
        gridTemplateRows: "auto 1fr",
        background: "var(--bg-base)",
        minHeight: 0,
        minWidth: 0,
      }}
    >
      <PaneChrome
        leafId={node.id}
        code={node.code}
        symbol={node.symbol}
        linkGroup={node.linkGroup}
      />
      <div
        style={{
          overflow: "hidden",
          position: "relative",
          minHeight: 0,
          minWidth: 0,
        }}
      >
        <PaneContent leafId={node.id} code={node.code} symbol={node.symbol} />
      </div>
    </div>
  );
}

function PaneContent({
  leafId,
  code,
  symbol,
}: {
  leafId: string;
  code: string;
  symbol?: string;
}) {
  if (code === "HOME") return <Welcome />;
  if (code === "PREF") return <Preferences />;
  const Native = resolvePane(code);
  if (Native) return <Native code={code} symbol={symbol} />;
  return <FunctionStub leafId={leafId} code={code} symbol={symbol} />;
}

function Split({ node }: { node: SplitNode }) {
  const setSplitSizes = useWorkspace((s) => s.setSplitSizes);
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingIdx = useRef<number | null>(null);
  const startSizes = useRef<number[] | null>(null);
  const startCoord = useRef<number>(0);
  const containerSize = useRef<number>(0);

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const idx = draggingIdx.current;
      if (idx == null) return;
      const start = startSizes.current;
      const total = containerSize.current;
      if (!start || !total) return;
      const delta =
        ((node.direction === "h" ? e.clientX : e.clientY) - startCoord.current) /
        total;
      const next = [...start];
      const min = 0.08;
      const a = Math.max(min, Math.min(start[idx] + delta, start[idx] + start[idx + 1] - min));
      const b = start[idx] + start[idx + 1] - a;
      next[idx] = a;
      next[idx + 1] = b;
      setSplitSizes(node.id, next);
    };
    const onUp = () => {
      draggingIdx.current = null;
      startSizes.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [node.direction, node.id, setSplitSizes]);

  const startDrag = (idx: number) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    containerSize.current = node.direction === "h" ? rect.width : rect.height;
    startSizes.current = [...node.sizes];
    startCoord.current = node.direction === "h" ? e.clientX : e.clientY;
    draggingIdx.current = idx;
  };

  return (
    <div
      ref={containerRef}
      style={{
        display: "grid",
        gridTemplateColumns:
          node.direction === "h"
            ? node.sizes.map((s) => `${(s * 100).toFixed(4)}fr`).join(` ${HANDLE_PX}px `)
            : "1fr",
        gridTemplateRows:
          node.direction === "v"
            ? node.sizes.map((s) => `${(s * 100).toFixed(4)}fr`).join(` ${HANDLE_PX}px `)
            : "1fr",
        height: "100%",
        width: "100%",
        minHeight: 0,
        minWidth: 0,
      }}
    >
      {node.children.flatMap((child, i) => {
        const items: React.ReactNode[] = [
          <div
            key={`pane-${child.id}`}
            style={{ overflow: "hidden", minWidth: 0, minHeight: 0 }}
          >
            <Node node={child} />
          </div>,
        ];
        if (i < node.children.length - 1) {
          items.push(
            <div
              key={`handle-${child.id}`}
              onMouseDown={startDrag(i)}
              style={{
                background: "var(--border-subtle)",
                cursor: node.direction === "h" ? "col-resize" : "row-resize",
                userSelect: "none",
                width: node.direction === "h" ? HANDLE_PX : "100%",
                height: node.direction === "v" ? HANDLE_PX : "100%",
              }}
              role="separator"
              aria-orientation={node.direction === "h" ? "vertical" : "horizontal"}
            />,
          );
        }
        return items;
      })}
    </div>
  );
}
