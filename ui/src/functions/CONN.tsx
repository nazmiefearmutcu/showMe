/**
 * CONN — Connect Exchange.
 *
 * Sub-system A's user surface. Search + filter the catalog, add /
 * test / delete connections, escalate read-only credentials to
 * trade via re-typed-label confirmation.
 */
import { useEffect, useMemo, useState } from "react";
import {
  type CatalogEntry,
  type CredentialRecord,
  useExchangeStore,
} from "@/lib/exchange-store";
import { confirmAction } from "@/lib/confirm";

const ASSET_CLASSES = ["spot", "futures", "swap", "margin", "options", "equity", "fx"] as const;
const REGIONS = ["global", "us", "eu", "asia"] as const;

function Initials({ name, fallbackId }: { name: string; fallbackId?: string }) {
  // QA-2026-05-24 (A12): when a name collides on its 2-letter prefix (e.g.
  // Coinbase / Coinbase Advanced / Coinbase Pro all "CO"), the caller can
  // pass `fallbackId` so we render a 3-letter tag derived from the exchange
  // id instead, breaking the visual collision.
  const baseTag = name.replace(/[^A-Za-zĞÜŞİÖÇğüşıöç]/g, "").slice(0, 2).toUpperCase();
  const expandedTag = fallbackId
    ? fallbackId.replace(/[^A-Za-z0-9]/g, "").slice(0, 3).toUpperCase()
    : baseTag;
  const tag = fallbackId ? expandedTag : baseTag;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 28,
        height: 28,
        borderRadius: 6,
        background: "var(--surface-2)",
        color: "var(--fg-2)",
        fontWeight: 600,
        fontSize: tag.length > 2 ? 10 : 12,
        flex: "0 0 auto",
      }}
    >
      {tag || "??"}
    </span>
  );
}

/**
 * Compute the set of catalog ids whose initials (2-letter prefix) collide
 * with another row. Those rows render with a 3-letter id-derived tag and a
 * suffix on the display name so two `Coinbase Advanced` entries don't
 * appear visually identical.
 */
export function collidingInitials(entries: CatalogEntry[]): Set<string> {
  const buckets = new Map<string, string[]>();
  for (const e of entries) {
    const key = e.display_name
      .replace(/[^A-Za-zĞÜŞİÖÇğüşıöç]/g, "")
      .slice(0, 2)
      .toUpperCase();
    const list = buckets.get(key) ?? [];
    list.push(e.id);
    buckets.set(key, list);
  }
  const out = new Set<string>();
  buckets.forEach((ids) => {
    if (ids.length > 1) ids.forEach((id) => out.add(id));
  });
  return out;
}

/**
 * Compute the set of display_names that appear on more than one catalog
 * entry. Those rows render with " (exchange-id)" suffix so the user can
 * tell them apart.
 */
export function collidingDisplayNames(entries: CatalogEntry[]): Set<string> {
  const counts = new Map<string, number>();
  for (const e of entries) counts.set(e.display_name, (counts.get(e.display_name) ?? 0) + 1);
  const out = new Set<string>();
  counts.forEach((n, name) => {
    if (n > 1) out.add(name);
  });
  return out;
}

