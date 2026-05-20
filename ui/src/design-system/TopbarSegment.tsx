/**
 * TopbarSegment — one cluster of buttons/pills inside the title bar.
 *
 * Encapsulates the spacing, optional caption, and divider that the new
 * Welcome design uses to break the topbar into product-name / pills /
 * actions groups without rebuilding the layout each time.
 */

import type { ReactNode } from "react";

export function TopbarSegment({
  children,
  caption,
  withDivider = false,
  align = "start",
}: {
  children: ReactNode;
  caption?: ReactNode;
  withDivider?: boolean;
  align?: "start" | "end";
}) {
  const classes = [
    "ds-topbar-seg",
    withDivider ? `ds-topbar-seg--divider-${align}` : null,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes}>
      {withDivider && align === "start" && (
        <span aria-hidden className="ds-topbar-seg__divider ds-topbar-seg__divider--start" />
      )}
      {caption && <span className="ds-topbar-seg__caption">{caption}</span>}
      {children}
      {withDivider && align === "end" && (
        <span aria-hidden className="ds-topbar-seg__divider ds-topbar-seg__divider--end" />
      )}
    </span>
  );
}
