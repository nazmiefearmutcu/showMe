import { useMemo } from "react";
import {
  DataGrid,
  Empty,
  Pill,
} from "@/design-system";
import { relativeTimeLabel, sortNewsNewestFirst } from "@/lib/time";
import type { FunctionEntry } from "@/lib/sidecar";
import { SeriesChart } from "./charts";
import type {
  ControlProfile,
  FunctionCallResult,
  MediaItem,
  MetricCard,
  PayloadStatus,
  RecordRow,
  ResultSummary,
} from "./_types";
import {
  asStringArray,
  buildColumns,
  extractChartSeries,
  extractFieldDictionary,
  extractMediaItems,
  extractMethodology,
  extractMetricCards,
  firstString,
  formatElapsed,
  formatTime,
  formatValue,
  humanizeKey,
  isRecord,
  isSyntheticText,
  motionDelayClass,
  newsRowTimestamp,
  renderMarkdownLine,
  rowsLookLikeOhlc,
  stableRowKey,
  stripHtml,
  stripMarkdown,
} from "./helpers";
import {
  briefBullet,
  briefBulletMark,
  briefPanel,
  briefSubhead,
  briefText,
  briefTitle,
  compactStatusBox,
  detailsBox,
  fieldDictionaryGrid,
  fieldDictionaryRow,
  kvPanel,
  kvRow,
  mediaCaption,
  mediaFigure,
  mediaGrid,
  mediaImage,
  metaLabel,
  methodologyPanel,
  methodologyText,
  metricRibbon,
  metricRibbonItem,
  metricRibbonValue,
  newsItem,
  newsList,
  newsSummary,
  newsTitle,
  preStyle,
  reasonBadge,
  resultMetaLine,
  sourceBadge,
  sourceStrip,
  statusBox,
  warningBox,
} from "./styles";

export function GenericResult({
  result,
  summary,
  payloadStatus,
  onRetry,
}: {
  result: FunctionCallResult<unknown>;
  summary: ResultSummary;
  payloadStatus: PayloadStatus;
  onRetry: () => void;
}) {
  const chart = useMemo(
    () => extractChartSeries(result.data, summary.rows),
    [result.data, summary.rows],
  );
  const mediaItems = useMemo(() => extractMediaItems(result.data), [result.data]);
  const metricCards = useMemo(() => extractMetricCards(result.data), [result.data]);
  const methodology = useMemo(() => extractMethodology(result.data), [result.data]);
  const fieldDictionary = useMemo(() => extractFieldDictionary(result.data), [result.data]);
  const displayRows = useMemo(
    () => (summary.rows.length ? summary.rows : (chart?.rows ?? [])),
    [summary.rows, chart?.rows],
  );
  const suppressOhlcRowsTable = useMemo(
    () => Boolean(chart && rowsLookLikeOhlc(displayRows)),
    [chart, displayRows],
  );
  const displayColumns = useMemo(() => buildColumns(displayRows), [displayRows]);
  const articleRows = displayRows.filter(isArticleRow);
  const shouldRenderArticleList =
    !suppressOhlcRowsTable && articleRows.length > 0 && articleRows.length === displayRows.length;
  const hasScalarResult = metricCards.length > 0 || summary.keyValues.length > 0;
  const briefMarkdown =
    result.code?.toUpperCase() === "BRIEF" && isRecord(result.data)
      ? firstString(result.data, ["markdown"])
      : null;
  return (
    <div className="showme-stub-payload u-grid-gap-12" data-testid="function-payload">
      {payloadStatus.state !== "live" ? (
        <StatusPanel status={payloadStatus} onRetry={onRetry} />
      ) : null}

      <ResultMetaLine result={result} summary={summary} />

      {briefMarkdown ? <BriefPanel markdown={briefMarkdown} /> : null}

      {mediaItems.length > 0 ? <MediaPreview items={mediaItems} /> : null}

      {metricCards.length > 0 ? <MetricRibbon metrics={metricCards} /> : null}

      {chart ? <SeriesChart chartId={result.code?.toUpperCase() ?? "GENERIC"} series={chart} /> : null}

      {methodology || fieldDictionary.length > 0 ? (
        <MethodologyPanel methodology={methodology} fields={fieldDictionary} />
      ) : null}

      {shouldRenderArticleList ? (
        <NewsList rows={articleRows} />
      ) : displayRows.length > 0 && !suppressOhlcRowsTable ? (
        <DataGrid
          className="showme-stub-grid showme-motion-grid"
          columns={displayColumns}
          rows={displayRows.slice(0, 500)}
          rowKey={stableRowKey}
          rowClassName={(_, idx) =>
            [
              "showme-row-reveal",
              "showme-motion-grid__row",
              motionDelayClass(idx),
            ].join(" ")
          }
          density="compact"
        />
      ) : payloadStatus.state === "live" && !hasScalarResult ? (
        <Empty
          title="No usable rows"
          body={
            result.warnings?.length
              ? "The function completed but only returned warnings or metadata."
              : "The function completed without chartable or tabular data."
          }
        />
      ) : null}

      {summary.keyValues.length > 0 && (
        <section className="showme-card-reveal showme-stub-block" style={kvPanel}>
          {summary.keyValues.map(([key, value]) => (
            <div key={key} className="showme-row-reveal showme-stub-kv-row" style={kvRow}>
              <span className="u-text-mute">{key}</span>
              <span className="u-text-primary">{formatValue(value)}</span>
            </div>
          ))}
        </section>
      )}

      <SourceStrip result={result} />

      <details className="showme-card-reveal showme-stub-block" style={detailsBox}>
        <summary className="u-cursor-default u-text-accent">
          Raw function payload
        </summary>
        <pre style={preStyle}>{JSON.stringify(result, null, 2)}</pre>
      </details>
    </div>
  );
}