function CredentialRow({
  rec, onDelete, onEscalate,
}: {
  rec: CredentialRecord;
  onDelete: (id: string) => void;
  onEscalate: (id: string, label: string) => void;
}) {
  const [confirm, setConfirm] = useState("");
  const [testing, setTesting] = useState<"idle" | "ok" | "err">("idle");
  const [testMsg, setTestMsg] = useState<string | null>(null);
  // Round 24 HIGH — pre-flight dependents lookup runs once per Sil click.
  // Without this `dependentLoading` flag, a double-click queued two lookups
  // + two confirmation modals via handleCredentialDelete.
  const [dependentLoading, setDependentLoading] = useState(false);
  // QA-2026-05-24 (A12): if a prior delete-click ran the dependents lookup
  // and BOTH endpoints failed, the row remembers it so the next click
  // happens against a visible "uncategorized bots" warning instead of
  // surprising the user mid-modal.
  const [botsUnknown, setBotsUnknown] = useState(false);
  // Round 24 HIGH — read in-flight sets from the store so rapid double-
  // clicks on Test/Upgrade buttons can't queue duplicate requests.
  const testingInFlight = useExchangeStore((s) => s.testing.has(rec.id));
  const deletingInFlight = useExchangeStore((s) => s.deleting.has(rec.id));
  const upgradingInFlight = useExchangeStore((s) => s.upgrading.has(rec.id));
  const canTrade = rec.permissions.includes("trade");
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr auto auto auto auto",
      gap: 8, alignItems: "center", padding: "6px 0",
      borderBottom: "1px solid var(--border-1)",
    }}>
      <div>
        <strong>{rec.account_label}</strong>{" "}
        <span style={{ color: canTrade ? "var(--accent-warn)" : "var(--fg-2)" }}>
          {canTrade ? "okuma + işlem" : "salt okuma"}
        </span>
      </div>
      <button
        disabled={testingInFlight}
        onClick={async () => {
          // Round 24 — short-circuit a 2nd rapid click; the store-level
          // `testing.has(id)` guard is the canonical seal.
          if (testingInFlight) return;
          setTesting("idle"); setTestMsg(null);
          const r = await useExchangeStore.getState().testCredential(rec.id);
          setTesting(r.ok ? "ok" : "err");
          setTestMsg(r.ok ? "OK" : (r.error ?? "fail"));
        }}>
        {testingInFlight ? "..." : "Test"}
      </button>
      {!canTrade && (
        <form onSubmit={(e) => {
          // Round 24 CRITICAL 5 — Enter from any input in this form fired
          // submit before React could re-render `disabled`. Local + store
          // guards are both required because the button-disabled is racy.
          e.preventDefault();
          if (upgradingInFlight) return;
          if (confirm === rec.account_label) {
            onEscalate(rec.id, confirm);
          }
        }} style={{ display: "flex", gap: 4 }}>
          <input
            placeholder={`re-type "${rec.account_label}"`}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            style={{ width: 140 }}
          />
          <button type="submit"
                  disabled={upgradingInFlight || confirm !== rec.account_label}>
            {upgradingInFlight ? "..." : "Upgrade"}
          </button>
        </form>
      )}
      {botsUnknown && (
        <span
          data-testid={`conn-bots-unknown-${rec.id}`}
          title="Bot bağımlılıkları doğrulanamadı — silmeden önce kontrol et."
          style={{
            fontSize: 11,
            color: "var(--accent-warn)",
            background: "color-mix(in srgb, var(--accent-warn) 12%, transparent)",
            border: "1px solid var(--accent-warn)",
            borderRadius: 4,
            padding: "2px 6px",
            whiteSpace: "nowrap",
          }}
        >
          May affect uncategorized bots — verify before disconnecting
        </span>
      )}
      <button
        data-testid={`conn-sil-${rec.id}`}
        disabled={dependentLoading || deletingInFlight}
        onClick={async () => {
          // Round 24 HIGH 7 — guard the pre-flight + onDelete sequence. The
          // old handler ran 3 awaits in a row (dependents → confirm modal →
          // deleteCredential) and a double-click queued 3× confirm modals
          // before the first one rendered. Local `dependentLoading` flag
          // covers the pre-flight window; the store-level `deleting` set
          // covers the DELETE itself.
          if (dependentLoading || deletingInFlight) return;
          setDependentLoading(true);
          try {
            const deps = await useExchangeStore.getState().dependentBots(rec.id);
            setBotsUnknown(deps.bots_unknown === true);
          } catch {
            setBotsUnknown(true);
          } finally {
            setDependentLoading(false);
          }
          onDelete(rec.id);
        }}
      >
        {(dependentLoading || deletingInFlight) ? "..." : "Sil"}
      </button>
      {testMsg && (
        <div style={{ gridColumn: "1 / -1", color: testing === "ok" ? "var(--accent-ok)" : "var(--accent-err)" }}>
          {testMsg}
        </div>
      )}
    </div>
  );
}

/**
 * C9 (FIX_CONTRACT) — cascade-aware delete handler.  Resolves the dependent
 * bot count via Agent 2's `/api/exchange/credentials/{id}/dependents` (with a
 * client-side fallback when the endpoint is missing), shows the user a
 * confirm dialog with the bot count, and forwards `force=true` to the DELETE
 * route so the backend cascade-disables the dependents instead of 409'ing.
 *
 * QA-2026-05-24 (A12): when `bots_unknown === true` (both endpoints failed
 * the lookup), the confirm dialog now warns the user instead of silently
 * pretending zero bots are affected — and the delete uses `force=true`
 * defensively so any uncategorized bot dependents are disabled rather than
 * leaving an orphan bot pointing at a missing credential.
 *
 * Exported only for test purposes (`CONN.test.tsx::test_credential_delete_...`).
 */
