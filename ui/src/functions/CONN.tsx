/**
 * CONN — Connect Exchange.
 *
 * Sub-system A's user surface. Search + filter the catalog, add /
 * test / delete connections, escalate read-only credentials to
 * trade via re-typed-label confirmation.
 *
 * SECURITY: secret form inputs (api_secret / passphrase / ...) live in
 * component-local React state ONLY, are never logged, never persisted to the
 * metadata index, and are cleared after a successful save. The show/hide
 * toggle (F1) flips input *visibility* only — it never copies, logs, or
 * transmits the value.
 */
import { useEffect, useMemo, useState } from "react";
import {
  type CatalogEntry,
  type CredentialDependents,
  type CredentialRecord,
  useExchangeStore,
} from "@/lib/exchange-store";
import { ConfirmDialog, Empty, Pill, Skeleton } from "@/design-system";
import { relativeTimeLabel } from "@/lib/time";

const ASSET_CLASSES = ["spot", "futures", "swap", "margin", "options", "equity", "fx"] as const;
const REGIONS = ["global", "us", "eu", "asia"] as const;

/** Does this credential field hold a secret? (drives type=password + toggle). */
function isSecretField(field: string): boolean {
  return field.includes("secret") || field.includes("passphrase");
}

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

/**
 * F4 — connection status derived from the last test result + last_verified.
 * Honest: never claims "connected" without a real, IN-SESSION verification.
 *
 * P2-2 — a credential `last_verified` in a PREVIOUS session no longer shows
 * the green "Doğrulandı" (which would imply live connectivity); it gets a
 * muted "Daha önce doğrulandı" ("stale") instead. Green is reserved for an
 * in-session successful test only.
 */
type ConnStatus = "ok" | "failed" | "stale" | "untested";

function statusFor(rec: CredentialRecord, lastTest: "idle" | "ok" | "err"): ConnStatus {
  if (lastTest === "ok") return "ok";
  if (lastTest === "err") return "failed";
  return rec.last_verified ? "stale" : "untested";
}

function StatusPill({ status }: { status: ConnStatus }) {
  const map: Record<ConnStatus, { tone: "positive" | "negative" | "muted"; label: string }> = {
    ok: { tone: "positive", label: "Doğrulandı" },
    failed: { tone: "negative", label: "Başarısız" },
    stale: { tone: "muted", label: "Daha önce doğrulandı" },
    untested: { tone: "muted", label: "Denenmedi" },
  };
  const { tone, label } = map[status];
  // role=status so SRs announce the change; the Pill carries the visible label.
  return (
    <span role="status" aria-label={`Durum: ${label}`}>
      <Pill tone={tone} variant="soft" withDot>
        {label}
      </Pill>
    </span>
  );
}

function PermissionPill({ canTrade }: { canTrade: boolean }) {
  return canTrade ? (
    <Pill tone="warn" variant="soft" withDot={false}>
      okuma + işlem
    </Pill>
  ) : (
    <Pill tone="muted" variant="soft" withDot={false}>
      salt okuma
    </Pill>
  );
}