function isArticleRow(row: RecordRow): boolean {
  return Boolean(firstString(row, ["headline", "title"]) && firstString(row, ["source", "url", "link"]));
}

export function BriefPanel({ markdown }: { markdown: string }) {
  const lines = markdown.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return (
    <section className="showme-card-reveal showme-stub-block" style={briefPanel}>
      {lines.slice(0, 34).map((line, idx) => {
        if (line.startsWith("## ")) {
          return <h3 key={`${line}-${idx}`} style={briefSubhead}>{stripMarkdown(line.slice(3))}</h3>;
        }
        if (line.startsWith("# ")) {
          return <h2 key={`${line}-${idx}`} style={briefTitle}>{stripMarkdown(line.slice(2))}</h2>;
        }
        if (line.startsWith("- ")) {
          return (
            <div key={`${line}-${idx}`} style={briefBullet}>
              <span style={briefBulletMark}>-</span>
              <span>{renderMarkdownLine(line.slice(2))}</span>
            </div>
          );
        }
        return <p key={`${line}-${idx}`} style={briefText}>{renderMarkdownLine(line)}</p>;
      })}
    </section>
  );
}

export function ResultMetaLine({
  result,
  summary,
}: {
  result: FunctionCallResult<unknown>;
  summary: ResultSummary;
}) {
  const fields = summary.fields.length || summary.keyValues.length;
  const sources = result.sources?.length ?? 0;
  const warnings = result.warnings?.length ?? 0;
  return (
    <div style={resultMetaLine}>
      <span data-testid={!result.status || result.status === "ok" ? "function-status" : undefined}>
        {result.status ?? "ok"}
      </span>
      <span>{summary.shape}</span>
      <span>{summary.rows.length} rows</span>
      <span>{fields} fields</span>
      <span>{sources} sources</span>
      {warnings ? <span>{warnings} warnings</span> : null}
      <span>{formatElapsed(result.elapsed_ms)}</span>
      <span>{formatTime(result.fetched_at)}</span>
    </div>
  );
}

