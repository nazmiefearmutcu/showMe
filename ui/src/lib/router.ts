/**
 * Hash-based pane router.
 *
 * Tauri webviews don't ship server-side routing; Vite's preview is a static
 * server. So we lean on `location.hash` — same path syntax in browser-mode
 * and inside the Tauri shell, no React-Router dependency.
 *
 *  #/                       → welcome
 *  #/preferences            → preferences
 *  #/fn/<CODE>              → function pane (round-14 ships first 5)
 *  #/symbol/<sym>/<CODE>    → symbol-bound function pane
 */
import { useEffect, useState } from "react";

export type Route =
  | { kind: "welcome" }
  | { kind: "preferences"; section?: string }
  | { kind: "function"; code: string; symbol?: string }
  | { kind: "settings"; section?: string }
  | { kind: "not-found"; raw: string };

export function parseRoute(hash: string): Route {
  const cleaned = hash.replace(/^#/, "").replace(/^\/+/, "");
  if (!cleaned || cleaned === "/") return { kind: "welcome" };
  const parts = cleaned.split("/").filter(Boolean);
  switch (parts[0]) {
    case "preferences":
      return { kind: "preferences", section: parts[1] };
    case "settings":
      return { kind: "settings", section: parts[1] };
    case "fn":
      if (!parts[1]) return { kind: "welcome" };
      return { kind: "function", code: parts[1].toUpperCase() };
    case "symbol":
      if (!parts[1] || !parts[2]) return { kind: "welcome" };
      return { kind: "function", code: parts[2].toUpperCase(), symbol: parts[1] };
    default:
      return { kind: "not-found", raw: cleaned };
  }
}

export function navigate(target: string) {
  const next = target.startsWith("#") ? target : `#${target}`;
  if (window.location.hash !== next) window.location.hash = next;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() =>
    parseRoute(window.location.hash || "#/"),
  );
  useEffect(() => {
    const handler = () => setRoute(parseRoute(window.location.hash || "#/"));
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  return route;
}
