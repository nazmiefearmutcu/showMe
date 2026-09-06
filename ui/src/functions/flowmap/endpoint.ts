/**
 * Endpoint injection (replaces upstream `net/serverBase.ts`).
 *
 * Upstream FlowMap derived the WS endpoint from `window.__FLOWMAP_SERVER__`
 * (Tauri-injected origin) or `window.location` (vite-proxied dev). The embedded
 * ShowMe pane knows the sidecar origin itself, so the ABSOLUTE endpoint is
 * passed into `createFlowMap(canvas, { wsUrl, ... })` (the frozen contract) and
 * only validated here. The API-base REST paths that serverBase also served
 * (SymbolSearch) are not part of the vendored library.
 */

/**
 * Validate the absolute `ws:` / `wss:` endpoint handed to `createFlowMap`.
 * Throws on a relative URL or wrong scheme — a silent same-origin fallback
 * would connect to ShowMe's own dev server instead of the sidecar.
 */
export function resolveEndpoint(wsUrl: string): string {
  const trimmed = wsUrl.trim();
  if (!/^wss?:\/\//i.test(trimmed)) {
    throw new Error(
      `flowmap: wsUrl must be an absolute ws:// or wss:// endpoint, got "${wsUrl}"`,
    );
  }
  return trimmed;
}
