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

const ASSET_CLASSES = ["spot", "futures", "swap", "margin", "options", "equity", "fx"] as const;
const REGIONS = ["global", "us", "eu", "asia"] as const;

function Initials({ name }: { name: string }) {
  const tag = name.replace(/[^A-Za-zĞÜŞİÖÇğüşıöç]/g, "").slice(0, 2).toUpperCase();
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
        fontSize: 12,
        flex: "0 0 auto",
      }}
    >
      {tag || "??"}
    </span>
  );
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
  const canTrade = rec.permissions.includes("trade");
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr auto auto auto",
      gap: 8, alignItems: "center", padding: "6px 0",
      borderBottom: "1px solid var(--border-1)",
    }}>
      <div>
        <strong>{rec.account_label}</strong>{" "}
        <span style={{ color: canTrade ? "var(--accent-warn)" : "var(--fg-2)" }}>
          {canTrade ? "okuma + işlem" : "salt okuma"}
        </span>
      </div>
      <button onClick={async () => {
        setTesting("idle"); setTestMsg(null);
        const r = await useExchangeStore.getState().testCredential(rec.id);
        setTesting(r.ok ? "ok" : "err");
        setTestMsg(r.ok ? "OK" : (r.error ?? "fail"));
      }}>
        Test
      </button>
      {!canTrade && (
        <form onSubmit={(e) => {
          e.preventDefault();
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
          <button type="submit" disabled={confirm !== rec.account_label}>
            Upgrade
          </button>
        </form>
      )}
      <button onClick={() => onDelete(rec.id)}>Sil</button>
      {testMsg && (
        <div style={{ gridColumn: "1 / -1", color: testing === "ok" ? "var(--accent-ok)" : "var(--accent-err)" }}>
          {testMsg}
        </div>
      )}
    </div>
  );
}

function ExchangeForm({ entry }: { entry: CatalogEntry }) {
  const credentials = useExchangeStore((s) => s.credentials);
  const save = useExchangeStore((s) => s.saveCredential);
  const error = useExchangeStore((s) => s.error);
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
          onDelete={(id) => useExchangeStore.getState().deleteCredential(id)}
          onEscalate={(id, lbl) => useExchangeStore.getState().upgradeToTrade(id, lbl)}
        />
      ))}

      <h4>Yeni bağlantı ekle</h4>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
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
        <button type="submit" disabled={submitting}>{submitting ? "..." : "Bağlan"}</button>
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
          {ASSET_CLASSES.map((a) => (
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
          {REGIONS.map((r) => (
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
          {filtered.map((e) => (
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
              <Initials name={e.display_name} />
              <div>
                <div>{e.display_name}</div>
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
          ))}
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
