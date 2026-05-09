import { waitForSidecarReady } from "./sidecar";
import { normalizeSymbolInput } from "./symbols";

export async function resolveSymbolInput(symbol: string): Promise<string> {
  const fallback = normalizeSymbolInput(symbol);
  const raw = String(symbol ?? "").trim();
  if (!raw) return fallback;
  try {
    const baseUrl = await waitForSidecarReady();
    const qs = new URLSearchParams({ symbol: raw });
    const res = await fetch(`${baseUrl}/api/symbol/resolve?${qs}`);
    if (!res.ok) return fallback;
    const payload = (await res.json()) as { symbol?: unknown };
    return normalizeSymbolInput(String(payload.symbol ?? fallback)) || fallback;
  } catch {
    return fallback;
  }
}
