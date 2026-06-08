import { useEffect, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  Field,
  FieldRow,
  Pill,
} from "@/design-system";
import { toast } from "@/lib/toast";
import {
  deleteSecret,
  listSecrets,
  secretsBackend,
  setSecret,
  type KeychainEntry,
  type SecretsBackend,
} from "@/lib/secrets";
import { capabilities, type BiometricCapabilities } from "@/lib/biometric";

export function SecretsSection() {
  const [entries, setEntries] = useState<KeychainEntry[]>([]);
  const [account, setAccount] = useState("");
  const [value, setValue] = useState("");
  const [caps, setCaps] = useState<BiometricCapabilities | null>(null);
  const [backend, setBackend] = useState<SecretsBackend>("browser");
  const writable = backend === "keychain";

  useEffect(() => {
    listSecrets().then(setEntries).catch(() => setEntries([]));
    capabilities().then(setCaps).catch(() => setCaps(null));
    secretsBackend().then(setBackend).catch(() => setBackend("unsupported"));
  }, []);

  const refresh = () => {
    listSecrets().then(setEntries).catch(() => setEntries([]));
  };

  const onSave = async () => {
    if (!account.trim() || !value) return;
    try {
      await setSecret(account.trim(), value);
      setValue("");
      setAccount("");
      refresh();
      toast.success("Secret stored", account.trim());
    } catch (err) {
      toast.error("Save failed", String(err));
    }
  };

  const onDelete = async (acct: string) => {
    try {
      const ok = await deleteSecret(acct);
      if (ok) {
        toast.warn("Secret removed", acct);
        refresh();
      }
    } catch (err) {
      toast.error("Delete failed", String(err));
    }
  };

  const backendNote = (() => {
    if (backend === "browser")
      return "Keychain is only available inside the native app. In browser preview this surface is read-only.";
    if (backend === "unsupported")
      return "This OS doesn't expose the macOS Keychain. Use environment variables until a local fallback vault is configured.";
    return null;
  })();

  return (
    <Card>
      <CardHeader
        trailing={
          <span className="u-flex u-gap-6">
            <Pill
              tone={
                backend === "keychain"
                  ? "positive"
                  : backend === "browser"
                    ? "muted"
                    : "warn"
              }
              withDot={false}
            >
              {backend === "keychain"
                ? "Keychain"
                : backend === "browser"
                  ? "Browser"
                  : "Unsupported"}
            </Pill>
            {caps && (
              <Pill
                tone={caps.biometry_available ? "positive" : "muted"}
                withDot={false}
              >
                {caps.biometry_available
                  ? caps.biometry_kind === "face_id"
                    ? "Face ID"
                    : "Touch ID"
                  : "no biometry"}
              </Pill>
            )}
          </span>
        }
      >
        Secrets
      </CardHeader>
      <CardBody>
        {backendNote && (
          <p className="secrets-note">{backendNote}</p>
        )}
        <FieldRow>
          <Field
            label="Account"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            placeholder="e.g. finnhub, openai"
          />
          <Field
            label="Secret"
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="paste API key"
            trailing={
              <button
                type="button"
                onClick={onSave}
                disabled={!writable || !account.trim() || !value}
                className="btn btn--accent u-btn-mini"
                
              >
                Save
              </button>
            }
          />
        </FieldRow>

        <div className="secrets-list">
          {entries.length === 0 && (
            <span className="u-text-mute u-text-11">
              no stored secrets
            </span>
          )}
          {entries.map((e) => (
            <div key={e.account} className="secrets-row">
              <span>{e.account}</span>
              <span className="u-text-mute u-text-10">
                {e.service.split(".").slice(-2).join(".")}
              </span>
              <button
                type="button"
                onClick={() => onDelete(e.account)}
                aria-label={`Delete ${e.account}`}
                className="btn btn--ghost secrets-del-btn"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  );
}
