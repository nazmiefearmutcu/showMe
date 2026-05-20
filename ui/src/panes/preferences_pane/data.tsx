import { Card, CardBody, CardHeader, Field, FieldRow, Pill } from "@/design-system";
import { t } from "@/i18n";
import { invoke } from "@/lib/tauri";
import { toast } from "@/lib/toast";
import { useAppStore } from "@/lib/store";
import { btnStyle } from "./_types";

export function DataSection() {
  const engineRoot = useAppStore((s) => s.engineRoot);
  const port = useAppStore((s) => s.sidecarPort);
  const status = useAppStore((s) => s.sidecarStatus);

  const reveal = async () => {
    try {
      await invoke("open_data_folder");
    } catch (err) {
      toast.error("Reveal failed", String(err));
    }
  };

  return (
    <>
      <Card>
        <CardHeader
          trailing={
            <Pill
              tone={engineRoot ? "positive" : "muted"}
              withDot={false}
            >
              {engineRoot ? "attached" : "detached"}
            </Pill>
          }
        >
          {t("preferences.data.engine") || "Engine"}
        </CardHeader>
        <CardBody>
          <FieldRow>
            <Field
              label={t("preferences.data.engine_root")}
              value={engineRoot ?? ""}
              placeholder="/path/to/ShowMe"
              readOnly
            />
          </FieldRow>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <Pill tone="positive" withDot={false}>
              writable
            </Pill>
          }
        >
          {t("preferences.data.app_data_folder") || "App data folder"}
        </CardHeader>
        <CardBody>
          <FieldRow>
            <Field
              label={t("preferences.data.app_data")}
              value="~/Library/Application Support/showMe"
              readOnly
              trailing={
                <button type="button" onClick={reveal} style={btnStyle}>
                  {t("preferences.data.reveal")}
                </button>
              }
            />
          </FieldRow>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          trailing={
            <Pill
              tone={status === "healthy" ? "positive" : "warn"}
              withDot={false}
            >
              {status}
            </Pill>
          }
        >
          {t("preferences.data.sidecar_bridge") || "Sidecar bridge"}
        </CardHeader>
        <CardBody>
          <FieldRow>
            <Field
              label={t("preferences.data.http_endpoint") || "HTTP endpoint"}
              value={port ? `http://127.0.0.1:${port}` : "—"}
              readOnly
            />
            <Field
              label={t("preferences.data.api_version") || "API version"}
              value={port ? "v3" : "—"}
              readOnly
            />
          </FieldRow>
        </CardBody>
      </Card>
    </>
  );
}