export function FunctionHelp({
  code,
  entry,
  symbolFirst,
  controlProfile,
}: {
  code: string;
  entry: FunctionEntry | null;
  symbolFirst: boolean;
  controlProfile: ControlProfile;
}) {
  const usage = entry?.usage;
  const controls = [
    symbolFirst ? "Symbol field selects the market target." : `Scope: ${usage?.scope ?? "global"}.`,
    controlProfile.queryParam === "symbols"
      ? "WATCHLIST field sends comma-separated symbols without JSON editing."
      : controlProfile.queryParam
        ? `${controlProfile.queryParam.toUpperCase()} field changes the backend search text without JSON editing.`
        : null,
    controlProfile.limit ? "ROW controls the result count sent to the backend." : null,
    controlProfile.days ? "RANGE maps to the backend time horizon." : null,
    controlProfile.tradeTicket ? "Ticket controls set side, quantity, order type, and TIF; Run stays preview-only with submit=false." : null,
    "Advanced opens JSON overrides only when you need raw backend params.",
    "Deep inserts the broader-provider flag for functions that support it.",
  ].filter(Boolean);
  const steps = usage?.steps?.length ? usage.steps : controls;
  return (
    <div className="fn-help-grid">
      <strong>
        {code} · {entry?.name ?? "ShowMe function"}
      </strong>
      <span className="fn-help-grid__hint">
        {usage?.purpose || entry?.description || "Run the function, inspect the source strip, then adjust inputs and rerun."}
      </span>
      {usage?.inputs?.length ? (
        <span className="fn-help-grid__hint-mute">
          Inputs: {usage.inputs.join(", ")}
        </span>
      ) : null}
      <div className="u-grid-gap-4">
        {steps.map((line) => (
          <span key={line} className="u-text-mute">
            {line}
          </span>
        ))}
      </div>
    </div>
  );
}