export async function handleCredentialDelete(
  credentialId: string,
  accountLabel: string,
): Promise<boolean> {
  const dependents = await useExchangeStore.getState().dependentBots(credentialId);
  const botCount = dependents.bot_count;
  const unknown = dependents.bots_unknown === true;
  let title: string;
  let body: string;
  if (unknown) {
    title = "Bot bağımlılıkları doğrulanamadı";
    body =
      `"${accountLabel}" bağlantısının kaç bota bağlı olduğu sunucu tarafından ` +
      `doğrulanamadı (her iki uç nokta da başarısız). Silme işlemi muhtemelen ` +
      `kategorize edilmemiş botları etkileyecek — devam edilsin mi?`;
  } else if (botCount > 0) {
    title = `${botCount} bot etkilenecek`;
    body =
      `Bu credential ${botCount} bota bağlı. Silme işlemi bu botları otomatik olarak ` +
      `devre dışı bırakacak. Devam edilsin mi?`;
  } else {
    title = "Bağlantıyı sil";
    body = `"${accountLabel}" bağlantısı silinsin mi?`;
  }
  const ok = await confirmAction({
    title,
    body,
    primary: "Sil",
    destructive: true,
  });
  if (!ok) return false;
  return useExchangeStore.getState().deleteCredential(credentialId, {
    // Force when (a) we know bots are attached, or (b) we couldn't verify.
    force: botCount > 0 || unknown,
  });
}

function ExchangeForm({ entry }: { entry: CatalogEntry }) {
  const credentials = useExchangeStore((s) => s.credentials);
  const save = useExchangeStore((s) => s.saveCredential);
  const error = useExchangeStore((s) => s.error);
  // Round 24 CRITICAL 3 — read store-level `saving` so the form can
  // disable submit + early-exit Enter-from-input even when the local
  // `submitting` ref hasn't been set yet (race window between the click
  // event and the local setState).
  const storeSaving = useExchangeStore((s) => s.saving);
  const [label, setLabel] = useState("");
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  const [permsTrade, setPermsTrade] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const allFields = [...entry.requires, ...entry.optional];

  const myCreds = credentials.filter((c) => c.exchange_id === entry.id);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3>{entry.display_name} bağlantıları</h3>
      {myCreds.length === 0 && <div style={{ color: "var(--fg-2)" }}>(henüz bağlantı yok)</div>}
      {myCreds.map((rec) => (
        <CredentialRow
          key={rec.id}
          rec={rec}
          onDelete={(id) => {
            void handleCredentialDelete(id, rec.account_label);
          }}
          onEscalate={(id, lbl) => useExchangeStore.getState().upgradeToTrade(id, lbl)}
        />
      ))}

      <h4>Yeni bağlantı ekle</h4>
      <form
        onSubmit={async (e) => {
          // Round 24 CRITICAL 5 — Enter in any input fires `submit`. The
          // button has `disabled={submitting || storeSaving}` but React's
          // re-render lags the click. Inline guard is the cheapest layer.
          e.preventDefault();
          if (submitting || storeSaving) return;
          setSubmitting(true);
          const ok = await save({
            exchange_id: entry.id,
            account_label: label,
            secrets,
            permissions: permsTrade ? ["read", "trade"] : ["read"],
          });
          setSubmitting(false);
          if (ok) {
            setLabel("");
            setSecrets({});
            setPermsTrade(false);
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: 6 }}
      >
        <label>
          account label
          <input value={label} onChange={(e) => setLabel(e.target.value)} required minLength={1} />
        </label>
        {allFields.map((field) => (
          <label key={field}>
            {field}
            <input
              type={field.includes("secret") || field.includes("passphrase") ? "password" : "text"}
              value={secrets[field] ?? ""}
              onChange={(e) => setSecrets({ ...secrets, [field]: e.target.value })}
              required={entry.requires.includes(field)}
            />
          </label>
        ))}
        <label>
          <input
            type="checkbox"
            checked={permsTrade}
            onChange={(e) => setPermsTrade(e.target.checked)}
          />
          Okuma + işlem (trade) izni
        </label>
        {permsTrade && (
          <div style={{ color: "var(--accent-err)" }}>
            Dikkat: bu kimlik bilgisi gerçek hesapta emir gönderebilir. Borsa tarafında da
            "trading" scope'unu gerçekten verdiğinden ve API anahtarını IP'ye bağladığından
            emin ol.
          </div>
        )}
        <button type="submit" disabled={submitting || storeSaving}>
          {(submitting || storeSaving) ? "..." : "Bağlan"}
        </button>
        {error && <div style={{ color: "var(--accent-err)" }}>{error}</div>}
      </form>
    </div>
  );
}

