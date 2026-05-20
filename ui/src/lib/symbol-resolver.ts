import { sidecarFetch } from "./sidecar";
import { normalizeSymbolInput } from "./symbols";

export async function resolveSymbolInput(symbol: string): Promise<string> {
  const fallback = normalizeSymbolInput(symbol);
  const raw = String(symbol ?? "").trim();
  if (!raw) return fallback;
  try {
    // Routed through sidecarFetch so the auth header + port-discovery layer
    // both apply. See ARCH-05 P2.
    const qs = new URLSearchParams({ symbol: raw });
    const payload = await sidecarFetch<{ symbol?: unknown }>(
      `/api/symbol/resolve?${qs.toString()}`,
    );
    return normalizeSymbolInput(String(payload.symbol ?? fallback)) || fallback;
  } catch {
    return fallback;
  }
}
