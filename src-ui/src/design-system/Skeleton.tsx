/**
 * Skeleton — loading placeholder. CSS-only shimmer; no `<motion>` needed.
 * The plan's UI standards forbid spring/bounce — shimmer is a flat sweep.
 */
import type { CSSProperties } from "react";

const shimmerStyle: CSSProperties = {
  background:
    "linear-gradient(90deg, var(--bg-elev-2) 25%, var(--bg-elev-3) 37%, var(--bg-elev-2) 63%)",
  backgroundSize: "400% 100%",
  animation: "skeleton-shimmer 1400ms linear infinite",
  borderRadius: "var(--radius-sm)",
};

const css = `@keyframes skeleton-shimmer {
  0%   { background-position: 100% 0; }
  100% { background-position: 0 0; }
}`;

let injected = false;
function injectKeyframes() {
  if (injected || typeof document === "undefined") return;
  const tag = document.createElement("style");
  tag.dataset.scope = "showme-skeleton";
  tag.textContent = css;
  document.head.appendChild(tag);
  injected = true;
}

export function Skeleton({
  width = "100%",
  height = 12,
  radius,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
}) {
  injectKeyframes();
  return (
    <span
      aria-busy="true"
      style={{
        display: "inline-block",
        width,
        height,
        borderRadius: radius ?? shimmerStyle.borderRadius,
        ...shimmerStyle,
      }}
    />
  );
}

export function SkeletonRow({ columns = 4 }: { columns?: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columns}, 1fr)`,
        gap: 8,
        padding: "6px 0",
      }}
    >
      {Array.from({ length: columns }).map((_, i) => (
        <Skeleton key={i} height={14} />
      ))}
    </div>
  );
}
