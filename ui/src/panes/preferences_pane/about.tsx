import { useState } from "react";
import { Card, CardBody, CardHeader, Pill } from "@/design-system";
import { t } from "@/i18n";
import { invoke, isInTauri } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { fetchSidecarInfo } from "@/lib/sidecar";
import { applyUpdate, checkForUpdates, type UpdateInfo } from "@/lib/updater";
import type { InstallResult } from "./_types";

export function AboutSection({
  info,
}: {
  info: Awaited<ReturnType<typeof fetchSidecarInfo>> | null;
}) {
  const [check, setCheck] = useState<UpdateInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installResult, setInstallResult] = useState<InstallResult | null>(null);
  const inTauri = isInTauri();

  const onCheck = async () => {
    setBusy(true);
    try {
      const res = await checkForUpdates();
      setCheck(res);
      if (res.error) toast.warn("Updater error", res.error);
      else if (res.available)
        toast.info(
          "Update available",
          `${res.current_version} → ${res.latest_version}`,
        );
      else toast.info("Up to date", res.current_version);
    } catch (err) {
      toast.error("Updater failed", String(err));
    } finally {
      setBusy(false);
    }
  };

  const onApply = async () => {
    setApplying(true);
    try {
      await applyUpdate();
    } catch (err) {
      toast.error("Update failed", String(err));
      setApplying(false);
    }
  };

  const onInstall = async () => {
    if (!inTauri) {
      toast.warn("Native app required", "Build the app first, then install.");
      return;
    }
    setInstalling(true);
    try {
      const res = await invoke<InstallResult>("install_to_applications");
      setInstallResult(res);
      toast.success(
        res.already_installed ? "Already in Applications" : "Installed",
        res.target,
      );
    } catch (err) {
      toast.error("Install failed", String(err));
    } finally {
      setInstalling(false);
    }
  };

  return (
    <Card>
      <CardHeader
        trailing={
          <button
            type="button"
            onClick={onCheck}
            disabled={busy}
            aria-busy={busy}
            className="btn btn--accent u-btn-24"
          >
            {busy ? "Checking…" : "Check for updates"}
          </button>
        }
      >
        {t("preferences.about")}
      </CardHeader>
      <CardBody>
        <dl className="about-dl">
          <dt className="u-text-mute">{t("preferences.about.version")}</dt>
          <dd className="u-m-0">{info?.version ?? "—"}</dd>
          <dt className="u-text-mute">{t("preferences.about.python")}</dt>
          <dd className="about-dl__dd--mono">
            {info?.python?.split(" ")[0] ?? "—"}
          </dd>
          <dt className="u-text-mute">{t("preferences.about.tauri")}</dt>
          <dd className="u-m-0">2.x</dd>
          <dt className="u-text-mute">engine attached</dt>
          <dd className="u-m-0">
            {info?.engine?.engine_attached ? "yes" : "no"}
          </dd>
        </dl>

        <div className="about-card-row">
          <div>
            <div className="u-fw-700">Applications install</div>
            <div className="u-text-mute u-text-11">
              {inTauri
                ? "Copy this signed app bundle into /Applications."
                : "Available after running the native app build."}
            </div>
            {installResult && (
              <div className="about-install-target">{installResult.target}</div>
            )}
          </div>
          <button
            type="button"
            onClick={onInstall}
            disabled={installing || !inTauri}
            aria-busy={installing}
            className="btn btn--accent u-btn-26"
          >
            {installing ? "Installing..." : "Install to Applications"}
          </button>
        </div>

        {check && (
          <div
            className="about-card-row about-card-row--block"
            role={check.error ? "alert" : "status"}
            aria-live="polite"
          >
            <div className="u-flex u-gap-8 u-items-center">
              <Pill
                tone={
                  check.error ? "warn" : check.available ? "positive" : "muted"
                }
                withDot={false}
              >
                {check.error
                  ? "error"
                  : check.available
                    ? "update available"
                    : "up to date"}
              </Pill>
              <span className="u-text-mute">
                current {check.current_version}
                {check.latest_version
                  ? ` · latest ${check.latest_version}`
                  : ""}
              </span>
            </div>
            {check.release_notes && (
              <pre className="about-release-notes">{check.release_notes}</pre>
            )}
            {check.available && !check.error && (
              <div className="u-mt-10">
                <button
                  type="button"
                  onClick={onApply}
                  disabled={applying}
                  className="btn btn--accent u-btn-26"
                >
                  {applying ? "Downloading…" : "Download & restart"}
                </button>
              </div>
            )}
            {check.error && (
              <pre className="about-error-pre">{check.error}</pre>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