export function CONNPane() {
  const catalog = useExchangeStore((s) => s.catalog);
  const credentials = useExchangeStore((s) => s.credentials);
  const selectedId = useExchangeStore((s) => s.selectedExchangeId);
  const filterCatalog = useExchangeStore((s) => s.filterCatalog);
  const loadCatalog = useExchangeStore((s) => s.loadCatalog);
  const loadCreds = useExchangeStore((s) => s.loadCredentials);
  const setSelected = useExchangeStore((s) => s.setSelectedExchange);
  const [query, setQuery] = useState("");
  const [assetClasses, setAssetClasses] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);

  useEffect(() => { loadCatalog(); loadCreds(); }, [loadCatalog, loadCreds]);

  const filtered = useMemo(
    () => filterCatalog({ query, assetClasses, regions }),
    [query, assetClasses, regions, filterCatalog, catalog],
  );

  // QA-2026-05-24 (A12): hide filter buttons that match zero rows in the
  // current catalog (e.g. `fx`, `swap`, `asia` had no entries) — they
  // produced dead clicks that wiped the list. A button is kept visible if
  // the user has already pressed it (so they can toggle back off) regardless
  // of count.
  const assetClassCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of catalog) {
      for (const cls of e.asset_classes) {
        counts.set(cls, (counts.get(cls) ?? 0) + 1);
      }
    }
    return counts;
  }, [catalog]);
  const regionCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of catalog) {
      for (const r of e.regions) counts.set(r, (counts.get(r) ?? 0) + 1);
    }
    return counts;
  }, [catalog]);
  const visibleAssetClasses = ASSET_CLASSES.filter(
    (a) => (assetClassCounts.get(a) ?? 0) > 0 || assetClasses.includes(a),
  );
  const visibleRegions = REGIONS.filter(
    (r) => (regionCounts.get(r) ?? 0) > 0 || regions.includes(r),
  );

  const collidingNames = useMemo(() => collidingDisplayNames(catalog), [catalog]);
  const collidingInitialsIds = useMemo(() => collidingInitials(catalog), [catalog]);

  const credCount = (exId: string) =>
    credentials.filter((c) => c.exchange_id === exId).length;

  const selected = selectedId ? catalog.find((e) => e.id === selectedId) ?? null : null;

  const toggle = (
    arr: string[], setArr: (v: string[]) => void, val: string,
  ) => () => setArr(arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val]);

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 1fr) 2fr", gap: 16, height: "100%" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, overflow: "hidden" }}>
        <input
          placeholder="Borsa ara…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Borsa ara"
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {visibleAssetClasses.map((a) => (
            <button
              key={a}
              onClick={toggle(assetClasses, setAssetClasses, a)}
              aria-pressed={assetClasses.includes(a)}
              style={{
                opacity: assetClasses.includes(a) ? 1 : 0.55,
                fontSize: 11,
              }}
            >
              {a}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {visibleRegions.map((r) => (
            <button
              key={r}
              onClick={toggle(regions, setRegions, r)}
              aria-pressed={regions.includes(r)}
              style={{
                opacity: regions.includes(r) ? 1 : 0.55,
                fontSize: 11,
              }}
            >
              {r}
            </button>
          ))}
        </div>
        <div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
          {filtered.map((e) => {
            const nameClash = collidingNames.has(e.display_name);
            const initialsClash = collidingInitialsIds.has(e.id);
            const labelSuffix = nameClash ? ` (${e.id})` : "";
            return (
              <button
                key={e.id}
                onClick={() => setSelected(e.id)}
                style={{
                  display: "grid", gridTemplateColumns: "auto 1fr auto",
                  gap: 8, alignItems: "center", padding: "6px 8px",
                  width: "100%", textAlign: "left",
                  background: selectedId === e.id ? "var(--surface-2)" : "transparent",
                  border: "none", borderBottom: "1px solid var(--border-1)",
                  cursor: "pointer",
                }}
              >
                <Initials
                  name={e.display_name}
                  fallbackId={initialsClash ? e.id : undefined}
                />
                <div>
                  <div>{e.display_name}{labelSuffix}</div>
                  <div style={{ fontSize: 10, color: "var(--fg-2)" }}>
                    {e.asset_classes.join(" · ")}
                  </div>
                </div>
                {credCount(e.id) > 0 && (
                  <span style={{ fontSize: 11, color: "var(--accent-ok)" }}>
                    Bağlı: {credCount(e.id)}
                  </span>
                )}
              </button>
            );
          })}
          {filtered.length === 0 && (
            <div style={{ padding: 12, color: "var(--fg-2)" }}>
              Eşleşen borsa yok.
            </div>
          )}
        </div>
      </div>
      <div style={{ overflowY: "auto" }}>
        {selected ? (
          <ExchangeForm key={selected.id} entry={selected} />
        ) : (
          <div style={{ color: "var(--fg-2)" }}>
            Soldan bir borsa seç.
          </div>
        )}
      </div>
    </div>
  );
}

export default CONNPane;
