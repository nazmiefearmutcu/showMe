import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  type DataGridColumn,
  Pill,
} from "@/design-system";
import { t } from "@/i18n";
import { useAppStore } from "@/lib/store";
import {
  fetchStreamStats,
  type StreamChannelStats,
} from "@/lib/sidecar";
import { SummaryStat } from "./migration";

export function StreamsSection() {
  const port = useAppStore((s) => s.sidecarPort);
  const [stats, setStats] = useState<Awaited<ReturnType<typeof fetchStreamStats>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setLoading(true);
    fetchStreamStats()
      .then((res) => !cancelled && setStats(res))
      .catch((err) => !cancelled && setError(String(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [port, tick]);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 2500);
    return () => clearInterval(id);
  }, []);

  const rows = stats?.channels ?? [];
  const subscribers = rows.reduce((sum, row) => sum + row.subscribers, 0);
  const cols = useMemo<DataGridColumn<StreamChannelStats>[]>(
    () => [
      { key: "symbol", header: "Symbol", width: 120 },
      {
        key: "subscribers",
        header: "Subs",
        numeric: true,
        width: 80,
      },
      {
        key: "last_price",
        header: "Last",
        numeric: true,
        width: 120,
        render: (row) =>
          row.last_price == null
            ? "-"
            : row.last_price.toLocaleString(undefined, {
                maximumFractionDigits: 6,
              }),
      },
      {
        key: "source",
        header: "Source",
        width: 100,
        render: (row) => row.source ?? "-",
      },
    ],
    [],
  );

  return (
    <Card>
      <CardHeader
        trailing={
          <span className="u-flex u-gap-6 u-items-center">
            <Pill tone={subscribers > 0 ? "positive" : "muted"} withDot={subscribers > 0}>
              {subscribers} subs
            </Pill>
            <button
              type="button"
              onClick={() => setTick((t) => t + 1)}
              className="btn btn--ghost u-btn-24"
              aria-label="Refresh stream stats"
              aria-busy={loading}
            >
              Refresh
            </button>
          </span>
        }
      >
        {t("preferences.streams")}
      </CardHeader>
      <CardBody>
        <div className="streams-stat-grid">
          <SummaryStat label="channels" value={rows.length} />
          <SummaryStat label="subscribers" value={subscribers} />
          <SummaryStat
            label="status"
            value={error ? "error" : subscribers > 0 ? "live" : "idle"}
          />
        </div>

        {error ? (
          <pre role="alert" className="streams-error">{error}</pre>
        ) : loading && rows.length === 0 ? (
          <div role="status" aria-live="polite" className="u-text-mute u-text-12">
            loading stream channels…
          </div>
        ) : rows.length === 0 ? (
          <div className="u-text-mute u-text-12">
            no active stream channels
          </div>
        ) : (
          <DataGrid
            columns={cols}
            rows={rows}
            rowKey={(row) => row.symbol}
            density="compact"
          />
        )}
      </CardBody>
    </Card>
  );
}
