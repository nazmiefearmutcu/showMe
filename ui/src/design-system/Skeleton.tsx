/**
 * Skeleton — loading placeholder.
 *
 * Desk-instrument styling (DESIGN-BRIEF laws 2 + 5): a flat surface-3 block
 * with a hairline edge and a 1.2s opacity pulse — no gradient sweep. The
 * pulse animation is declared in `styles/components.css` and wrapped in a
 * `prefers-reduced-motion: no-preference` guard, so reduced-motion users
 * get a static block. No runtime `<style>` injection anymore.
 */
import type { CSSProperties } from "react";

export function Skeleton({
  width = "100%",
  height = 12,
  radius,
}: {
  width?: number | string;
  height?: number | string;
  radius?: number | string;
}) {
  const style: CSSProperties = { width, height };
  if (radius != null) style.borderRadius = radius;
  return <span aria-busy="true" className="ds-skeleton" style={style} />;
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
