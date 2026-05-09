import { useEffect, useMemo, useState } from "react";
import {
  DataGrid,
  type DataGridColumn,
  Field,
  Pane,
  PaneBody,
  PaneFooter,
  PaneHeader,
  Pill,
  Skeleton,
} from "@/design-system";
import {
  capabilities,
  requestBiometric,
  type BiometricCapabilities,
  type BiometricResult,
} from "@/lib/biometric";
import { FunctionControlGroup, LoadStatePill, RefreshButton } from "./function-controls";
import type { FunctionPaneProps } from "./registry-types";

type BioRow = {
  item: string;
  status: string;
  detail: string;
};

export function BIOPane({ code }: FunctionPaneProps) {
  const [caps, setCaps] = useState<BiometricCapabilities | null>(null);
  const [result, setResult] = useState<BiometricResult | null>(null);
  const [reason, setReason] = useState("ShowMe biometric verification");
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setCaps(null);
    setCaps(await capabilities());
  };

  useEffect(() => {
    void refresh();
  }, []);

  const verify = async () => {
    setLoading(true);
    try {
      setResult(await requestBiometric(reason.trim() || "ShowMe biometric verification"));
      setCaps(await capabilities());
    } finally {
      setLoading(false);
    }
  };

  const rows = useMemo<BioRow[]>(() => {
    if (!caps) return [];
    return [
      {
        item: "Biometry",
        status: caps.biometry_available ? "available" : "unavailable",
        detail: caps.biometry_kind.replace("_", " "),
      },
      {
        item: "Device passcode",
        status: caps.passcode_available ? "available" : "unavailable",
        detail: "macOS LocalAuthentication owner policy",
      },
      {
        item: "Last verify",
        status: result ? (result.allowed ? "allowed" : "denied") : "not run",
        detail: result ? `${result.via} · ${result.reason}` : "Click Verify to open the OS prompt.",
      },
    ];
  }, [caps, result]);

  const cols = useMemo<DataGridColumn<BioRow>[]>(
    () => [
      { key: "item", header: "Item", width: 150 },
      {
        key: "status",
        header: "Status",
        width: 120,
        render: (row) => (
          <Pill
            tone={row.status === "available" || row.status === "allowed" ? "positive" : "muted"}
            withDot={false}
          >
            {row.status}
          </Pill>
        ),
      },
      { key: "detail", header: "Detail" },
    ],
    [],
  );

  return (
    <div style={{ padding: 18, height: "100%" }}>
      <Pane>
        <PaneHeader
          code={code}
          title="Biometric Auth"
          subtitle="macOS LocalAuthentication"
          trailing={
            <FunctionControlGroup>
              <LoadStatePill state={caps ? "ok" : "loading"} />
              <button className="btn btn--accent" type="button" onClick={verify} disabled={loading || !caps}>
                Verify
              </button>
              <RefreshButton loading={!caps} onClick={refresh} title="Refresh capabilities" />
            </FunctionControlGroup>
          }
        />
        <PaneBody>
          <Field
            label="Prompt reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Reason shown in the OS prompt"
          />
          <div style={{ marginTop: 12 }}>
            {!caps ? (
              <Skeleton height={100} />
            ) : (
              <DataGrid columns={cols} rows={rows} rowKey={(row) => row.item} density="compact" />
            )}
          </div>
        </PaneBody>
        <PaneFooter>
          <span>secret storage · none</span>
          <span>prompt · user initiated</span>
        </PaneFooter>
      </Pane>
    </div>
  );
}