export function StatusPanel({
  status,
  compact = false,
  onRetry,
}: {
  status: PayloadStatus;
  compact?: boolean;
  onRetry?: () => void;
}) {
  const tone = status.state === "unavailable" ? "negative" : "warn";
  return (
    <section
      className="showme-card-reveal showme-stub-block"
      style={compact ? compactStatusBox : statusBox}
      data-testid="function-status-panel"
    >
      <div className="status-panel__head">
        <div className="u-grid-gap-4">
          <Pill tone={tone} withDot={status.state === "degraded"}>
            <span data-testid="function-status">{status.label}</span>
          </Pill>
          <strong className="u-text-primary">{status.title}</strong>
        </div>
        {onRetry ? (
          <button type="button" className="btn btn--ghost" onClick={onRetry}>
            Retry
          </button>
        ) : null}
      </div>
      {status.reasons.length > 0 ? (
        <div className="u-grid-gap-4">
          {status.reasons.slice(0, compact ? 2 : 6).map((reason, idx) => (
            <span
              key={`${reason}-${idx}`}
              className="u-text-secondary"
              data-testid={idx === 0 ? "function-reason" : undefined}
            >
              {reason}
            </span>
          ))}
        </div>
      ) : null}
      {status.actions.length > 0 ? (
        <div className="u-grid-gap-4">
          {status.actions.slice(0, compact ? 2 : 6).map((action, idx) => (
            <span
              key={`${action}-${idx}`}
              className="u-text-mute"
              data-testid={idx === 0 ? "function-next-action" : undefined}
            >
              {action}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function NewsList({ rows }: { rows: RecordRow[] }) {
  const sortedRows = useMemo(
    () => sortNewsNewestFirst(rows, newsRowTimestamp),
    [rows],
  );
  return (
    <section className="showme-stub-news-list" style={newsList}>
      {sortedRows.slice(0, 40).map((row, idx) => {
        const title = firstString(row, ["headline", "title", "name"]) || `Item ${idx + 1}`;
        const url = firstString(row, ["url", "link"]);
        const source = firstString(row, ["source", "publisher", "provider"]) || "-";
        const time = newsRowTimestamp(row);
        const summary = firstString(row, ["summary", "description", "snippet"]);
        const severity = firstString(row, ["severity", "importance"]);
        const score = firstString(row, ["importance_score", "impact_score", "score"]);
        const alert = row.alert === true || severity === "critical" || severity === "high";
        const reasons = Array.isArray(row.importance_reasons)
          ? row.importance_reasons.map(String).slice(0, 3)
          : [];
        return (
          <article
            key={stableRowKey(row, idx)}
            className={`showme-card-reveal showme-stub-block ${motionDelayClass(idx)}`}
            style={newsItem}
          >
            <div className="news-row__head">
              {url ? (
                <a href={url} target="_blank" rel="noreferrer" style={newsTitle}>
                  {title}
                </a>
              ) : (
                <strong style={newsTitle}>{title}</strong>
              )}
              <div className="news-row__badges">
                {severity ? (
                  <Pill tone={alert ? "negative" : severity === "medium" ? "warn" : "muted"} withDot={alert}>
                    {severity}{score ? ` ${score}` : ""}
                  </Pill>
                ) : null}
                <span style={sourceBadge}>{source}</span>
              </div>
            </div>
            {summary ? <p style={newsSummary}>{stripHtml(summary)}</p> : null}
            <div className="news-row__meta">
              {time ? <span style={metaLabel}>{relativeTimeLabel(time) ?? time}</span> : null}
              {reasons.map((reason) => (
                <span key={reason} style={reasonBadge}>{reason}</span>
              ))}
            </div>
          </article>
        );
      })}
    </section>
  );
}

export function MediaPreview({ items }: { items: MediaItem[] }) {
  return (
    <section className="showme-stub-media-grid" style={mediaGrid}>
      {items.map((item) => (
        <figure
          key={`${item.label}:${item.src.slice(0, 40)}`}
          className="showme-card-reveal showme-stub-block"
          style={mediaFigure}
        >
          <img src={item.src} alt={item.label} style={mediaImage} />
          <figcaption style={mediaCaption}>
            <span>{item.label}</span>
            {item.note ? <span style={metaLabel}>{item.note}</span> : null}
          </figcaption>
        </figure>
      ))}
    </section>
  );
}

export function MetricRibbon({ metrics }: { metrics: MetricCard[] }) {
  return (
    <section className="showme-stub-metric-ribbon" style={metricRibbon}>
      {metrics.slice(0, 12).map((metric) => (
        <div
          key={metric.label}
          className="showme-card-reveal showme-stub-block showme-stub-metric"
          style={metricRibbonItem}
        >
          <span style={metaLabel}>{humanizeKey(metric.label)}</span>
          <strong style={metricRibbonValue}>{formatValue(metric.value)}</strong>
        </div>
      ))}
    </section>
  );
}

export function MethodologyPanel({
  methodology,
  fields,
}: {
  methodology: string | null;
  fields: Array<[string, string]>;
}) {
  return (
    <section className="showme-card-reveal showme-stub-block" style={methodologyPanel}>
      {methodology ? (
        <div>
          <div style={metaLabel}>Methodology</div>
          <p style={methodologyText}>{methodology}</p>
        </div>
      ) : null}
      {fields.length > 0 ? (
        <div>
          <div style={metaLabel}>Field dictionary</div>
          <div style={fieldDictionaryGrid}>
            {fields.map(([field, description]) => (
              <div key={field} className="showme-row-reveal showme-stub-kv-row" style={fieldDictionaryRow}>
                <span className="u-text-primary">{field}</span>
                <span>{description}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function SourceStrip({ result }: { result: FunctionCallResult<unknown> }) {
  const providerErrors = asStringArray(result.metadata?.provider_errors);
  return (
    <section className="showme-card-reveal showme-stub-block" style={sourceStrip} data-testid="function-source">
      <div>
        <span style={metaLabel}>Sources</span>
        <div className="source-strip__pills">
          {(result.sources?.length ? result.sources : ["none"]).map((source) => (
            <Pill key={source} tone={isSyntheticText(source) ? "negative" : "muted"} withDot={false}>
              {source}
            </Pill>
          ))}
        </div>
      </div>
      {providerErrors.length > 0 ? (
        <div style={warningBox}>
          {providerErrors.slice(0, 5).map((w, i) => (
            <div key={`${w}-${i}`}>{w}</div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