function CredentialRow({
  rec, onDelete, onEscalate,
}: {
  rec: CredentialRecord;
  // P2-1 — the row passes the dependents it already fetched in the click
  // handler so resolveDeletePlan does NOT fetch a second time. `null` means
  // the single lookup threw (both endpoints failed) → treated as unknown.
  onDelete: (id: string, deps: CredentialDependents | null) => void;
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
  const status = statusFor(rec, testing);
  const verifiedLabel = rec.last_verified ? relativeTimeLabel(rec.last_verified) : null;
  const upgradeInputId = `conn-upgrade-confirm-${rec.id}`;
  const testResultId = `conn-test-result-${rec.id}`;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr auto auto auto auto",
      gap: 8, alignItems: "center", padding: "6px 0",
      borderBottom: "1px solid var(--border-1)",
    }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong>{rec.account_label}</strong>
          <PermissionPill canTrade={canTrade} />
          <StatusPill status={status} />
        </div>
        <span style={{ fontSize: 11, color: "var(--fg-2)" }}>
          {verifiedLabel
            ? `Son doğrulama: ${verifiedLabel}`
            : "Son doğrulama: — (Denenmedi)"}
        </span>
      </div>
      <button
        aria-busy={testingInFlight}
        disabled={testingInFlight}
        // P3-1 — associate the live test-result region with this trigger so
        // SR users hear the outcome announced against the Test button.
        aria-describedby={testResultId}
        title={testingInFlight ? "Test sürüyor…" : undefined}
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
          <label
            htmlFor={upgradeInputId}
            style={{
              position: "absolute",
              width: 1,
              height: 1,
              overflow: "hidden",
              clip: "rect(0 0 0 0)",
              whiteSpace: "nowrap",
            }}
          >
            İşlem iznine yükseltmek için hesap etiketini yeniden yaz: {rec.account_label}
          </label>
          <input
            id={upgradeInputId}
            placeholder={`re-type "${rec.account_label}"`}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            style={{ width: 140 }}
          />
          <button type="submit"
                  aria-busy={upgradingInFlight}
                  title={
                    upgradingInFlight
                      ? "Yükseltme sürüyor…"
                      : confirm !== rec.account_label
                        ? "Onaylamak için hesap etiketini birebir yaz."
                        : undefined
                  }
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
        aria-busy={dependentLoading || deletingInFlight}
        disabled={dependentLoading || deletingInFlight}
        title={
          dependentLoading
            ? "Bot bağımlılıkları kontrol ediliyor…"
            : deletingInFlight
              ? "Silme sürüyor…"
              : undefined
        }
        onClick={async () => {
          // Round 24 HIGH 7 — guard the pre-flight + onDelete sequence. The
          // old handler ran 3 awaits in a row (dependents → confirm modal →
          // deleteCredential) and a double-click queued 3× confirm modals
          // before the first one rendered. Local `dependentLoading` flag
          // covers the pre-flight window; the store-level `deleting` set
          // covers the DELETE itself.
          if (dependentLoading || deletingInFlight) return;
          setDependentLoading(true);
          // P2-1 — fetch dependents EXACTLY ONCE and thread the result into
          // onDelete → resolveDeletePlan. The row's `botsUnknown` banner and
          // the dialog's `plan.force` now derive from this SAME single fetch,
          // so they can never diverge. A throw → deps=null → unknown.
          let deps: CredentialDependents | null = null;
          try {
            deps = await useExchangeStore.getState().dependentBots(rec.id);
            setBotsUnknown(deps.bots_unknown === true);
          } catch {
            setBotsUnknown(true);
          } finally {
            setDependentLoading(false);
          }
          onDelete(rec.id, deps);
        }}
      >
        {(dependentLoading || deletingInFlight) ? "..." : "Sil"}
      </button>
      {testMsg && (
        <div
          id={testResultId}
          role="status"
          aria-live="polite"
          className={testing === "ok" ? "u-text-positive" : "u-text-negative"}
          style={{ gridColumn: "1 / -1" }}
        >
          {testMsg}
        </div>
      )}
    </div>
  );
}

/**
 * C9 (FIX_CONTRACT) — resolve the dependent-bot count + confirm copy for a
 * credential delete. Split out from the dialog so the in-app ConfirmDialog
 * (F5) can show the bot count / "doğrulanamadı" warning before the user
 * confirms, and so the same `force`/cascade semantics drive the actual
 * delete. Exported for tests.
 *
 * QA-2026-05-24 (A12): when `bots_unknown === true` (both endpoints failed
 * the lookup), the copy warns the user instead of silently pretending zero
 * bots are affected — and `force` is set defensively so any uncategorized bot
 * dependents are disabled rather than leaving an orphan bot pointing at a
 * missing credential.
 */
export interface DeletePlan {
  title: string;
  body: string;
  force: boolean;
}

/**
 * P2-1 — accepts the PRE-FETCHED dependents from the row's click handler so
 * the delete path performs ONLY ONE `dependentBots` round-trip per Sil click
 * (previously the row and this function each fetched, which double-tripped the
 * network and could diverge). `dependents === null` means the single lookup
 * threw (both endpoints failed) → treated identically to `bots_unknown`.
 */
