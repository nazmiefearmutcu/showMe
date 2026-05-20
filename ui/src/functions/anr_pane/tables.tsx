import { useEffect, useMemo, useState } from "react";
import {
  Card,
  CardBody,
  CardHeader,
  DataGrid,
  Field,
  FieldRow,
  Pill,
  type DataGridColumn,
} from "@/design-system";
import type {
  ANRData,
  ANRSummary,
  AlertRule,
  AnalystRow,
  BucketRow,
  SignalRow,
  SourceDetail,
} from "./_types";
import {
  formatDateTime,
  formatInt,
  formatMoney,
  formatPct,
  formatScore,
  loadAlert,
  providerLabel,
} from "./formatters";
import { labelStyle, selectStyle } from "./styles";

export function AnalystTable({
  rows,
  detailStatus,
  detailReason,
}: {
  rows: AnalystRow[];
  detailStatus?: string;
  detailReason?: string;
}) {
  const cols = useMemo<DataGridColumn<AnalystRow>[]>(
    () => [
      { key: "broker", header: "Broker", width: 130, render: (r) => r.broker ?? "—" },
      { key: "analyst", header: "Analyst", width: 150, render: (r) => r.analyst ?? "—" },
      { key: "rating", header: "Rating", width: 100, render: (r) => r.rating ?? "—" },
      { key: "previous_rating", header: "Previous", width: 110, render: (r) => r.previous_rating ?? "—" },
      { key: "action", header: "Action", width: 105, render: (r) => r.action ?? "—" },
      { key: "target_price", header: "Target price", width: 115, numeric: true, render: (r) => formatMoney(r.target_price) },
      { key: "target_period", header: "Period", width: 85, render: (r) => r.target_period ?? "—" },
      { key: "date", header: "Date", width: 100, render: (r) => r.date ?? "—" },
      { key: "last_update", header: "Last update", width: 115, render: (r) => r.last_update ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader
        trailing={<Pill tone={rows.length ? "positive" : "warn"} variant="soft">{detailStatus ? providerLabel(detailStatus) : "broker feed"}</Pill>}
      >
        Analyst-Level Ratings
      </CardHeader>
      <CardBody>
        <DataGrid
          columns={cols}
          rows={rows}
          density="compact"
          empty={
            <span>
              Broker-level analyst feed is not configured. Aggregate consensus is shown above; no
              broker or analyst rows are fabricated.
            </span>
          }
        />
        {detailReason ? (
          <p className="anr-detail-reason">{detailReason}</p>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function SignalInputsTable({ rows, detailReason }: { rows: SignalRow[]; detailReason?: string }) {
  const cols = useMemo<DataGridColumn<SignalRow>[]>(
    () => [
      { key: "signal", header: "Signal", width: 170, render: (r) => r.signal ?? "—" },
      { key: "value", header: "Value", width: 120, render: (r) => r.value ?? "—" },
      { key: "score", header: "Score", width: 80, numeric: true, render: (r) => formatScore(r.score) },
      { key: "weight", header: "Weight", width: 80, numeric: true, render: (r) => formatPct(Number(r.weight ?? 0) * 100) },
      { key: "source", header: "Source", width: 130, render: (r) => providerLabel(r.source) },
      { key: "explanation", header: "Meaning", width: "1fr", render: (r) => r.explanation ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader trailing={<Pill tone={rows.length ? "positive" : "warn"} variant="soft">{rows.length ? "live proxy" : "no signals"}</Pill>}>
        Crypto Consensus Inputs
      </CardHeader>
      <CardBody>
        <DataGrid
          columns={cols}
          rows={rows}
          density="compact"
          empty="crypto market-data signals unavailable"
        />
        {detailReason ? (
          <p className="anr-detail-reason">{detailReason}</p>
        ) : null}
      </CardBody>
    </Card>
  );
}

export function BucketTable({ rows }: { rows: BucketRow[] }) {
  const cols = useMemo<DataGridColumn<BucketRow>[]>(
    () => [
      { key: "bucket", header: "Bucket", width: "1fr", render: (r) => r.bucket ?? "—" },
      { key: "count", header: "Count", width: 90, numeric: true, render: (r) => formatInt(r.count) },
      { key: "pct_of_consensus", header: "%", width: 80, numeric: true, render: (r) => formatPct(r.pct_of_consensus) },
      { key: "sentiment_score", header: "Score", width: 80, numeric: true, render: (r) => formatInt(r.sentiment_score) },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader>Bucket Distribution</CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={rows} density="compact" empty="bucket rows unavailable" />
      </CardBody>
    </Card>
  );
}

export function AlertEditor({ symbol, summary }: { symbol: string; summary: ANRSummary }) {
  const storageKey = `showme.anr.alert.${symbol}`;
  const [enabled, setEnabled] = useState(false);
  const [rule, setRule] = useState<AlertRule>("label_change");
  const [threshold, setThreshold] = useState("");
  const [savedAt, setSavedAt] = useState<string | undefined>(undefined);

  useEffect(() => {
    const saved = loadAlert(storageKey);
    setEnabled(saved.enabled);
    setRule(saved.rule);
    setThreshold(saved.threshold);
    setSavedAt(saved.savedAt);
  }, [storageKey]);

  const save = () => {
    const next = {
      enabled,
      rule,
      threshold,
      savedAt: new Date().toISOString(),
    };
    localStorage.setItem(storageKey, JSON.stringify(next));
    setSavedAt(next.savedAt);
  };

  return (
    <Card>
      <CardHeader trailing={<Pill tone={enabled ? "positive" : "muted"} variant="soft" withDot={enabled}>{enabled ? "on" : "off"}</Pill>}>
        Recommendation Alert
      </CardHeader>
      <CardBody>
        <div className="u-grid-gap-10">
          <FieldRow>
            <label className="u-grid-gap-4">
              <span style={labelStyle}>Rule</span>
              <select
                value={rule}
                onChange={(e) => setRule(e.target.value as AlertRule)}
                style={selectStyle}
              >
                <option value="label_change">Consensus label changes</option>
                <option value="score_below">Consensus score below</option>
                <option value="score_above">Consensus score above</option>
                <option value="positive_pct_below">Positive pct below</option>
              </select>
            </label>
            <Field
              label="Threshold"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
              placeholder={rule.includes("pct") ? "60" : "3.5"}
              disabled={rule === "label_change"}
            />
          </FieldRow>
          <label className="anr-alert-checkbox">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            Enable local ANR alert draft for {symbol}
          </label>
          <div className="u-flex u-items-center u-justify-between u-gap-8">
            <span className="u-text-12 u-text-secondary">
              Current consensus: {formatScore(summary.consensus_score)} / 5 · {summary.label ?? "—"}
            </span>
            <button type="button" className="btn" onClick={save}>
              Save alert
            </button>
          </div>
          <span className="u-text-11 u-text-mute">
            Saved: {savedAt ? formatDateTime(savedAt) : "—"} · editable from this ANR panel.
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

export function SourceFreshness({ sources }: { sources: SourceDetail[] }) {
  const cols = useMemo<DataGridColumn<SourceDetail>[]>(
    () => [
      { key: "name", header: "Source", width: 145, render: (r) => providerLabel(r.name) },
      { key: "status", header: "Status", width: 180, render: (r) => providerLabel(r.status) },
      { key: "asOf", header: "As of", width: 115, render: (r) => r.asOf ?? "—" },
      { key: "fields", header: "Fields", width: "1fr", render: (r) => r.fields ?? "—" },
    ],
    [],
  );
  return (
    <Card>
      <CardHeader>Source & Freshness</CardHeader>
      <CardBody>
        <DataGrid columns={cols} rows={sources} density="compact" empty="source details unavailable" />
      </CardBody>
    </Card>
  );
}

export function AnalystQuality({ status, crypto }: { status?: string; crypto?: boolean }) {
  const brokerAvailable = status === "broker_actions_available";
  const tone = brokerAvailable ? "positive" : "warn";
  return (
    <Card>
      <CardHeader trailing={<Pill tone={tone} variant="soft">{status ? providerLabel(status) : "provider not configured"}</Pill>}>
        {crypto ? "Consensus Quality" : "Analyst Quality"}
      </CardHeader>
      <CardBody>
        <p className="anr-card-meaning">
          {crypto
            ? "Crypto consensus quality is limited by live quote/OHLCV coverage. Sell-side analyst hit-rate scoring is not applicable unless a real broker-level crypto research feed is configured."
            : brokerAvailable
              ? "Broker rating actions (upgrades / downgrades / target revisions) are available from the configured provider. Full analyst hit-rate scoring still requires named-analyst identifiers and realized forward returns, which this provider does not supply."
              : "Analyst accuracy scoring requires broker-level historical ratings, target prices, realized returns, and revision history. The current configured ANR feed is aggregate-level, so ShowMe exposes the missing provider state instead of presenting a synthetic accuracy score."}
        </p>
      </CardBody>
    </Card>
  );
}

export function Methodology({ data }: { data: ANRData }) {
  const entries = Object.entries(data.field_dictionary ?? {}).filter(([, value]) =>
    value != null && String(value).trim().length > 0,
  );
  return (
    <Card density="compact">
      <CardHeader>Methodology</CardHeader>
      <CardBody>
        <div className="u-grid-gap-10 u-text-12">
          {data.methodology ? (
            <p className="anr-methodology-text">{data.methodology}</p>
          ) : null}
          {entries.length ? (
            <dl className="anr-methodology-dl">
              {entries.map(([key, value]) => (
                <span key={key} className="anr-methodology-row">
                  <dt className="u-text-mute u-mono">{key}</dt>
                  <dd className="anr-methodology-dd">{value}</dd>
                </span>
              ))}
            </dl>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

export function StatGrid({ items }: { items: [string, string][] }) {
  return (
    <div className="anr-stat-grid">
      {items.map(([label, value]) => (
        <div key={label} className="anr-stat-card">
          <div className="anr-stat-card__label">{label}</div>
          <div title={value} className="anr-stat-card__value">{value}</div>
        </div>
      ))}
    </div>
  );
}