export function resolveDeletePlan(
  accountLabel: string,
  dependents: CredentialDependents | null,
): DeletePlan {
  const botCount = dependents?.bot_count ?? 0;
  const unknown = dependents === null || dependents.bots_unknown === true;
  if (unknown) {
    return {
      title: "Bot bağımlılıkları doğrulanamadı",
      body:
        `"${accountLabel}" bağlantısının kaç bota bağlı olduğu sunucu tarafından ` +
        `doğrulanamadı (her iki uç nokta da başarısız). Silme işlemi muhtemelen ` +
        `kategorize edilmemiş botları etkileyecek — devam edilsin mi?`,
      force: true,
    };
  }
  if (botCount > 0) {
    return {
      title: `${botCount} bot etkilenecek`,
      body:
        `Bu credential ${botCount} bota bağlı. Silme işlemi bu botları otomatik olarak ` +
        `devre dışı bırakacak. Devam edilsin mi?`,
      force: true,
    };
  }
  return {
    title: "Bağlantıyı sil",
    body: `"${accountLabel}" bağlantısı silinsin mi?`,
    force: false,
  };
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
  // F1 — per-field visibility toggle for secret inputs. Local-only: this
  // flips the input `type` between password/text and never touches the value.
  const [revealed, setRevealed] = useState<Record<string, boolean>>({});
  const [permsTrade, setPermsTrade] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // F5 — in-app delete confirmation state (replaces native confirmAction).
  const [pendingDelete, setPendingDelete] = useState<
    { id: string; label: string; plan: DeletePlan } | null
  >(null);
  const deleting = useExchangeStore((s) => s.deleting);

  const allFields = [...entry.requires, ...entry.optional];

  const myCreds = credentials.filter((c) => c.exchange_id === entry.id);

  // F2 — client-side gate: account_label + all `requires` fields present.
  const missingRequired = entry.requires.filter((f) => !(secrets[f] ?? "").trim());
  const labelMissing = label.trim().length === 0;
  const canSubmit = !labelMissing && missingRequired.length === 0;
  const disabledReason = labelMissing
    ? "Hesap etiketi gerekli."
    : missingRequired.length
      ? `Zorunlu alanlar eksik: ${missingRequired.join(", ")}`
      : undefined;

  const errorRegionId = `conn-form-error-${entry.id}`;
  const labelInputId = `conn-account-label-${entry.id}`;

  // P2-1 — `deps` is the single fetch performed by the row; resolveDeletePlan
  // reuses it instead of re-fetching, so one Sil click = one dependents call.
  const requestDelete = (id: string, lbl: string, deps: CredentialDependents | null) => {
    const plan = resolveDeletePlan(lbl, deps);
    setPendingDelete({ id, label: lbl, plan });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h3>{entry.display_name} bağlantıları</h3>
      {myCreds.length === 0 && (
        <Empty
          title="Henüz bağlantı yok"
          body={`${entry.display_name} için kayıtlı bir API anahtarı yok. Aşağıdan ekle.`}
        />
      )}
      {myCreds.map((rec) => (
        <CredentialRow
          key={rec.id}
          rec={rec}
          onDelete={(id, deps) => {
            requestDelete(id, rec.account_label, deps);
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
          if (submitting || storeSaving || !canSubmit) return;
          setSubmitting(true);
          const ok = await save({
            exchange_id: entry.id,
            account_label: label,
            secrets,
            permissions: permsTrade ? ["read", "trade"] : ["read"],
          });
          setSubmitting(false);
          if (ok) {
            // SECURITY: clear secret inputs from local state after save.
            setLabel("");
            setSecrets({});
            setRevealed({});
            setPermsTrade(false);
          }
        }}
        style={{ display: "flex", flexDirection: "column", gap: 6 }}
      >
        <label htmlFor={labelInputId}>
          account label
          <input
            id={labelInputId}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            required
            minLength={1}
            aria-describedby={errorRegionId}
          />
        </label>
        {allFields.map((field) => {
          const secret = isSecretField(field);
          const fieldId = `conn-field-${entry.id}-${field}`;
          const shown = revealed[field] === true;
          return (
            <label key={field} htmlFor={fieldId}>
              {field}
              <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <input
                  id={fieldId}
                  type={secret && !shown ? "password" : "text"}
                  value={secrets[field] ?? ""}
                  onChange={(e) => setSecrets({ ...secrets, [field]: e.target.value })}
                  required={entry.requires.includes(field)}
                  aria-describedby={errorRegionId}
                  style={{ flex: 1 }}
                />
                {secret && (
                  <button
                    type="button"
                    aria-label={`${shown ? "Gizle" : "Göster"}: ${field}`}
                    aria-pressed={shown}
                    title={shown ? "Gizle" : "Göster"}
                    onClick={() =>
                      setRevealed((r) => ({ ...r, [field]: !r[field] }))
                    }
                    style={{ flex: "0 0 auto" }}
                  >
                    {shown ? "🙈" : "👁"}
                  </button>
                )}
              </span>
            </label>
          );
        })}
        <label>
          <input
            type="checkbox"
            checked={permsTrade}
            onChange={(e) => setPermsTrade(e.target.checked)}
          />
          Okuma + işlem (trade) izni
        </label>
        {permsTrade && (
          <div className="u-text-negative">
            Dikkat: bu kimlik bilgisi gerçek hesapta emir gönderebilir. Borsa tarafında da
            "trading" scope'unu gerçekten verdiğinden ve API anahtarını IP'ye bağladığından
            emin ol.
          </div>
        )}
        <button
          type="submit"
          aria-busy={submitting || storeSaving}
          disabled={submitting || storeSaving || !canSubmit}
          title={
            submitting || storeSaving ? "Kaydediliyor…" : disabledReason
          }
        >
          {(submitting || storeSaving) ? "..." : "Bağlan"}
        </button>
        {/* F2 — add-form error region (announced). */}
        <div
          id={errorRegionId}
          role="status"
          aria-live="polite"
          className="u-text-negative"
        >
          {error || ""}
        </div>
      </form>

      {/* F5 — in-app, focus-trapped delete confirmation (replaces native
          confirmAction). Preserves the bot-count / "doğrulanamadı" copy and
          the exact force/cascade semantics from resolveDeletePlan(). */}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={pendingDelete?.plan.title ?? ""}
        body={pendingDelete?.plan.body}
        confirmLabel="Sil"
        destructive
        busy={pendingDelete ? deleting.has(pendingDelete.id) : false}
        onConfirm={() => {
          if (!pendingDelete) return;
          const { id, plan } = pendingDelete;
          setPendingDelete(null);
          void useExchangeStore.getState().deleteCredential(id, { force: plan.force });
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

export function CONNPane() {
  const catalog = useExchangeStore((s) => s.catalog);
  const credentials = useExchangeStore((s) => s.credentials);
  const selectedId = useExchangeStore((s) => s.selectedExchangeId);
  const catalogLoading = useExchangeStore((s) => s.catalogLoading);
  const credentialsLoading = useExchangeStore((s) => s.credentialsLoading);
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

  // F6 — show a skeleton while the catalog (+ credentials) load on first paint.
  const loading = (catalogLoading || credentialsLoading) && catalog.length === 0;

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
              aria-label={a}
              title={`Varlık sınıfı filtresi: ${a}`}
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
              aria-label={r}
              title={`Bölge filtresi: ${r}`}
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
          {loading && (
            <div data-testid="conn-catalog-loading" aria-busy="true" style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8 }}>
              <Skeleton height={32} />
              <Skeleton height={32} />
              <Skeleton height={32} />
            </div>
          )}
          {!loading && filtered.map((e) => {
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
                  <span className="u-text-positive" style={{ fontSize: 11 }}>
                    Bağlı: {credCount(e.id)}
                  </span>
                )}
              </button>
            );
          })}
          {!loading && filtered.length === 0 && (
            <Empty
              title="Eşleşen borsa yok"
              body="Arama veya filtreleri gevşetmeyi dene."
            />
          )}
        </div>
      </div>
      <div style={{ overflowY: "auto" }}>
        {selected ? (
          <ExchangeForm key={selected.id} entry={selected} />
        ) : (
          <div style={{ color: "var(--text-primary)" }}>
            Soldan bir borsa seç.
          </div>
        )}
      </div>
    </div>
  );
}

export default CONNPane;
